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
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st


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
    # Keep the contract price sticky across county changes:
    # - set a default once
    # - let the widget (key=...) manage the value after that
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

    cdf = df_all[df_all["County_clean_up"].astype(str).str.strip().str.upper() == county_key].copy()

    total_n = len(cdf)
    sold_n = int(cdf["is_sold"].sum()) if total_n else 0
    cut_n = int(cdf["is_cut"].sum()) if total_n else 0
    conf = _confidence_label(total_n)

    step, tail_min_n, min_bin_n = _auto_params_for_county(total_n)

    avg_sold = cdf.loc[cdf["is_sold"] == 1, "effective_price"].mean() if total_n else float("nan")

    # County SOLD ceiling (THIS is the rule you want)
    county_max_sold = cdf.loc[cdf["is_sold"] == 1, "effective_price"].max()
    has_county_sold_ceiling = pd.notna(county_max_sold)

    # Tail cut rates
    tail_cut_at_input, tail_n_at_input = _tail_cut_rate_at_price(cdf, input_price, tail_min_n=tail_min_n)

    # Cliff lines for explanation (grid-based, but only explanatory)
    line_80 = _find_tail_threshold(cdf, 0.80, tail_min_n=tail_min_n, step=step) if total_n else None
    line_90 = _find_tail_threshold(cdf, 0.90, tail_min_n=tail_min_n, step=step) if total_n else None

    # Context table
    bin_stats = _build_bins(cdf, bin_size=step, min_bin_n=min_bin_n)

    # =========================
    # Recommendation (county SOLD ceiling + monotonic tail at input)
    # =========================
    rec_reason_tag = ""

    # 1) County SOLD ceiling rule (hard)
    if has_county_sold_ceiling and input_price > float(county_max_sold):
        rec = "🔴 RED — Above county sold ceiling"
        rec_reason_tag = "county_sold_ceiling"

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
        if not math.isnan(avg_sold) and input_price <= avg_sold * 1.10:
            rec = "🟢 GREEN — Contractable"
            rec_reason_tag = "fallback_green"
        elif not math.isnan(avg_sold) and input_price >= avg_sold * 1.35:
            rec = "🔴 RED — Likely Cut Loose"
            rec_reason_tag = "fallback_red"
        else:
            rec = "🟡 YELLOW — Caution / Needs justification"
            rec_reason_tag = "fallback_yellow"

    # =========================
    # Why bullets
    # =========================
    county_title = county_key.title()
    reason: list[str] = []
    
    if has_county_sold_ceiling:
        reason.append(
            f"County SOLD ceiling (max sold effective price): {_dollars(county_max_sold)}"
        )
    else:
        reason.append(
            "County SOLD ceiling: — (no sold deals in this county)"
        )
    
    if not math.isnan(avg_sold):
        reason.append(
            f"Avg SOLD effective price: {_dollars(avg_sold)}"
        )
    else:
        reason.append(
            "Avg SOLD effective price: —"
        )
    
    if tail_cut_at_input is not None:
        reason.append(
            f"At {_dollars(input_price)} and above: "
            f"about {int(round(tail_cut_at_input * 10))} out of 10 deals got cut loose "
            f"(based on {tail_n_at_input} deals)"
        )
    else:
        reason.append(
            f"At {_dollars(input_price)} and above: — "
            f"(based on {tail_n_at_input} deals)"
        )
    
    if line_80 is not None:
        t80 = cdf[cdf["effective_price"] >= line_80]
        reason.append(
            f"Around {_dollars(line_80)} and above: "
            f"about 8 out of 10 deals got cut loose "
            f"(based on {len(t80)} deals)"
        )
    
    if line_90 is not None:
        t90 = cdf[cdf["effective_price"] >= line_90]
        reason.append(
            f"Around {_dollars(line_90)} and above: "
            f"about 9 out of 10 deals got cut loose "
            f"(based on {len(t90)} deals)"
        )


    # =========================
    # Layout
    # =========================
    left_col, right_col = st.columns([1.2, 1], gap="large")

    with left_col:
        st.subheader("✅ Should We Contract This?")
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
        st.write(f"**Input contract price:** {_dollars(input_price)}")
        st.write(f"**County sample:** {total_n} deals  |  **Sold:** {sold_n}  |  **Cut Loose:** {cut_n}")
        st.write(f"**Confidence:** {conf}")

        if conf == "🚧 Low":
            st.warning("Low data volume in this county. Use as guidance only; get buyer alignment to confirm pricing.")

        st.markdown("**Why:**")
        for r in reason:
            st.write(f"- {r}")

        # Callout aligned with the new rules
        if rec_reason_tag == "county_sold_ceiling":
            st.error("Above the **highest price we’ve ever successfully SOLD** in this county.")
        elif rec_reason_tag == "tail_input_90":
            st.error("This is in the **90%+ tail failure zone** at this price and above.")
        elif rec_reason_tag == "tail_input_80":
            st.warning("This is in the **80% tail failure zone** at this price and above.")
        else:
            st.success("This price is *not* in the high-failure zone based on your historical outcomes.")

    with right_col:
        st.subheader("Cut-Rate by Price Range")
        if bin_stats.empty:
            st.info("Not enough data to build a context table for this county.")
        else:
            show = bin_stats.copy()
            show["Price Range"] = show.apply(lambda r: f"{_dollars(r['bin_low'])}–{_dollars(r['bin_high'])}", axis=1)
            show["Cut Rate"] = (show["cut_rate"] * 100).round(0).astype(int).astype(str) + "%"
            show = show[["Price Range", "n", "Cut Rate"]].rename(columns={"n": "Deals in bin"})
            st.dataframe(show, use_container_width=True, hide_index=True)
