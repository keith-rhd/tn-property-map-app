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

#####################################################################################################################################################

def render_county_detail_panel(
    *,
    county_options_title: list[str],
    title_to_key: dict[str, str],
    selected_key: str | None,
    mao_tier_by_county: dict[str, str],
    mao_range_by_county: dict[str, str],
    sold_counts: dict[str, int],
    cut_counts: dict[str, int],
    buyer_active: bool,
    buyer_choice: str,
    buyer_sold_counts: dict[str, int],
    top_buyers_dict: dict,
    county_properties_view: dict,
):
    st.sidebar.markdown("## County details")

    # Dropdown (searchable)
    options = ["— Select a county —"] + county_options_title
    default_index = 0
    if selected_key:
        # try to map key back to title
        selected_title = None
        for t, k in title_to_key.items():
            if k == selected_key:
                selected_title = t
                break
        if selected_title and selected_title in county_options_title:
            default_index = 1 + county_options_title.index(selected_title)

    chosen_title = st.sidebar.selectbox("County", options, index=default_index)

    if chosen_title == "— Select a county —":
        st.sidebar.caption("Pick a county to see MAO guidance, performance stats, buyers, and addresses.")
        st.sidebar.markdown("---")
        return None

    c_key = title_to_key.get(chosen_title)
    if not c_key:
        st.sidebar.warning("Could not map county selection.")
        st.sidebar.markdown("---")
        return None

    # MAO info
    mao_tier = (mao_tier_by_county.get(c_key) or "").strip()
    mao_range = (mao_range_by_county.get(c_key) or "").strip()

    # Performance stats
    sold = int(sold_counts.get(c_key, 0) or 0)
    cut = int(cut_counts.get(c_key, 0) or 0)
    total = sold + cut
    close_rate = (sold / total) if total > 0 else 0.0
    close_rate_str = f"{close_rate:.0%}"

    st.sidebar.markdown(
        f"""
<div style="
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 10px;
    padding: 10px 12px;
">
  <div style="font-size:16px; font-weight:700; margin-bottom:6px;">{chosen_title}</div>

  <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
    <span>MAO Tier</span><span><b>{mao_tier if mao_tier else "—"}</b></span>
  </div>
  <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
    <span>MAO Range</span><span><b>{mao_range if mao_range else "—"}</b></span>
  </div>

  <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
    <span>Sold</span><span><b>{sold}</b></span>
  </div>
  <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
    <span>Cut loose</span><span><b>{cut}</b></span>
  </div>
  <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
    <span>Total</span><span><b>{total}</b></span>
  </div>
  <div style="display:flex; justify-content:space-between;">
    <span>Close rate</span><span><b>{close_rate_str}</b></span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Buyer-specific stat (only when buyer filter active)
    if buyer_active:
        bcount = int(buyer_sold_counts.get(c_key, 0) or 0)
        st.sidebar.caption(f"**{buyer_choice} (Sold in county):** {bcount}")

    # Top buyers (SOLD)
    top_buyers = top_buyers_dict.get(c_key) or []
    if top_buyers:
        st.sidebar.markdown("**Top buyers (Sold):**")
        # support either list[str] or list[tuple(name,count)]
        lines = []
        for item in top_buyers:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                lines.append(f"- {item[0]} ({item[1]})")
            else:
                lines.append(f"- {item}")
        st.sidebar.markdown("\n".join(lines))
    else:
        st.sidebar.caption("No top buyer data for this county (under current filters).")

    # Address list (current view)
    props = county_properties_view.get(c_key) or []
    if props:
        with st.sidebar.expander(f"Addresses in view ({len(props)})", expanded=False):
            # Keep it from getting huge
            max_show = 60
            shown = props[:max_show]

            # Scroll container
            html_lines = []
            for row in shown:
                addr = str(row.get("Address", "")).strip()
                url = str(row.get("Salesforce_URL", "")).strip()
                if url and addr:
                    html_lines.append(f"<div style='margin-bottom:6px;'><a href='{url}' target='_blank'>{addr}</a></div>")
                elif addr:
                    html_lines.append(f"<div style='margin-bottom:6px;'>{addr}</div>")

            more = len(props) - len(shown)
            if more > 0:
                html_lines.append(f"<div style='margin-top:8px; opacity:0.8;'>…and {more} more</div>")

            st.markdown(
                f"""
<div style="max-height:260px; overflow-y:auto; padding-right:6px;">
  {''.join(html_lines)}
</div>
""",
                unsafe_allow_html=True,
            )
    else:
        st.sidebar.caption("No addresses for this county in the current view.")

    st.sidebar.markdown("---")
    return c_key

