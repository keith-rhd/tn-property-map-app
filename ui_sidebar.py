# ui_sidebar.py
import pandas as pd
import streamlit as st


def render_overall_stats(*, year_choice, sold_total, cut_total, total_deals, total_buyers, close_rate_str):
    st.sidebar.markdown("## Overall stats")
    st.sidebar.caption(f"Year: **{year_choice}**")

    st.sidebar.markdown(
        f"""
<div style="
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 10px;
    padding: 10px 12px;
">
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Sold</span><span><b>{sold_total}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Cut loose</span><span><b>{cut_total}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Total deals</span><span><b>{total_deals}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Total buyers</span><span><b>{total_buyers}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between;">
        <span>Close rate</span><span><b>{close_rate_str}</b></span>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.sidebar.markdown("---")


def render_rankings(rank_df: pd.DataFrame):
    """
    Expects rank_df to include:
      - County
      - Health score
      - Buyer count
      - Trend (arrow string)
    Optional helper column:
      - _trend_delta (int), used to sort Trend correctly
    """
    st.sidebar.markdown("## County rankings")

    rank_metric = st.sidebar.selectbox(
        "Rank by",
        ["Health score", "Buyer count", "Trend"],
        index=0,
    )
    top_n = st.sidebar.slider("Top N", 5, 50, 15, 5)

    df = rank_df.copy()

    if df.empty:
        st.sidebar.info("No ranking data available.")
        return rank_metric, top_n

    # Sort correctly
    if rank_metric == "Trend":
        if "_trend_delta" in df.columns:
            df = df.sort_values("_trend_delta", ascending=False)
        else:
            # Fallback if helper column is missing
            df = df.sort_values("Trend", ascending=False)
    else:
        df = df.sort_values(rank_metric, ascending=False)

    # Hide helper column from display
    df = df.drop(columns=["_trend_delta"], errors="ignore")

    st.sidebar.dataframe(
        df.head(top_n),
        use_container_width=True,
        hide_index=True,
    )

    return rank_metric, top_n
