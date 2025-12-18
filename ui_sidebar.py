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
    st.sidebar.markdown("## County rankings")
    rank_metric = st.sidebar.selectbox("Rank by", ["Health score", "Buyer count"], index=0)
    top_n = st.sidebar.slider("Top N", 5, 50, 15, 5)

    st.sidebar.dataframe(
        rank_df.sort_values(rank_metric, ascending=False).head(top_n),
        use_container_width=True,
        hide_index=True,
    )
    return rank_metric, top_n
