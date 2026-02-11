"""acquisitions_calculator.py

Streamlit UI for the Acquisitions "Should We Contract This?" calculator.

All business logic lives in `calculator_logic.compute_feasibility`.
All shared helpers (formatting, adjacency blending, bins) live in `calculator_support`.

Keeping UI and logic separate makes future tweaks much safer.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from calculator_logic import compute_feasibility
from calculator_support import dollars


def render_contract_calculator(
    *,
    df_time_sold_for_view: pd.DataFrame,
    df_time_cut_for_view: pd.DataFrame,
) -> None:
    county_key = str(st.session_state.get("acq_selected_county", "")).strip().upper()
    if not county_key:
        st.info("Select a county in the left sidebar (MAO guidance) to use the calculator.")
        return

    # Keep the contract price sticky + keep the input box tight
    st.session_state.setdefault("acq_contract_price", 150000)
    price_col, _ = st.columns([0.35, 1])
    with price_col:
        input_price = float(
            st.number_input(
                "Proposed Contract Price ($)",
                min_value=0,
                step=5000,
                key="acq_contract_price",
            )
        )

    adjacency = st.session_state.get("county_adjacency", None)

    try:
        result = compute_feasibility(
            county_key=county_key,
            input_price=input_price,
            df_time_sold_for_view=df_time_sold_for_view,
            df_time_cut_for_view=df_time_cut_for_view,
            adjacency=adjacency,
        )
    except KeyError as e:
        st.error(str(e))
        return

    # -----------------------------
    # UI (original style)
    # -----------------------------
    rec = result["rec"]
    county_title = result["county_title"]
    conf = result["confidence"]
    input_price = result["input_price"]

    county_counts = result["county_counts"]
    support = result["support"]
    reason = result["reason"]
    bins = result["bins"]

    left_col, right_col = st.columns([1.2, 1], gap="large")

    with left_col:
        st.subheader("✅ RHD Feasibility Calculator")
        st.caption("Uses your historical outcomes to flag pricing cliffs for the selected county.")

        # Big red county name (same line)
        st.markdown(
            f"""
            <div style="
                display: flex;
                align-items: baseline;
                gap: 10px;
                margin: 6px 0 12px 0;
            ">
                <span style="
                    font-size: 16px;
                    font-weight: 600;
                    opacity: 0.7;
                ">
                    County:
                </span>
                <span style="
                    font-size: 30px;
                    font-weight: 900;
                    color: #E53935;
                    line-height: 1;
                ">
                    {county_title}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(f"### {rec}")

        # Tight callout for Input Contract Price (always match the displayed recommendation)
        if rec.startswith("🔴"):
            _bg, _bd, _tx = "#3B2529", "#4A2D32", "#C96562"
        elif rec.startswith("🟡"):
            _bg, _bd, _tx = "#3A2F1E", "#54422A", "#D8B56A"
        else:
            _bg, _bd, _tx = "#233629", "#2F4A36", "#7BC29A"

        st.markdown(
            f"""
            <div style="
                display: inline-block;
                background: {_bg};
                border: 1px solid {_bd};
                color: {_tx};
                border-radius: 8px;
                padding: 6px 10px;
                margin: 6px 0 10px 0;
                font-size: 14px;
                line-height: 1.2;
                white-space: nowrap;
            ">
                <span style="font-weight: 600;">Input contract price:</span>
                <span style="font-weight: 800;">{dollars(input_price)}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.write(
            f"**County sample:** {county_counts['n']} deals  |  "
            f"**Sold:** {county_counts['sold']}  |  **Cut Loose:** {county_counts['cut']}"
        )
        st.write(f"**Confidence:** {conf}")

        # Friendly model support line (only when blended / statewide)
        if support["used"]:
            if support["label"] == "Nearby counties":
                st.caption(f"Model support: {support['n']} deals pulled from nearby counties.")
                neigh_list = [c for c in support["counties"] if c != result["county_key"]]
                if neigh_list:
                    st.caption("Blended counties: " + ", ".join([n.title() for n in neigh_list]))
            else:
                st.caption(f"Model support: {support['n']} deals pulled from statewide history.")

        if conf == "🚧 Low":
            st.warning("Low data volume. Use as guidance only; confirm with buyer alignment.")

        st.markdown("**Why:**")
        for r in reason:
            st.write(f"- {r}")

        # Callout aligned with the displayed recommendation
        if rec.startswith("🔴"):
            st.error("This price is in a **high-failure zone** based on your historical outcomes.")
        elif rec.startswith("🟡"):
            st.warning(
                "This price is **borderline** — not an automatic no, but it needs justification / buyer alignment."
            )
        else:
            st.success("This price is **not** in the high-failure zone based on your historical outcomes.")

    with right_col:
        st.subheader("Cut-Rate by Price Range")

        if bins["source"] == "support" and county_counts["n"] < 15:
            st.caption(f"Showing **support-based** bins because county volume is low (n={county_counts['n']}).")

        bin_stats = bins["df"]
        if bin_stats.empty:
            st.info("Not enough data to build a context table for this selection.")
        else:
            show = bin_stats.copy()
            show["Price Range"] = show.apply(
                lambda r: f"{dollars(r['bin_low'])}–{dollars(r['bin_high'])}", axis=1
            )
            show["Cut Rate"] = (show["cut_rate"] * 100).round(0).astype(int).astype(str) + "%"
            show = show[["Price Range", "n", "Cut Rate"]].rename(columns={"n": "Deals in bin"})
            st.dataframe(show, use_container_width=True, hide_index=True)
