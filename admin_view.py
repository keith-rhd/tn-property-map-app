# admin_view.py
import os
import pandas as pd
import streamlit as st
import altair as alt


# -----------------------------
# Admin auth
# -----------------------------
def _get_sales_manager_password() -> str | None:
    # Prefer Streamlit Secrets (Streamlit Cloud)
    try:
        pw = st.secrets.get("sales_manager_password", None)
        if pw:
            return str(pw)
    except Exception:
        pass

    # Fallback to env var
    pw = os.environ.get("SALES_MANAGER_PASSWORD")
    return str(pw) if pw else None


def require_sales_manager_auth():
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


# -----------------------------
# Admin dashboard
# -----------------------------
def _safe_sum(series) -> float:
    try:
        return float(pd.to_numeric(series, errors="coerce").fillna(0).sum())
    except Exception:
        return 0.0


def render_sales_manager_dashboard(df_sold: pd.DataFrame):
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
