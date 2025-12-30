import streamlit as st

from enrich import build_county_properties_view
from filters import compute_overall_stats


def render_selected_county_details(
    df_view,
    selected_county_key: str,
    df_sold,
    df_cut,
) -> None:
    """
    Below-map panel:
      - Selected county summary stats (sold/cut/total/close rate)
      - Properties table for that county (based on df_view filters)
    """
    st.markdown("### Selected county details")

    sel_key = str(selected_county_key or "").strip().upper()
    if not sel_key:
        st.info("Select a county from the sidebar or click one on the map.")
        return

    county_props = build_county_properties_view(df_view, sel_key)

    sold_scope = df_sold[df_sold["County_clean_up"] == sel_key]
    cut_scope = df_cut[df_cut["County_clean_up"] == sel_key]
    cstats = compute_overall_stats(sold_scope, cut_scope)

    sold_ct = int(cstats.get("sold_total", 0))
    cut_ct = int(cstats.get("cut_total", 0))
    total_ct = sold_ct + cut_ct
    close_rate = (sold_ct / total_ct) if total_ct else 0.0

    st.markdown(
        f"""
**County:** {sel_key.title()}  
**Sold:** {sold_ct}  
**Cut loose:** {cut_ct}  
**Total:** {total_ct}  
**Close rate:** {round(close_rate * 100, 1)}%  
"""
    )

    st.dataframe(county_props, use_container_width=True, hide_index=True)


# -------------------------------------------------------------------
# Phase B2 wrapper: pass ctx dict
# -------------------------------------------------------------------
def render_selected_county_details_ctx(ctx: dict) -> None:
    fd = ctx.get("fd")
    df_view = ctx.get("df_view")
    selected = str(ctx.get("selected", "")).strip().upper()

    if fd is None or df_view is None:
        st.info("Data is still loading…")
        return

    render_selected_county_details(
        df_view=df_view,
        selected_county_key=selected,
        df_sold=fd.df_time_sold,
        df_cut=fd.df_time_cut,
    )
