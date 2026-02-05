"""acquisitions_calculator.py

"Should We Contract This?" calculator for Acquisitions.

Design goals:
- Minimal inputs: county (driven by the Acquisitions sidebar selection) + proposed contract price
- Uses effective contract price from history:
    Effective_Contract_Price = Amended if present else Contract
- Uses tail cut-rate thresholds to detect high-end cliffs (Davidson-style)

Key behavior:
- Uses a dynamic global "RED ceiling" based on a rolling window max SOLD price
  (defaults to last 24 months) + a small cushion.
  This avoids hard-coded numbers like $500k that will age poorly with inflation.
"""

from __future__ import annotations

import math
from typing import Iterable

import pandas as pd
import streamlit as st


# Rolling-window settings for the global "outside sold range" rule
GLOBAL_SOLD_WINDOW_MONTHS = 24
GLOBAL_SOLD_CUSHION_MULT = 1.05  # 5% cushion to avoid borderline flips / single-point weirdness


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
    """(step, tail_min_n, min_bin_n) based on sample size."""
    if total_n >= 120:
        return (5000, 20, 5)
    if total_n >= 60:
        return (10000, 15, 4)
    if total_n >= 30:
        return (10000, 10, 3)
    if total_n >= 15:
        return (15000, 8, 3)
    return (20000, 6, 2)


def _build_bins(df_county: pd.DataFrame, bin_size: int, min_bin_n: int) -> pd.DataFrame:
    """Context table only (NOT used for decision thresholds)."""
    prices = pd.to_numeric(df_county["effective_price"], errors="coerce").dropna()
    if prices.empty:
        return pd.DataFrame(columns=["bin_low", "bin_high", "n", "cut_rate"])

    pmin, pmax = float(prices.min()), float(prices.max())
    start = int(math.floor(pmin / bin_size) * bin_size)
    end = int(math.ceil(pmax / bin_size) * bin_size)

    bins = list(range(start, end + bin_size, bin_size))
    if len(bins) < 3:
        bins = [start, end + bin_size]

    d = df_county.copy()
    d["effective_price"] = pd.to_numeric(d["effective_price"], errors="coerce")
    d = d.dropna(subset=["effective_price"])
    d["price_bin"] = pd.cut(d["effective_price"], bins=bins, right=True, include_lowest=True)

    grp = (
        d.groupby("price_bin", observed=False)
        .agg(n=("status_norm", "size"), cut_rate=("is_cut", "mean"))
        .reset_index()
    )

    grp["bin_low"] = grp["price_bin"].apply(lambda x: float(x.left) if pd.notna(x) else float("nan"))
    grp["bin_high"] = grp["price_bin"].apply(lambda x: float(x.right) if pd.notna(x) else float("nan"))

    grp["bin_low"] = pd.to_numeric(grp["bin_low"], errors="coerce")
    grp["bin_high"] = pd.to_numeric(grp["bin_high"], errors="coerce")
    grp["cut_rate"] = pd.to_numeric(grp["cut_rate"], errors="coerce")
    grp = grp.dropna(subset=["bin_low", "bin_high", "cut_rate"])

    grp = grp[grp["n"] >= min_bin_n].copy()
    grp = grp.sort_values(["bin_low"]).reset_index(drop=True)
    return grp[["bin_low", "bin_high", "n", "cut_rate"]]


def _find_tail_threshold(
    df_county: pd.DataFrame,
    target_cut_rate: float,
    tail_min_n: int,
    step: int,
) -> float | None:
    """Tail threshold: lowest P with cut_rate(deals >= P) >= target_cut_rate."""
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


def _first_existing_col(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    return None


def _infer_date_column(df: pd.DataFrame) -> str | None:
    """Try to find a usable date column for sold deals. Falls back to None."""
    candidates = [
        # common close/sold fields
        "Close_Date",
        "Close Date",
        "Closed_Date",
        "Closed Date",
        "Date_Closed",
        "Date Closed",
        "Sold_Date",
        "Sold Date",
        "Date_Sold",
        "Date Sold",
        "Disposition_Date",
        "Disposition Date",
        # sometimes people store a generic date
        "Date",
        "Deal_Date",
        "Deal Date",
        "Timestamp",
        "Created",
        "Created At",
    ]
    return _first_existing_col(df, candidates)


def _rolling_global_red_line_from_sold(
    sold_df: pd.DataFrame,
    *,
    window_months: int = GLOBAL_SOLD_WINDOW_MONTHS,
    cushion_mult: float = GLOBAL_SOLD_CUSHION_MULT,
) -> tuple[float | None, str]:
    """
    Returns (global_red_line, note).
    - Uses rolling window max SOLD price (last N months) * cushion
    - If no date col or no dates parse, fall back to all-time max SOLD * cushion
    """
    if sold_df is None or sold_df.empty or "effective_price" not in sold_df.columns:
        return None, "No sold data available."

    # choose date column
    date_col = _infer_date_column(sold_df)
    sold_prices = pd.to_numeric(sold_df["effective_price"], errors="coerce")
    sold_prices = sold_prices.dropna()
    if sold_prices.empty:
        return None, "No sold prices available."

    all_time_max = float(sold_prices.max()) * float(cushion_mult)

    if not date_col:
        return all_time_max, "No sold date column found; using all-time sold max + cushion."

    dt = pd.to_datetime(sold_df[date_col], errors="coerce")
    valid = dt.notna()
    if valid.sum() == 0:
        return all_time_max, "Sold date column present but unparseable; using all-time sold max + cushion."

    # Use the max sold date as the anchor (more stable than 'today' when viewing older years)
    max_date = pd.to_datetime(dt[valid].max())
    cutoff = max_date - pd.DateOffset(months=int(window_months))

    in_window = sold_df.loc[valid & (dt >= cutoff)].copy()
    in_window_prices = pd.to_numeric(in_window["effective_price"], errors="coerce").dropna()

    if in_window_prices.empty:
        # If window yields nothing (very old dataset slice), fall back
        return all_time_max, f"No sold deals in last {window_months} months of this view; using all-time sold max + cushion."

    rolling_max = float(in_window_prices.max()) * float(cushion_mult)
    return rolling_max, f"Using rolling sold max (last {window_months} months in this view) + {int((cushion_mult-1)*100)}% cushion."


def render_contract_calculator(
    *,
    df_time_sold_for_view: pd.DataFrame,
    df_time_cut_for_view: pd.DataFrame,
) -> None:
    """Main calculator UI."""

    # County selection is driven by the Acquisitions sidebar.
    county_key = str(st.session_state.get("acq_selected_county", "")).strip().upper()
    if not county_key:
        st.info("Select a county in the left sidebar (MAO guidance) to use the calculator.")
        return

    # Proposed contract price input (simple).
    price_col, _ = st.columns([0.3, 1.5])

    with price_col:
        input_price = float(
            st.number_input(
                "Proposed Contract Price ($)",
                min_value=0,
                value=int(st.session_state.get("acq_contract_price", 150000)),
                step=5000,
                key="acq_contract_price",
            )
        )

    # Build county dataset (sold + cut) with a single effective_price column.
    sold = df_time_sold_for_view.copy()
    cut = df_time_cut_for_view.copy()

    # Make sure the key columns exist (defensive).
    for d in (sold, cut):
        if "County_clean_up" not in d.columns and "County" in d.columns:
            d["County_clean_up"] = (
                d["County"].astype(str).str.upper().str.replace(r"\s+COUNTY\b", "", regex=True)
            )

    # Normalize status labels for this module.
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

    # Effective contract price is already computed by data.normalize_inputs.
    price_col_name = "Effective_Contract_Price" if "Effective_Contract_Price" in sold.columns else None
    if price_col_name is None:
        st.error("Missing Effective_Contract_Price in dataset. (Check data.normalize_inputs.)")
        return

    sold["effective_price"] = pd.to_numeric(sold[price_col_name], errors="coerce")
    cut["effective_price"] = pd.to_numeric(cut[price_col_name], errors="coerce")

    # Prepare unified frame
    df_all = pd.concat([sold, cut], ignore_index=True)
    df_all = df_all.dropna(subset=["effective_price"])

    df_all["is_cut"] = (df_all["status_norm"] == "cut loose").astype(int)
    df_all["is_sold"] = (df_all["status_norm"] == "sold").astype(int)

    # County slice
    cdf = df_all[df_all["County_clean_up"].astype(str).str.strip().str.upper() == county_key].copy()

    # County counts + auto params
    total_n = len(cdf)
    sold_n = int(cdf["is_sold"].sum()) if total_n else 0
    cut_n = int(cdf["is_cut"].sum()) if total_n else 0
    conf = _confidence_label(total_n)
    step, tail_min_n, min_bin_n = _auto_params_for_county(total_n)

    # Stats
    avg_sold = cdf.loc[cdf["is_sold"] == 1, "effective_price"].mean() if total_n else float("nan")

    # Thresholds (tail based)
    line_80 = _find_tail_threshold(cdf, 0.80, tail_min_n=tail_min_n, step=step) if total_n else None
    line_90 = _find_tail_threshold(cdf, 0.90, tail_min_n=tail_min_n, step=step) if total_n else None

    # Rolling global sold ceiling
    global_red_line, global_red_note = _rolling_global_red_line_from_sold(
        sold_df=sold.dropna(subset=["effective_price"]).copy(),
        window_months=GLOBAL_SOLD_WINDOW_MONTHS,
        cushion_mult=GLOBAL_SOLD_CUSHION_MULT,
    )

    # County ceiling (helps prevent "red -> yellow" at extreme prices)
    county_max = cdf["effective_price"].max() if total_n else float("nan")

    # Recommendation flags
    outside_global_sold_range = (global_red_line is not None and input_price > float(global_red_line))
    in_90_zone = (line_90 is not None and input_price >= float(line_90))
    in_80_zone = (line_80 is not None and input_price >= float(line_80))
    above_county_observed = (pd.notna(county_max) and input_price > float(county_max))

    # =========================
    # Recommendation (monotonic + rolling-global ceiling)
    # =========================
    if outside_global_sold_range:
        rec = "🔴 RED — Outside recent sold range"
    elif in_90_zone:
        rec = "🔴 RED — Likely Cut Loose"
    elif in_80_zone:
        if above_county_observed:
            rec = "🔴 RED — Above county historical range"
        else:
            rec = "🟡 YELLOW — Caution / Needs justification"
    else:
        if not math.isnan(avg_sold) and input_price <= avg_sold * 1.10:
            rec = "🟢 GREEN — Contractable"
        elif not math.isnan(avg_sold) and input_price >= avg_sold * 1.35:
            rec = "🔴 RED — Likely Cut Loose"
        else:
            rec = "🟡 YELLOW — Caution / Needs justification"

    # Build "Why" bullets
    reason: list[str] = []
    county_title = county_key.title()

    if not math.isnan(avg_sold):
        reason.append(f"Avg SOLD effective price: {_dollars(avg_sold)}")
    else:
        reason.append("Avg SOLD effective price: —")

    if global_red_line is not None:
        reason.append(f"Global recent SOLD ceiling: {_dollars(global_red_line)}")
        reason.append(f"Global ceiling logic: {global_red_note}")
    else:
        reason.append("Global recent SOLD ceiling: —")

    if pd.notna(county_max):
        reason.append(f"County max observed effective price: {_dollars(county_max)}")
    else:
        reason.append("County max observed effective price: —")

    if line_80 is not None:
        t80 = cdf[cdf["effective_price"] >= line_80]
        reason.append(
            f"~80% cut cliff around: {_dollars(line_80)} "
            f"(Deals ≥ line: {len(t80)}, cut rate: {(t80['is_cut'].mean()*100):.0f}%)"
        )

    if line_90 is not None:
        t90 = cdf[cdf["effective_price"] >= line_90]
        reason.append(
            f"~90% cut cliff around: {_dollars(line_90)} "
            f"(Deals ≥ line: {len(t90)}, cut rate: {(t90['is_cut'].mean()*100):.0f}%)"
        )

    # Build bins once (for the right-side context table)
    bin_stats = _build_bins(cdf, bin_size=step, min_bin_n=min_bin_n)

    # =========================
    # Layout: Decision (left) + Context table (right)
    # =========================
    left_col, right_col = st.columns([1.2, 1], gap="large")

    with left_col:
        st.subheader("✅ Should We Contract This?")
        st.caption("Uses your historical outcomes to flag pricing cliffs for the selected county.")

        # County header (same-line; big red county name)
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
        st.write(f"**Input contract price:** {_dollars(input_price)}")
        st.write(f"**County sample:** {total_n} deals  |  **Sold:** {sold_n}  |  **Cut Loose:** {cut_n}")
        st.write(f"**Confidence:** {conf}")

        if conf == "🚧 Low":
            st.warning(
                "Low data volume in this county. Use as guidance only; get buyer alignment to confirm pricing."
            )

        st.markdown("**Why:**")
        for r in reason:
            st.write(f"- {r}")

        # Bottom callout aligned with the new rules
        if outside_global_sold_range:
            st.error(
                "Outside the **recent SOLD range** (rolling window). Strongly avoid unless you have a "
                "pre-committed buyer at this price."
            )
        elif in_90_zone:
            st.error("This is in the **90%+ cut zone** for this county. Strongly avoid unless the deal is exceptional.")
        elif in_80_zone and above_county_observed:
            st.error("Above anything historically seen in this county **and** already in the high-failure zone.")
        elif in_80_zone:
            st.warning("This is in the **80% cut zone**. Only sign with clear justification.")
        else:
            st.success("This price is *not* in the high-failure zone based on your historical outcomes.")

    with right_col:
        st.subheader("Cut-Rate by Price Range")

        if bin_stats.empty:
            st.info("Not enough data to build a context table for this county.")
        else:
            show = bin_stats.copy()
            show["Price Range"] = show.apply(
                lambda r: f"{_dollars(r['bin_low'])}–{_dollars(r['bin_high'])}", axis=1
            )
            show["Cut Rate"] = (show["cut_rate"] * 100).round(0).astype(int).astype(str) + "%"
            show = show[["Price Range", "n", "Cut Rate"]].rename(columns={"n": "Deals in bin"})
            st.dataframe(show, use_container_width=True, hide_index=True)
