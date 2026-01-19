"""admin.py

Admin-only authentication + the financial dashboard.

This module is split out of `app.py` so the main app stays easy to reason about.
"""

from __future__ import annotations

import os

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


def require_sales_manager_auth() -> None:
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
        return

    st.sidebar.markdown("## Admin access")
    entered = st.sidebar.text_input("Password", type="password")

    if entered and entered == expected:
        st.session_state["sales_manager_authed"] = True
        st.sidebar.success("Unlocked.")
        return

    st.sidebar.info("Enter the Admin password to continue.")
    st.stop()


def _safe_sum(series) -> float:
    try:
        return float(pd.to_numeric(series, errors="coerce").fillna(0).sum())
    except Exception:
        return 0.0


def _safe_mean(series) -> float:
    try:
        s = pd.to_numeric(series, errors="coerce").dropna()
        return float(s.mean()) if len(s) else 0.0
    except Exception:
        return 0.0


def _build_gp_by_county_table(df_sold: pd.DataFrame) -> pd.DataFrame:
    """Return a county-level GP summary table.

    Columns:
      - County
      - Sold Deals
      - Total GP
      - Avg GP
      - Total Wholesale (if available)
      - Avg Wholesale (if available)
    """
    if df_sold is None or df_sold.empty:
        return pd.DataFrame(columns=["County", "Sold Deals", "Total GP", "Avg GP"])

    county_col = None
    for c in ["County_clean_up", "County", "County_clean"]:
        if c in df_sold.columns:
            county_col = c
            break

    if not county_col:
        return pd.DataFrame(columns=["County", "Sold Deals", "Total GP", "Avg GP"])

    df = df_sold.copy()

    # Normalize numeric fields
    if "Gross_Profit" in df.columns:
        df["Gross_Profit_num"] = pd.to_numeric(df["Gross_Profit"], errors="coerce")
    else:
        df["Gross_Profit_num"] = pd.NA

    if "Wholesale_Price_num" in df.columns:
        df["Wholesale_Price_num2"] = pd.to_numeric(df["Wholesale_Price_num"], errors="coerce")
    elif "Wholesale_Price" in df.columns:
        df["Wholesale_Price_num2"] = pd.to_numeric(df["Wholesale_Price"], errors="coerce")
    else:
        df["Wholesale_Price_num2"] = pd.NA

    df[county_col] = df[county_col].astype(str).str.strip()
    df = df[df[county_col] != ""]
    df = df[df[county_col].str.lower() != "nan"]

    grp = df.groupby(county_col, dropna=True)

    out = pd.DataFrame(
        {
            "County": grp.size().index.astype(str),
            "Sold Deals": grp.size().values.astype(int),
            "Total GP": grp["Gross_Profit_num"].sum(min_count=1).fillna(0).values,
            "Avg GP": grp["Gross_Profit_num"].mean().fillna(0).values,
        }
    )

    # Wholesale optional
    if df["Wholesale_Price_num2"].notna().any():
        wholesale_sum = grp["Wholesale_Price_num2"].sum(min_count=1).fillna(0).values
        wholesale_avg = grp["Wholesale_Price_num2"].mean().fillna(0).values
        out["Total Wholesale"] = wholesale_sum
        out["Avg Wholesale"] = wholesale_avg

    # Clean + sort
    out["County"] = out["County"].astype(str).str.title()

    out = out.sort_values(["Total GP", "Sold Deals"], ascending=[False, False]).reset_index(drop=True)

    # Friendly rounding
    for col in ["Total GP", "Avg GP", "Total Wholesale", "Avg Wholesale"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)

    return out


def render_sales_manager_dashboard(df_sold: pd.DataFrame) -> None:
    """Render the Admin financial dashboard.

    Expects *sold rows only*.
    """
    st.subheader("Financial dashboard")

    if df_sold is None or df_sold.empty:
        st.info("No SOLD deals found for the current filters.")
        return

    total_gp = _safe_sum(df_sold.get("Gross_Profit"))
    total_wholesale = _safe_sum(df_sold.get("Wholesale_Price_num"))
    sold_count = int(len(df_sold))
    avg_gp = total_gp / sold_count if sold_count else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Gross Profit (GP)", f"${total_gp:,.0f}")
    c2.metric("Total Wholesale Volume", f"${total_wholesale:,.0f}")
    c3.metric("Sold Deals", f"{sold_count:,}")
    c4.metric("Avg GP / Sold Deal", f"${avg_gp:,.0f}")

    st.divider()

    # -------------------------
    # NEW: GP + Avg GP per county
    # -------------------------
    st.markdown("### GP by county")

    county_table = _build_gp_by_county_table(df_sold)

    if county_table.empty:
        st.info("County summary not available (missing county column).")
    else:
        left, right = st.columns([1.2, 1.0])
        with left:
            top_n = st.slider("Show top N counties (by Total GP)", min_value=10, max_value=95, value=25, step=5)
        with right:
            include_all = st.checkbox("Show all counties", value=False)

        show_df = county_table if include_all else county_table.head(int(top_n))

        # Display as formatted table
        fmt_cols = {c: "${:,.0f}" for c in show_df.columns if c in ["Total GP", "Avg GP", "Total Wholesale", "Avg Wholesale"]}
        st.dataframe(show_df.style.format(fmt_cols), use_container_width=True, hide_index=True)

        # Download
        csv_bytes = county_table.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download county GP table (CSV)",
            data=csv_bytes,
            file_name="county_gp_summary.csv",
            mime="text/csv",
        )

        # Optional chart (Top 15)
        st.markdown("#### Total GP by county (top 15)")
        chart_df = county_table.head(15).copy()
        chart_df["County"] = chart_df["County"].astype(str)

        bar = (
            alt.Chart(chart_df)
            .mark_bar()
            .encode(
                x=alt.X("Total GP:Q", title="Total GP"),
                y=alt.Y("County:N", sort="-x"),
                tooltip=["County", alt.Tooltip("Total GP:Q", format=",.0f"), "Sold Deals"],
            )
        )
        st.altair_chart(bar, use_container_width=True)

    st.divider()

    # Existing time charts
    time_bucket = st.selectbox("Time bucket", ["Quarter", "Month"], index=0)

    df_sold = df_sold.copy()
    df_sold["Date_dt"] = pd.to_datetime(df_sold.get("Date_dt"), errors="coerce")

    if time_bucket == "Month":
        df_sold["Period"] = df_sold["Date_dt"].dt.to_period("M").astype(str)
        period_label = "month"
    else:
        df_sold["Period"] = df_sold["Date_dt"].dt.to_period("Q").astype(str)
        period_label = "quarter"

    st.markdown(f"#### GP by {period_label}")
    gp_by_period = df_sold.groupby("Period")["Gross_Profit"].sum().sort_index()
    st.line_chart(gp_by_period)

    st.markdown(f"#### Sold deals by {period_label}")
    deals_by_period = df_sold.groupby("Period").size().sort_index()
    st.bar_chart(deals_by_period)

    pie_left, pie_right = st.columns(2)

    with pie_left:
        if "Dispo_Rep_clean" in df_sold.columns:
            st.markdown("#### GP by Dispo Rep (share of total, top 10)")

            gp_by_rep = (
                df_sold[df_sold["Dispo_Rep_clean"].astype(str).str.strip() != ""]
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
        if "Market_clean" in df_sold.columns:
            st.markdown("#### GP by Market (share of total)")

            gp_by_mkt = (
                df_sold[df_sold["Market_clean"].astype(str).str.strip() != ""]
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
