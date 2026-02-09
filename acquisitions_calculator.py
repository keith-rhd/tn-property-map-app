"""acquisitions_calculator.py

"Should We Contract This?" calculator for Acquisitions.

Goals:
- Keep the original UI/UX (two-column layout + “Why” bullets + cut-rate table).
- Fix small-sample counties by blending nearby counties (adjacency) when n is low.
- Ensure the recommendation is MONOTONIC with price (higher cannot become “safer”).

Decision (monotonic):
1) If price > SOLD ceiling -> RED (county ceiling if exists, else support ceiling)
2) Else if price >= 90% cut cliff (support-based) -> RED
3) Else if price >= 80% cut cliff (support-based) -> YELLOW
4) Else -> GREEN/YELLOW using support avg SOLD guardrail
"""

from __future__ import annotations

import math
from collections import deque

import pandas as pd
import streamlit as st


# -----------------------------
# Small-sample blending controls
# -----------------------------
MIN_SUPPORT_N = 15
MAX_HOPS = 2


# -----------------------------
# Formatting helpers
# -----------------------------
def _dollars(x) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    try:
        return f"${float(x):,.0f}"
    except Exception:
        return "—"


def _confidence_label(total_n: int) -> str:
    if total_n >= 30:
        return "✅ High"
    if total_n >= 15:
        return "⚠️ Medium"
    return "🚧 Low"


def _auto_params_for_county(total_n: int) -> tuple[int, int, int]:
    """(step, tail_min_n, min_bin_n) tuned by sample size."""
    if total_n >= 40:
        return (5000, 12, 6)
    if total_n >= 20:
        return (5000, 8, 5)
    if total_n >= 10:
        return (10000, 6, 4)
    return (20000, 5, 3)


# -----------------------------
# Binning + tail analytics
# -----------------------------
def _build_bins(df: pd.DataFrame, *, bin_size: int, min_bin_n: int) -> pd.DataFrame:
    """
    Returns dataframe with:
      bin_low, bin_high, n, cut_rate
    """
    d = df.copy()
    d["effective_price"] = pd.to_numeric(d["effective_price"], errors="coerce")
    d = d.dropna(subset=["effective_price", "is_cut"])
    if d.empty:
        return pd.DataFrame(columns=["bin_low", "bin_high", "n", "cut_rate"])

    d["bin_low"] = (d["effective_price"].astype(float) // float(bin_size)).astype(int) * int(bin_size)
    d["bin_high"] = d["bin_low"] + int(bin_size)

    rows = []
    for (lo, hi), g in d.groupby(["bin_low", "bin_high"]):
        n = int(len(g))
        if n < int(min_bin_n):
            continue
        cut_rate = float(g["is_cut"].mean()) if n else float("nan")
        rows.append({"bin_low": int(lo), "bin_high": int(hi), "n": n, "cut_rate": cut_rate})

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["bin_low", "bin_high", "n", "cut_rate"])
    return out.sort_values(["bin_low"])


def _find_tail_threshold(
    df: pd.DataFrame,
    target_cut_rate: float,
    *,
    tail_min_n: int,
    step: int,
) -> float | None:
    """Lowest price P (grid) where cut_rate(deals >= P) >= target_cut_rate."""
    d = df.copy()
    d["effective_price"] = pd.to_numeric(d["effective_price"], errors="coerce")
    d = d.dropna(subset=["effective_price", "is_cut"])
    if d.empty:
        return None

    prices = d["effective_price"].astype(float)
    pmin, pmax = float(prices.min()), float(prices.max())
    start = int((pmin // step) * step)
    end = int(((pmax + step - 1) // step) * step)

    for P in range(start, end + step, step):
        tail = d[d["effective_price"] >= float(P)]
        n = len(tail)
        if n < int(tail_min_n):
            continue
        cut_rate = float(tail["is_cut"].mean())
        if cut_rate >= float(target_cut_rate):
            return float(P)

    return None


def _tail_cut_rate_at_price(df: pd.DataFrame, price: float) -> tuple[float | None, int]:
    """Diagnostic only (not used for decision)."""
    d = df.copy()
    d["effective_price"] = pd.to_numeric(d["effective_price"], errors="coerce")
    d = d.dropna(subset=["effective_price", "is_cut"])
    if d.empty:
        return (None, 0)

    tail = d[d["effective_price"] >= float(price)]
    n = int(len(tail))
    if n == 0:
        return (None, 0)
    return (float(tail["is_cut"].mean()), n)


# -----------------------------
# Adjacency blending
# -----------------------------
def _neighbors_within_hops(
    county_key: str,
    adjacency: dict[str, list[str]],
    max_hops: int,
) -> list[str]:
    """BFS out to max_hops; returns unique counties excluding the start."""
    start = county_key.strip().upper()
    if not start or not adjacency:
        return []

    seen = {start}
    q: deque[tuple[str, int]] = deque([(start, 0)])
    out: list[str] = []

    while q:
        node, depth = q.popleft()
        if depth >= max_hops:
            continue
        for nxt in adjacency.get(node, []):
            nxt_u = str(nxt).strip().upper()
            if not nxt_u or nxt_u in seen:
                continue
            seen.add(nxt_u)
            out.append(nxt_u)
            q.append((nxt_u, depth + 1))

    return out


def _build_support_df(
    df_all: pd.DataFrame,
    county_key: str,
    *,
    adjacency: dict[str, list[str]] | None,
    min_support_n: int,
    max_hops: int,
) -> tuple[pd.DataFrame, str, list[str], bool]:
    """
    Returns:
      (df_support, scope_label, counties_used, used_fallback)
    """
    ck = county_key.strip().upper()
    d = df_all.copy()

    county_only = d[d["County_clean_up"].astype(str).str.strip().str.upper() == ck].copy()
    if len(county_only) >= int(min_support_n):
        return (county_only, "County only", [ck], False)

    adjacency = adjacency or {}

    for hops in range(1, int(max_hops) + 1):
        neigh = _neighbors_within_hops(ck, adjacency, max_hops=hops)
        pool = [ck] + neigh
        support = d[d["County_clean_up"].astype(str).str.strip().str.upper().isin(pool)].copy()
        if len(support) >= int(min_support_n):
            label = f"Blended nearby counties (≤{hops} hop{'s' if hops > 1 else ''})"
            return (support, label, pool, True)

    return (d, "Statewide fallback", ["ALL TN"], True)


# -----------------------------
# Main UI render
# -----------------------------
def render_contract_calculator(
    *,
    df_time_sold_for_view: pd.DataFrame,
    df_time_cut_for_view: pd.DataFrame,
) -> None:
    county_key = str(st.session_state.get("acq_selected_county", "")).strip().upper()
    if not county_key:
        st.info("Select a county in the left sidebar (MAO guidance) to use the calculator.")
        return

    # Keep the contract price sticky
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


    sold = df_time_sold_for_view.copy()
    cut = df_time_cut_for_view.copy()

    # Ensure County_clean_up exists (defensive)
    for d in (sold, cut):
        if "County_clean_up" not in d.columns and "County" in d.columns:
            d["County_clean_up"] = (
                d["County"].astype(str).str.upper().str.replace(r"\s+COUNTY\b", "", regex=True)
            )

    # Ensure Effective_Contract_Price exists
    if "Effective_Contract_Price" not in sold.columns:
        st.error("Missing Effective_Contract_Price in dataset. (Check data.normalize_inputs.)")
        return

    # We assume df_time_sold_for_view is sold-only and df_time_cut_for_view is cut-only.
    # If that ever changes upstream, swap this for Status_norm parsing.
    sold["status_norm"] = "sold"
    cut["status_norm"] = "cut loose"

    sold["effective_price"] = pd.to_numeric(sold["Effective_Contract_Price"], errors="coerce")
    cut["effective_price"] = pd.to_numeric(cut["Effective_Contract_Price"], errors="coerce")

    df_all = pd.concat([sold, cut], ignore_index=True).dropna(subset=["effective_price"])

    df_all["is_cut"] = (df_all["status_norm"] == "cut loose").astype(int)
    df_all["is_sold"] = (df_all["status_norm"] == "sold").astype(int)

    # County-only slice (for display)
    cdf = df_all[df_all["County_clean_up"].astype(str).str.strip().str.upper() == county_key].copy()
    total_n = int(len(cdf))
    sold_n = int(cdf["is_sold"].sum()) if total_n else 0
    cut_n = int(cdf["is_cut"].sum()) if total_n else 0

    # Build support df (for stability)
    adjacency = st.session_state.get("county_adjacency", None)
    support_df, support_label, support_counties, used_fallback = _build_support_df(
        df_all,
        county_key,
        adjacency=adjacency,
        min_support_n=MIN_SUPPORT_N,
        max_hops=MAX_HOPS,
    )

    support_n = int(len(support_df))
    support_sold_n = int(support_df["is_sold"].sum()) if support_n else 0
    support_cut_n = int(support_df["is_cut"].sum()) if support_n else 0

    conf = _confidence_label(support_n)
    step, tail_min_n, min_bin_n = _auto_params_for_county(support_n)

    # Averages (support avg always available if there are solds in support)
    support_avg_sold = (
        support_df.loc[support_df["is_sold"] == 1, "effective_price"].mean()
        if support_sold_n > 0
        else float("nan")
    )
    county_avg_sold = (
        cdf.loc[cdf["is_sold"] == 1, "effective_price"].mean()
        if sold_n > 0
        else float("nan")
    )

    # SOLD ceiling (prefer county, else support)
    county_max_sold = cdf.loc[cdf["is_sold"] == 1, "effective_price"].max()
    support_max_sold = support_df.loc[support_df["is_sold"] == 1, "effective_price"].max()

    if pd.notna(county_max_sold):
        ceiling_value = float(county_max_sold)
        ceiling_label = "County SOLD ceiling (max sold effective price)"
    elif pd.notna(support_max_sold):
        ceiling_value = float(support_max_sold)
        ceiling_label = "Support SOLD ceiling (max sold effective price)"
    else:
        ceiling_value = None
        ceiling_label = None

    # Cliff lines (support-based)
    line_80 = _find_tail_threshold(support_df, 0.80, tail_min_n=tail_min_n, step=step) if support_n else None
    line_90 = _find_tail_threshold(support_df, 0.90, tail_min_n=tail_min_n, step=step) if support_n else None

    # Diagnostic only
    tail_cut_at_input, tail_n_at_input = _tail_cut_rate_at_price(support_df, input_price)

    # Use bins from county when it has enough volume; otherwise from support
    bins_source_df = cdf if total_n >= MIN_SUPPORT_N else support_df
    bin_stats = _build_bins(bins_source_df, bin_size=step, min_bin_n=min_bin_n)

    # -----------------------------
    # MONOTONIC Recommendation
    # -----------------------------
    rec_reason_tag = ""

    # 1) SOLD ceiling hard rule (if we have one)
    if ceiling_value is not None and input_price > float(ceiling_value):
        rec = "🔴 RED — Above sold ceiling"
        rec_reason_tag = "county_sold_ceiling" if pd.notna(county_max_sold) else "support_sold_ceiling"

    # 2) 90% cliff hard red
    elif line_90 is not None and input_price >= float(line_90):
        rec = "🔴 RED — Likely Cut Loose"
        rec_reason_tag = "cliff_90"

    # 3) 80% cliff warning yellow
    elif line_80 is not None and input_price >= float(line_80):
        rec = "🟡 YELLOW — Caution / Needs justification"
        rec_reason_tag = "cliff_80"

    else:
        # 4) Guardrail using SUPPORT avg sold (works even when county has 0 sold)
        if not math.isnan(support_avg_sold) and input_price <= float(support_avg_sold) * 1.10:
            rec = "🟢 GREEN — Contractable"
            rec_reason_tag = "guardrail_green"
        else:
            rec = "🟡 YELLOW — Caution / Needs justification"
            rec_reason_tag = "guardrail_yellow"

    # -----------------------------
    # Explanation ("Why")
    # -----------------------------
    reason: list[str] = []

    if ceiling_value is not None:
        reason.append(f"{ceiling_label}: **{_dollars(ceiling_value)}**")
    else:
        reason.append("No SOLD ceiling available (no sold deals in the support dataset).")

    # Averages: avoid duplicate messaging when support == county
    if used_fallback:
        if not math.isnan(support_avg_sold):
            reason.append(f"Avg SOLD effective price (nearby data): **{_dollars(support_avg_sold)}**")
        if not math.isnan(county_avg_sold):
            reason.append(f"Avg SOLD effective price (this county): **{_dollars(county_avg_sold)}**")
    else:
        if not math.isnan(county_avg_sold):
            reason.append(f"Avg SOLD effective price: **{_dollars(county_avg_sold)}**")


    if tail_cut_at_input is None:
        reason.append(f"At {_dollars(input_price)} and above: —")
    else:
        out_of_10 = int(round(float(tail_cut_at_input) * 10))
        out_of_10 = max(0, min(10, out_of_10))
        reason.append(
            f"At {_dollars(input_price)} and above: about **{out_of_10} out of 10 deals** got cut loose (based on {tail_n_at_input} deals)."
        )

    if line_80 is not None:
        tail_80 = support_df[support_df["effective_price"] >= line_80]
        n80 = len(tail_80)
        reason.append(
            f"Around **{_dollars(line_80)}** and above: about **8 out of 10 deals** got cut loose (based on {n80} deals)."
        )
    
    if line_90 is not None:
        tail_90 = support_df[support_df["effective_price"] >= line_90]
        n90 = len(tail_90)
        reason.append(
            f"Around **{_dollars(line_90)}** and above: about **9 out of 10 deals** got cut loose (based on {n90} deals)."
        )


    # -----------------------------
    # UI (original style)
    # -----------------------------
    county_title = county_key.title()

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

        # Tight callout for Input Contract Price (color matches verdict)
        if rec_reason_tag in ("county_sold_ceiling", "support_sold_ceiling", "cliff_90"):
            _bg, _bd, _tx = "#3B2529", "#4A2D32", "#C96562"
        elif rec_reason_tag in ("cliff_80", "guardrail_yellow"):
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
                <span style="font-weight: 800;">{_dollars(input_price)}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Keep original “County sample” line, but confidence comes from SUPPORT
        st.write(f"**County sample:** {total_n} deals  |  **Sold:** {sold_n}  |  **Cut Loose:** {cut_n}")
        st.write(f"**Confidence:** {conf}")

        # Add model support line when blended/fallback so users understand the source
        if used_fallback:
            if support_label.startswith("Blended"):
                st.caption(f"Model support: {support_n} deals pulled from nearby counties.")
                neigh_list = [c for c in support_counties if c != county_key]
                if neigh_list:
                    st.caption("Blended counties: " + ", ".join([n.title() for n in neigh_list]))
            else:
                st.caption(f"Model support: {support_n} deals pulled from statewide history.")


        if conf == "🚧 Low":
            st.warning("Low data volume. Use as guidance only; confirm with buyer alignment.")

        st.markdown("**Why:**")
        for r in reason:
            st.write(f"- {r}")

        # Callout aligned with the new monotonic rules
        if rec_reason_tag in ("county_sold_ceiling", "support_sold_ceiling"):
            st.error("Above the **highest price we’ve ever successfully SOLD** (in the selected scope).")
        elif rec_reason_tag == "cliff_90":
            st.error("This is in the **90%+ tail failure zone** at this price and above.")
        elif rec_reason_tag == "cliff_80":
            st.warning("This is in the **80% tail failure zone** at this price and above.")
        else:
            st.success("This price is *not* in the high-failure zone based on your historical outcomes.")

    with right_col:
        st.subheader("Cut-Rate by Price Range")

        if bins_source_df is support_df and total_n < MIN_SUPPORT_N:
            st.caption(f"Showing **support-based** bins because county volume is low (n={total_n}).")

        if bin_stats.empty:
            st.info("Not enough data to build a context table for this selection.")
        else:
            show = bin_stats.copy()
            # Match your original table columns
            show["Price Range"] = show.apply(
                lambda r: f"{_dollars(r['bin_low'])}–{_dollars(r['bin_high'])}", axis=1
            )
            show["Cut Rate"] = (show["cut_rate"] * 100).round(0).astype(int).astype(str) + "%"
            show = show[["Price Range", "n", "Cut Rate"]].rename(columns={"n": "Deals in bin"})
            st.dataframe(show, use_container_width=True, hide_index=True)
