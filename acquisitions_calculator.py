"""acquisitions_calculator.py

"Should We Contract This?" calculator for Acquisitions.

Design goals:
- Minimal inputs: county (driven by the Acquisitions sidebar selection) + proposed contract price
- Uses effective contract price from history:
    Effective_Contract_Price = Amended if present else Contract
- Uses tail cut-rate thresholds to detect high-end cliffs (Davidson-style)

Key corrections:
- County-specific SOLD ceiling: highest successfully SOLD effective price in that county.
  Anything above that is auto-RED for that county.
- Tail cut-rate at the input price is computed directly (no step artifacts),
  preventing "higher price becomes safer" glitches.

Small-sample upgrade (NEW):
- If the county has low history (n < MIN_SUPPORT_N), blend with adjacent counties
  (1-hop, then 2-hop). If still low, fall back to statewide.
- Always explain in the UI what support scope was used.
"""

from __future__ import annotations

import math
from collections import deque

import pandas as pd
import streamlit as st


# ===== Small-sample controls =====
MIN_SUPPORT_N = 15       # minimum deals needed to trust tail cut-rate + bins
MAX_HOPS = 2             # how far out to expand adjacency before statewide fallback


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


def _build_bins(df_county: pd.DataFrame, bin_size: int, min_bin_n: int) -> pd.DataFrame:
    """Build a price-binned table for context display."""
    d = df_county.copy()
    d["effective_price"] = pd.to_numeric(d["effective_price"], errors="coerce")
    d = d.dropna(subset=["effective_price", "is_cut", "is_sold"])
    if d.empty:
        return pd.DataFrame(columns=["Price Band", "n", "Sold", "Cut", "Cut Rate"])

    d["bin"] = (d["effective_price"].astype(float) // float(bin_size)).astype(int) * int(bin_size)

    rows = []
    for b, g in d.groupby("bin"):
        n = int(len(g))
        if n < int(min_bin_n):
            continue
        sold = int(g["is_sold"].sum())
        cut = int(g["is_cut"].sum())
        cut_rate = float(g["is_cut"].mean()) if n else float("nan")

        lo = int(b)
        hi = int(b + bin_size - 1)
        rows.append(
            {
                "Price Band": f"{_dollars(lo)}–{_dollars(hi)}",
                "n": n,
                "Sold": sold,
                "Cut": cut,
                "Cut Rate": f"{cut_rate:.0%}",
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["Price Band", "n", "Sold", "Cut", "Cut Rate"])
    return out.sort_values("Price Band")


def _find_tail_threshold(
    df_county: pd.DataFrame,
    target_cut_rate: float,
    tail_min_n: int,
    step: int,
) -> float | None:
    """Tail threshold: lowest P (grid) where cut_rate(deals >= P) >= target_cut_rate."""
    d = df_county.copy()
    d["effective_price"] = pd.to_numeric(d["effective_price"], errors="coerce")
    d = d.dropna(subset=["effective_price", "is_cut"])
    if d.empty:
        return None

    prices = d["effective_price"].astype(float)
    pmin, pmax = float(prices.min()), float(prices.max())

    start = int((pmin // step) * step)
    end = int(((pmax + step - 1) // step) * step)

    for P in range(start, end + step, step):
        tail = d[d["effective_price"] >= P]
        n = len(tail)
        if n < tail_min_n:
            continue
        cut_rate = float(tail["is_cut"].mean())
        if cut_rate >= target_cut_rate:
            return float(P)

    return None


def _tail_cut_rate_at_price(
    df_county: pd.DataFrame,
    price: float,
    tail_min_n: int,
) -> tuple[float | None, int]:
    """
    Returns (cut_rate, n) for deals with effective_price >= price.
    If n < tail_min_n, returns (None, n).
    """
    d = df_county.copy()
    d["effective_price"] = pd.to_numeric(d["effective_price"], errors="coerce")
    d = d.dropna(subset=["effective_price", "is_cut"])
    if d.empty:
        return (None, 0)

    tail = d[d["effective_price"] >= float(price)]
    n = int(len(tail))
    if n < int(tail_min_n):
        return (None, n)

    return (float(tail["is_cut"].mean()), n)


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

    Scope logic:
      - If county n >= min_support_n -> COUNTY ONLY
      - Else try 1-hop neighbors -> NEARBY (1-hop)
      - Else try 2-hop neighbors -> NEARBY (2-hop)
      - Else -> STATEWIDE
    """
    ck = county_key.strip().upper()
    d = df_all.copy()

    county_only = d[d["County_clean_up"].astype(str).str.strip().str.upper() == ck].copy()
    if len(county_only) >= min_support_n:
        return (county_only, "County only", [ck], False)

    adjacency = adjacency or {}

    # Expand 1-hop then 2-hop
    for hops in range(1, max_hops + 1):
        neigh = _neighbors_within_hops(ck, adjacency, max_hops=hops)
        pool = [ck] + neigh
        support = d[d["County_clean_up"].astype(str).str.strip().str.upper().isin(pool)].copy()
        if len(support) >= min_support_n:
            label = f"Blended nearby counties (≤{hops} hop{'s' if hops > 1 else ''})"
            return (support, label, pool, True)

    # Still low: statewide fallback
    return (d, "Statewide fallback", ["ALL TN"], True)


def render_contract_calculator(
    *,
    df_time_sold_for_view: pd.DataFrame,
    df_time_cut_for_view: pd.DataFrame,
) -> None:
    """Main calculator UI."""
    county_key = str(st.session_state.get("acq_selected_county", "")).strip().upper()
    if not county_key:
        st.info("Select a county in the left sidebar (MAO guidance) to use the calculator.")
        return

    price_col, _ = st.columns([0.3, 1.5])

    # Keep the contract price sticky across county changes
    st.session_state.setdefault("acq_contract_price", 150000)

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

    # Defensive county cleanup if needed
    for d in (sold, cut):
        if "County_clean_up" not in d.columns and "County" in d.columns:
            d["County_clean_up"] = (
                d["County"].astype(str).str.upper().str.replace(r"\s+COUNTY\b", "", regex=True)
            )

    # Normalize status labels for this module
    if "Status_norm" in sold.columns:
        sold_status = sold["Status_norm"].astype(str).str.lower()
    else:
        sold_status = pd.Series(["sold"] * len(sold), index=sold.index)

    if "Status_norm" in cut.columns:
        cut_status = cut["Status_norm"].astype(str).str.lower()
    else:
        cut_status = pd.Series(["cut loose"] * len(cut), index=cut.index)

    sold["status_norm"] = sold_status.replace({"cut": "cut loose"})
    cut["status_norm"] = cut_status.replace({"cut": "cut loose"})

    # Effective price
    price_col_name = "Effective_Contract_Price" if "Effective_Contract_Price" in sold.columns else None
    if price_col_name is None:
        st.error("Missing Effective_Contract_Price in dataset. (Check data.normalize_inputs.)")
        return

    sold["effective_price"] = pd.to_numeric(sold[price_col_name], errors="coerce")
    cut["effective_price"] = pd.to_numeric(cut[price_col_name], errors="coerce")

    df_all = pd.concat([sold, cut], ignore_index=True)
    df_all = df_all.dropna(subset=["effective_price"])

    df_all["is_cut"] = (df_all["status_norm"] == "cut loose").astype(int)
    df_all["is_sold"] = (df_all["status_norm"] == "sold").astype(int)

    # County-only slice (always compute + show)
    cdf = df_all[df_all["County_clean_up"].astype(str).str.strip().str.upper() == county_key].copy()
    total_n = int(len(cdf))
    sold_n = int(cdf["is_sold"].sum()) if total_n else 0
    cut_n = int(cdf["is_cut"].sum()) if total_n else 0

    # Support data selection (for low-sample stability)
    adjacency = st.session_state.get("county_adjacency", None)
    support_df, support_label, support_counties, used_fallback = _build_support_df(
        df_all,
        county_key,
        adjacency=adjacency,
        min_support_n=MIN_SUPPORT_N,
        max_hops=MAX_HOPS,
    )

    support_n = int(len(support_df))
    conf = _confidence_label(support_n)

    step, tail_min_n, min_bin_n = _auto_params_for_county(support_n)

    # County-only avg sold
    avg_sold_county = (
        cdf.loc[cdf["is_sold"] == 1, "effective_price"].mean() if total_n else float("nan")
    )

    # SOLD ceiling:
    # Prefer county ceiling if it exists; otherwise use support ceiling but clearly label it.
    county_max_sold = cdf.loc[cdf["is_sold"] == 1, "effective_price"].max()
    has_county_sold_ceiling = pd.notna(county_max_sold)

    support_max_sold = support_df.loc[support_df["is_sold"] == 1, "effective_price"].max()
    has_support_sold_ceiling = pd.notna(support_max_sold)

    ceiling_value = None
    ceiling_label = None

    if has_county_sold_ceiling:
        ceiling_value = float(county_max_sold)
        ceiling_label = "County sold ceiling"
    elif has_support_sold_ceiling:
        ceiling_value = float(support_max_sold)
        ceiling_label = f"Support sold ceiling ({support_label.lower()})"

    # Tail cut rates (computed on support_df for stability)
    tail_cut_at_input, tail_n_at_input = _tail_cut_rate_at_price(
        support_df, input_price, tail_min_n=tail_min_n
    )

    # Cliff lines for explanation (grid-based, support_df)
    line_80 = _find_tail_threshold(support_df, 0.80, tail_min_n=tail_min_n, step=step) if support_n else None
    line_90 = _find_tail_threshold(support_df, 0.90, tail_min_n=tail_min_n, step=step) if support_n else None

    # Context bins (support_df)
    bin_stats = _build_bins(support_df, bin_size=step, min_bin_n=min_bin_n)

    # =========================
    # Recommendation
    # =========================
    rec_reason_tag = ""

    # 1) Sold ceiling rule (hard)
    if ceiling_value is not None and input_price > float(ceiling_value):
        rec = f"🔴 RED — Above sold ceiling ({ceiling_label})"
        rec_reason_tag = "sold_ceiling"

    # 2) Tail-at-input rule (hard red at 90%)
    elif tail_cut_at_input is not None and tail_cut_at_input >= 0.90:
        rec = "🔴 RED — Likely Cut Loose"
        rec_reason_tag = "tail_input_90"

    # 3) Tail-at-input rule (yellow at 80%)
    elif tail_cut_at_input is not None and tail_cut_at_input >= 0.80:
        rec = "🟡 YELLOW — Caution / Needs justification"
        rec_reason_tag = "tail_input_80"

    else:
        # fallback when tails are unreliable or low n
        if not math.isnan(avg_sold_county) and input_price <= avg_sold_county * 1.10:
            rec = "🟢 GREEN — Contractable"
            rec_reason_tag = "fallback_green"
        elif not math.isnan(avg_sold_county) and input_price >= avg_sold_county * 1.35:
            rec = "🔴 RED — Likely Cut Loose"
            rec_reason_tag = "fallback_red"
        else:
            rec = "🟡 YELLOW — Caution / Needs justification"
            rec_reason_tag = "fallback_yellow"

    # =========================
    # UI
    # =========================
    county_title = county_key.title()

    st.markdown(f"### {county_title} — Feasibility")
    st.markdown(f"**Recommendation:** {rec}")
    st.markdown(
        f"**Confidence:** {conf}  \n"
        f"County history: **n={total_n}** (Sold {sold_n} / Cut {cut_n})  \n"
        f"Model support: **n={support_n}** — {support_label}"
    )

    if used_fallback:
        # Don’t spam statewide list; show neighbors only
        if support_label.startswith("Blended"):
            neigh_list = [c for c in support_counties if c != county_key]
            if neigh_list:
                st.caption("Blended counties: " + ", ".join([n.title() for n in neigh_list]))
        else:
            st.caption("Using statewide data because the county has too few historical deals under current filters.")

    st.divider()

    # Explanation bullets
    reason: list[str] = []

    if ceiling_value is not None:
        reason.append(f"Sold ceiling used: **{_dollars(ceiling_value)}** ({ceiling_label}).")
    else:
        reason.append("No sold ceiling available (no sold deals found in the support dataset).")

    if tail_cut_at_input is None:
        reason.append(f"Tail cut-rate at {_dollars(input_price)} is unavailable (tail sample too small: n={tail_n_at_input}).")
    else:
        reason.append(f"Tail cut-rate at {_dollars(input_price)}: **{tail_cut_at_input:.0%}** (n={tail_n_at_input}).")

    if line_80 is not None:
        reason.append(f"80% cut cliff starts around **{_dollars(line_80)}** (support-based).")
    if line_90 is not None:
        reason.append(f"90% cut cliff starts around **{_dollars(line_90)}** (support-based).")

    if not math.isnan(avg_sold_county):
        reason.append(f"County avg SOLD effective price: **{_dollars(avg_sold_county)}**.")

    for r in reason:
        st.write("• " + r)

    st.divider()

    st.markdown("#### Historical context (price bands)")
    if bin_stats.empty:
        st.info("Not enough historical deals to build stable price bands under current filters.")
    else:
        st.dataframe(bin_stats, use_container_width=True)
