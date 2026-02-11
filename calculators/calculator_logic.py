"""calculator_logic.py

Business logic for the Acquisitions feasibility calculator.

All calculations live here. The Streamlit UI should call `compute_feasibility`
and render the returned result.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from calculator_support import (
    MIN_SUPPORT_N,
    MAX_HOPS,
    auto_params_for_n,
    build_bins,
    build_support_df,
    confidence_label,
    dollars,
    find_tail_threshold,
    tail_cut_rate_at_price,
)


def compute_feasibility(
    *,
    county_key: str,
    input_price: float,
    df_time_sold_for_view: pd.DataFrame,
    df_time_cut_for_view: pd.DataFrame,
    adjacency: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Compute calculator outputs. Returns a dict suitable for UI rendering."""
    county_key = str(county_key or "").strip().upper()
    input_price = float(input_price)

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
        raise KeyError("Missing Effective_Contract_Price in dataset. (Check data.normalize_inputs.)")

    # Upstream expects: sold df is sold-only; cut df is cut-only.
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

    # Support selection (for stability)
    support_df, support_label, support_counties, used_fallback = build_support_df(
        df_all,
        county_key,
        adjacency=adjacency,
        min_support_n=MIN_SUPPORT_N,
        max_hops=MAX_HOPS,
    )

    support_n = int(len(support_df))
    support_sold_n = int(support_df["is_sold"].sum()) if support_n else 0
    support_cut_n = int(support_df["is_cut"].sum()) if support_n else 0

    conf = confidence_label(support_n)
    step, tail_min_n, min_bin_n = auto_params_for_n(support_n)

    # Averages
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
    line_80 = find_tail_threshold(support_df, 0.80, tail_min_n=tail_min_n, step=step) if support_n else None
    line_90 = find_tail_threshold(support_df, 0.90, tail_min_n=tail_min_n, step=step) if support_n else None

    # Diagnostic tail-at-input
    tail_cut_at_input, tail_n_at_input = tail_cut_rate_at_price(support_df, input_price)

    # Bins: county if enough volume, else support
    bins_source_df = cdf if total_n >= MIN_SUPPORT_N else support_df
    bin_stats = build_bins(bins_source_df, bin_size=step, min_bin_n=min_bin_n)

    # -----------------------------
    # Recommendation (monotonic)
    # -----------------------------
    rec_reason_tag = ""

    if ceiling_value is not None and input_price > float(ceiling_value):
        rec = "🔴 RED — Above sold ceiling"
        rec_reason_tag = "county_sold_ceiling" if pd.notna(county_max_sold) else "support_sold_ceiling"

    # Hard-red override: if tail-at-input is 90%+ with sufficient sample
    elif tail_cut_at_input is not None and float(tail_cut_at_input) >= 0.90 and tail_n_at_input >= tail_min_n:
        rec = "🔴 RED — Likely Cut Loose"
        rec_reason_tag = "tail_90_at_input"

    elif line_90 is not None and input_price >= float(line_90):
        rec = "🔴 RED — Likely Cut Loose"
        rec_reason_tag = "cliff_90"

    elif line_80 is not None and input_price >= float(line_80):
        rec = "🟡 YELLOW — Caution / Needs justification"
        rec_reason_tag = "cliff_80"

    else:
        if not math.isnan(support_avg_sold) and input_price <= float(support_avg_sold) * 1.10:
            rec = "🟢 GREEN — Contractable"
            rec_reason_tag = "guardrail_green"
        else:
            rec = "🟡 YELLOW — Caution / Needs justification"
            rec_reason_tag = "guardrail_yellow"

    # -----------------------------
    # Explanation bullets (Why)
    # -----------------------------
    reason: list[str] = []

    if ceiling_value is not None:
        reason.append(f"{ceiling_label}: **{dollars(ceiling_value)}**")
    else:
        reason.append("No SOLD ceiling available (no sold deals in the support dataset).")

    # Averages: avoid duplicate messaging when support == county
    if used_fallback:
        if not math.isnan(support_avg_sold):
            reason.append(f"Avg SOLD effective price (nearby data): **{dollars(support_avg_sold)}**")
        if not math.isnan(county_avg_sold):
            reason.append(f"Avg SOLD effective price (this county): **{dollars(county_avg_sold)}**")
    else:
        if not math.isnan(county_avg_sold):
            reason.append(f"Avg SOLD effective price: **{dollars(county_avg_sold)}**")

    # Tail-at-input: use "X out of 10" phrasing
    if tail_cut_at_input is None:
        reason.append(f"At {dollars(input_price)} and above: —")
    else:
        out_of_10 = int(round(float(tail_cut_at_input) * 10))
        out_of_10 = max(0, min(10, out_of_10))
        reason.append(
            f"At {dollars(input_price)} and above: about **{out_of_10} out of 10 deals** got cut loose (based on {tail_n_at_input} deals)."
        )

    # Only show the 90% cliff line (per latest UX decision)
    if line_90 is not None:
        tail_90 = support_df[support_df["effective_price"] >= line_90]
        n90 = len(tail_90)
        reason.append(
            f"Around **{dollars(line_90)}** and above: about **9 out of 10 deals** got cut loose (based on {n90} deals)."
        )

    return {
        "county_key": county_key,
        "county_title": county_key.title(),
        "input_price": input_price,
        "rec": rec,
        "rec_reason_tag": rec_reason_tag,
        "confidence": conf,
        "county_counts": {"n": total_n, "sold": sold_n, "cut": cut_n},
        "support": {
            "used": used_fallback,
            "label": support_label,  # "County only" | "Nearby counties" | "Statewide"
            "n": support_n,
            "sold": support_sold_n,
            "cut": support_cut_n,
            "counties": support_counties,
        },
        "tail": {"rate": tail_cut_at_input, "n": tail_n_at_input, "tail_min_n": tail_min_n},
        "cliffs": {"p80": line_80, "p90": line_90},
        "averages": {"county_avg_sold": county_avg_sold, "support_avg_sold": support_avg_sold},
        "ceiling": {"value": ceiling_value, "label": ceiling_label},
        "bins": {
            "df": bin_stats,
            "source": "county" if bins_source_df is cdf else "support",
            "step": step,
            "min_bin_n": min_bin_n,
        },
        "reason": reason,
    }
