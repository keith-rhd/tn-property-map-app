"""admin.py

Admin-only authentication + the financial dashboard.
"""

from __future__ import annotations

import hmac
import os
import time

import altair as alt
import pandas as pd
import streamlit as st


def _get_sales_manager_password() -> str | None:
    """Read the admin password.

    Prefers Streamlit secrets (Streamlit Cloud), falls back to an env var.
    """
    try:
        pw = st.secrets.get("sales_manager_password", None)
        if pw:
            return str(pw)
    except Exception:
        pass

    pw = os.environ.get("SALES_MANAGER_PASSWORD")
    return str(pw) if pw else None


def require_sales_manager_auth(*, session_timeout_seconds: int = 2 * 60 * 60) -> None:
    """Gate Admin view behind a password in the sidebar."""
    expected = _get_sales_manager_password()
    if not expected:
        st.sidebar.error(
            "Admin password is not configured.\n\n"
            "Add `sales_manager_password` in Streamlit Secrets "
            "or set env var `SALES_MANAGER_PASSWORD`."
        )
        st.stop()

    if st.session_state.get("sales_manager_authed") is True:
        authed_at = float(st.session_state.get("sales_manager_authed_at", 0) or 0)
        if authed_at and (time.time() - authed_at) > session_timeout_seconds:
            st.session_state["sales_manager_authed"] = False
            st.session_state["sales_manager_authed_at"] = 0

        if st.session_state.get("sales_manager_authed") is True:
            st.sidebar.markdown("## Admin access")
            if st.sidebar.button("Log out"):
                st.session_state["sales_manager_authed"] = False
                st.session_state["sales_manager_authed_at"] = 0
                # Rerun (Streamlit renamed this over time)
                if hasattr(st, "rerun"):
                    st.rerun()
                else:
                    st.experimental_rerun()
            return

    st.sidebar.markdown("## Admin access")
    entered = st.sidebar.text_input("Password", type="password")

    if entered and hmac.compare_digest(str(entered), str(expected)):
        st.session_state["sales_manager_authed"] = True
        st.session_state["sales_manager_authed_at"] = time.time()
        st.sidebar.success("Unlocked.")
        return

    st.sidebar.info("Enter the Admin password to continue.")
    st.stop()


def render_sales_manager_dashboard(
    df_sold_only: pd.DataFrame,
    *,
    headline: dict | None = None,
    county_table: pd.DataFrame | None = None,
) -> None:
    """Render the Admin financial dashboard.

    In Option B, `headline` and `county_table` are computed once upstream and passed in.
    We keep light fallbacks so the dashboard won’t hard-crash if called differently.
    """
    st.subheader("Financial dashboard")

    if df_sold_only is None or df_sold_only.empty:
        st.info("No SOLD deals found for the current filters.")
        return

    # ---- Headline metrics (prefer precomputed) ----
    if not headline:
        gp = pd.to_numeric(df_sold_only.get("Gross_Profit"), errors="coerce").fillna(0)
        total_gp = float(gp.sum())

        if "Wholesale_Price_num" in df_sold_only.columns:
            wholesale = pd.to_numeric(df_sold_only["Wholesale_Price_num"], errors="coerce").fillna(0)
        elif "Wholesale_Price" in df_sold_only.columns:
            wholesale = pd.to_numeric(df_sold_only["Wholesale_Price"], errors="coerce").fillna(0)
        else:
            wholesale = pd.Series([0] * len(df_sold_only), dtype="float")

        total_wholesale = float(wholesale.sum())
        sold_count = int(len(df_sold_only))
        avg_gp = float(total_gp / sold_count) if sold_count else 0.0

        headline = {
            "total_gp": total_gp,
            "total_wholesale": total_wholesale,
            "sold_count": sold_count,
            "avg_gp": avg_gp,
        }

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Gross Profit (GP)", f"${float(headline['total_gp']):,.0f}")
    c2.metric("Total Wholesale Volume", f"${float(headline['total_wholesale']):,.0f}")
    c3.metric("Sold Deals", f"{int(headline['sold_count']):,}")
    c4.metric("Avg GP / Sold Deal", f"${float(headline['avg_gp']):,.0f}")

    st.divider()

    # ---- Time series (light compute is fine) ----
    time_bucket = st.selectbox("Time bucket", ["Quarter", "Month"], index=0)

    df = df_sold_only.copy()
    df["Date_dt"] = pd.to_datetime(df.get("Date_dt"), errors="coerce")

    if time_bucket == "Month":
        df["Period"] = df["Date_dt"].dt.to_period("M").astype(str)
        period_label = "month"
    else:
        df["Period"] = df["Date_dt"].dt.to_period("Q").astype(str)
        period_label = "quarter"

    st.markdown(f"#### GP by {period_label}")
    gp_by_period = df.groupby("Period")["Gross_Profit"].sum().sort_index()
    
    gp_chart_df = gp_by_period.reset_index()
    gp_chart_df.columns = ["Period", "Gross Profit"]
    
    gp_chart = (
        alt.Chart(gp_chart_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("Period:N", sort=list(gp_chart_df["Period"]), title=period_label.title()),
            y=alt.Y("Gross Profit:Q", title="Gross Profit"),
            tooltip=["Period", alt.Tooltip("Gross Profit:Q", format=",.0f")],
        )
    )
    st.altair_chart(gp_chart, use_container_width=True)
    
    st.markdown(f"#### Sold deals by {period_label}")
    deals_by_period = df.groupby("Period").size().sort_index()
    
    deals_chart_df = deals_by_period.reset_index()
    deals_chart_df.columns = ["Period", "Sold Deals"]
    
    deals_chart = (
        alt.Chart(deals_chart_df)
        .mark_bar()
        .encode(
            x=alt.X("Period:N", sort=list(deals_chart_df["Period"]), title=period_label.title()),
            y=alt.Y("Sold Deals:Q", title="Sold Deals"),
            tooltip=["Period", "Sold Deals"],
        )
    )
    st.altair_chart(deals_chart, use_container_width=True)


    # ---- Pies (light compute is fine) ----
    pie_left, pie_right = st.columns(2)

    with pie_left:
        if "Dispo_Rep_clean" in df.columns:
            st.markdown("#### GP by Dispo Rep (share of total, top 10)")

            gp_by_rep = (
                df[df["Dispo_Rep_clean"].astype(str).str.strip() != ""]
                .groupby("Dispo_Rep_clean")["Gross_Profit"]
                .sum()
                .sort_values(ascending=False)
            )

            top_n = 10
            if len(gp_by_rep) > top_n:
                top = gp_by_rep.head(top_n)
                other = gp_by_rep.iloc[top_n:].sum()
                gp_by_rep_plot = pd.concat([top, pd.Series({"Other": other})])
            else:
                gp_by_rep_plot = gp_by_rep

            gp_by_rep_plot = gp_by_rep_plot[gp_by_rep_plot > 0]

            if gp_by_rep_plot.empty:
                st.info("Not enough positive GP to show Dispo Rep pie.")
            else:
                pie_df = gp_by_rep_plot.reset_index()
                pie_df.columns = ["Dispo Rep", "Gross Profit"]

                chart = (
                    alt.Chart(pie_df)
                    .mark_arc(innerRadius=50)
                    .encode(
                        theta=alt.Theta(field="Gross Profit", type="quantitative"),
                        color=alt.Color(field="Dispo Rep", type="nominal"),
                        tooltip=["Dispo Rep", alt.Tooltip("Gross Profit", format=",.0f")],
                    )
                )
                st.altair_chart(chart, use_container_width=True)

    with pie_right:
        if "Market_clean" in df.columns:
            st.markdown("#### GP by Market (share of total)")

            gp_by_mkt = (
                df[df["Market_clean"].astype(str).str.strip() != ""]
                .groupby("Market_clean")["Gross_Profit"]
                .sum()
                .sort_values(ascending=False)
            )

            top_n = 8
            if len(gp_by_mkt) > top_n:
                top = gp_by_mkt.head(top_n)
                other = gp_by_mkt.iloc[top_n:].sum()
                gp_by_mkt_plot = pd.concat([top, pd.Series({"Other": other})])
            else:
                gp_by_mkt_plot = gp_by_mkt

            gp_by_mkt_plot = gp_by_mkt_plot[gp_by_mkt_plot > 0]

            if gp_by_mkt_plot.empty:
                st.info("Not enough positive GP to show Market pie.")
            else:
                pie_df = gp_by_mkt_plot.reset_index()
                pie_df.columns = ["Market", "Gross Profit"]

                chart = (
                    alt.Chart(pie_df)
                    .mark_arc(innerRadius=50)
                    .encode(
                        theta=alt.Theta(field="Gross Profit", type="quantitative"),
                        color=alt.Color(field="Market", type="nominal"),
                        tooltip=["Market", alt.Tooltip("Gross Profit", format=",.0f")],
                    )
                )
                st.altair_chart(chart, use_container_width=True)

    # ---- County table (prefer precomputed) ----
    st.divider()
    st.markdown("### County GP (Admin)")

    if county_table is None:
        st.info("County GP table not provided (expected in Option B).")
        return

    if county_table.empty:
        st.info("No county summary available for the current filters.")
        return

    controls_left, controls_right = st.columns([1.2, 1.0])
    with controls_left:
        top_n = st.slider("Show top N counties", min_value=10, max_value=95, value=25, step=5)
    with controls_right:
        min_deals_for_avg = st.slider("Min sold deals for Avg GP ranking", min_value=1, max_value=15, value=3, step=1)

    by_avg_base = county_table[county_table["Sold Deals"] >= int(min_deals_for_avg)].copy()
    by_avg = by_avg_base.sort_values(["Avg GP", "Sold Deals"], ascending=[False, False]).head(int(top_n)).copy()

    counties_in_table = by_avg["County"].tolist()
    chart_df = (
        county_table[county_table["County"].isin(counties_in_table)]
        .sort_values("Total GP", ascending=False)
        .copy()
    )

    fmt_cols = {c: "${:,.0f}" for c in ["Total GP", "Avg GP", "Total Wholesale", "Avg Wholesale"] if c in county_table.columns}

    left, right = st.columns(2)

    with left:
        st.markdown("#### Total GP (same counties as Avg GP table)")
        bar = (
            alt.Chart(chart_df)
            .mark_bar()
            .encode(
                x=alt.X("Total GP:Q", title="Total GP"),
                y=alt.Y("County:N", sort=None, title=""),
                tooltip=[
                    "County",
                    alt.Tooltip("Total GP:Q", format=",.0f"),
                    alt.Tooltip("Avg GP:Q", format=",.0f"),
                    "Sold Deals",
                ],
            )
        )
        st.altair_chart(bar, use_container_width=True)
        st.caption("Chart counties are controlled by the Avg GP table filters (Top N + Min deals).")

    with right:
        st.markdown("#### Avg GP by County")
        show_cols = ["County", "Sold Deals", "Avg GP", "Total GP"]
        if "Avg Wholesale" in by_avg.columns:
            show_cols += ["Avg Wholesale"]
        st.dataframe(by_avg[show_cols].style.format(fmt_cols), use_container_width=True, hide_index=True)

    csv_bytes = county_table.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download full county GP table (CSV)",
        data=csv_bytes,
        file_name="county_gp_summary.csv",
        mime="text/csv",
    )
