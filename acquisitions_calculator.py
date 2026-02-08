"""acquisitions_calculator.py

Acquisitions feasibility calculator ("Should we contract this?").

Key behavior:
- Uses Effective_Contract_Price (Amended if present else Contract) as the price axis.
- For low-volume counties, blends nearby counties using adjacency (1-hop then 2-hop),
  then falls back to statewide if still too small.
- Decision is MONOTONIC with price: higher price cannot become "safer".

Monotonic decision rule:
1) If price > sold ceiling -> RED (if we have a ceiling)
2) Else if price >= 90% cut cliff (line_90) -> RED
3) Else if price >= 80% cut cliff (line_80) -> YELLOW
4) Else -> GREEN/YELLOW based on support sold average guardrails
"""

from __future__ import annotations

import math
from collections import deque

import pandas as pd
import streamlit as st


MIN_SUPPORT_N = 15
MAX_HOPS = 2


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


def _auto_params_for_county(total_n: int) -> tuple[int, int]:
    """(step, tail_min_n) tuned by sample size."""
    if total_n >= 40:
        return (5000, 12)
    if total_n >= 20:
        return (5000, 8)
    if total_n >= 10:
        return (10000, 6)
    return (20000, 5)


def _find_tail_threshold(
    df_support: pd.DataFrame,
    target_cut_rate: float,
    tail_min_n: int,
    step: int,
) -> float | None:
    """Lowest price P (grid) where cut_rate(deals >= P) >= target_cut_rate."""
    d = df_support.copy()
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
    df_support: pd.DataFrame,
    price: float,
) -> tuple[float | None, int]:
    """Diagnostic only (NOT used for decision)."""
    d = df_support.copy()
    d["effective_price"] = pd.to_numeric(d["effective_price"], errors="coerce")
    d = d.dropna(subset=["effective_price", "is_cut"])
    if d.empty:
        return (None, 0)

    tail = d[d["effective_price"] >= float(price)]
    n = int(len(tail))
    if n == 0:
        return (None, 0)
    return (float(tail["is_cut"].mean()), n)


def _neighbors_within_hops(
    county_key: str,
    adjacency: dict[str, list[str]],
    max_hops: int,
) -> list[str]:
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
    ck = county_key.strip().upper()
    d = df_all.copy()

    county_only = d[d["County_clean_up"].astype(str).str.strip().str.upper() == ck].copy()
    if len(county_only) >= min_support_n:
        return (county_only, "County only", [ck], False)

    adjacency = adjacency or {}

    for hops in range(1, max_hops + 1):
        neigh = _neighbors_within_hops(ck, adjacency, max_hops=hops)
        pool = [ck] + neigh
        support = d[d["County_clean_up"].astype(str).str.strip().str.upper().isin(pool)].copy()
        if len(support) >= min_support_n:
            label = f"Blended nearby counties (≤{hops} hop{'s' if hops > 1 else ''})"
            return (support, label, pool, True)

    return (d, "Statewide fallback", ["ALL TN"], True)


def render_contract_calculator(
    *,
    df_time_sold_for_view: pd.DataFrame,
    df_time_cut_for_view: pd.DataFrame,
) -> None:
    county_key = str(st.session_state.get("acq_selected_county", "")).strip().upper()
    if not county_key:
        st.info("Select a county in the left sidebar to use the calculator.")
        return

    st.session_state.setdefault("acq_contract_price", 150000)
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

    # Ensure County_clean_up exists
    for d in (sold, cut):
        if "County_clean_up" not in d.columns and "County" in d.columns:
            d["County_clean_up"] = (
                d["County"].astype(str).str.upper().str.replace(r"\s+COUNTY\b", "", regex=True)
            )

    if "Effective_Contract_Price" not in sold.columns:
        st.error("Missing Effective_Contract_Price in dataset. (Check data.normalize_inputs.)")
        return

    sold["status_norm"] = "sold"
    cut["status_norm"] = "cut loose"

    sold["effective_price"] = pd.to_numeric(sold["Effective_Contract_Price"], errors="coerce")
    cut["effective_price"] = pd.to_numeric(cut["Effective_Contract_Price"], errors="coerce")

    df_all = pd.concat([sold, cut], ignore_index=True).dropna(subset=["effective_price"])

    df_all["is_cut"] = (df_all["status_norm"] == "cut loose").astype(int)
    df_all["is_sold"] = (df_all["status_norm"] == "sold").astype(int)

    # County-only stats
    cdf = df_all[df_all["County_clean_up"].astype(str).str.strip().str.upper() == county_key].copy()
    county_n = int(len(cdf))
    county_sold_n = int(cdf["is_sold"].sum()) if county_n else 0
    county_cut_n = int(cdf["is_cut"].sum()) if county_n else 0

    # Support selection
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

    step, tail_min_n = _auto_params_for_county(support_n)

    # Averages (show support avg sold; show county avg sold if exists)
    county_avg_sold = (
        cdf.loc[cdf["is_sold"] == 1, "effective_price"].mean()
        if county_sold_n > 0
        else float("nan")
    )
    support_avg_sold = (
        support_df.loc[support_df["is_sold"] == 1, "effective_price"].mean()
        if support_sold_n > 0
        else float("nan")
    )

    # Sold ceiling (prefer county; otherwise support)
    county_max_sold = cdf.loc[cdf["is_sold"] == 1, "effective_price"].max()
    support_max_sold = support_df.loc[support_df["is_sold"] == 1, "effective_price"].max()

    if pd.notna(county_max_sold):
        ceiling_value = float(county_max_sold)
        ceiling_label = "County sold ceiling"
    elif pd.notna(support_max_sold):
        ceiling_value = float(support_max_sold)
        ceiling_label = f"Support sold ceiling ({support_label.lower()})"
    else:
        ceiling_value = None
        ceiling_label = None

    # Cliff thresholds (monotonic decision anchors)
    line_80 = _find_tail_threshold(support_df, 0.80, tail_min_n=tail_min_n, step=step)
    line_90 = _find_tail_threshold(support_df, 0.90, tail_min_n=tail_min_n, step=step)

    # Diagnostic (display only)
    tail_cut_at_input, tail_n_at_input = _tail_cut_rate_at_price(support_df, input_price)

    # =========================
    # MONOTONIC Recommendation
    # =========================
    if ceiling_value is not None and input_price > ceiling_value:
        rec = f"🔴 RED — Above sold ceiling ({ceiling_label})"
    elif line_90 is not None and input_price >= line_90:
        rec = f"🔴 RED — Past 90% cut cliff (~{_dollars(line_90)})"
    elif line_80 is not None and input_price >= line_80:
        rec = f"🟡 YELLOW — Past 80% cut cliff (~{_dollars(line_80)})"
    else:
        # guardrail using SUPPORT avg sold (works even when county has 0 sold)
        if not math.isnan(support_avg_sold) and input_price <= support_avg_sold * 1.10:
            rec = "🟢 GREEN — Contractable"
        else:
            rec = "🟡 YELLOW — Caution / Needs justification"

    # =========================
    # Simple UI (restored)
    # =========================
    st.markdown(f"### {county_key.title()} — Feasibility")
    st.markdown(f"**Recommendation:** {rec}")

    # Compact “what data did we use” block
    st.markdown(
        f"**Confidence:** {conf}  \n"
        f"County history: **n={county_n}** (Sold {county_sold_n} / Cut {county_cut_n})  \n"
        f"Model support: **n={support_n}** — {support_label} (Sold {support_sold_n} / Cut {support_cut_n})"
    )

    if used_fallback and support_label.startswith("Blended"):
        neigh_list = [c for c in support_counties if c != county_key]
        if neigh_list:
            st.caption("Blended counties: " + ", ".join([n.title() for n in neigh_list]))

    st.divider()

    # Key numbers (simple)
    cols = st.columns(3)
    cols[0].metric("Support Avg SOLD", _dollars(support_avg_sold) if not math.isnan(support_avg_sold) else "—")
    cols[1].metric("Sold Ceiling", _dollars(ceiling_value) if ceiling_value is not None else "—")
    if tail_cut_at_input is None:
        cols[2].metric("Tail Cut-Rate @ Price", "—")
    else:
        cols[2].metric("Tail Cut-Rate @ Price", f"{tail_cut_at_input:.0%} (n={tail_n_at_input})")

    # Cliff lines (if available)
    line_cols = st.columns(2)
    line_cols[0].metric("80% Cut Cliff", _dollars(line_80) if line_80 is not None else "—")
    line_cols[1].metric("90% Cut Cliff", _dollars(line_90) if line_90 is not None else "—")
