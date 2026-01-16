"""controller_services.py

Pure helpers used by app_controller. Keep this file free of Streamlit UI code
as much as possible (logic + data transformations).
"""

from __future__ import annotations

import pandas as pd


def county_options(
    df: pd.DataFrame, tiers: pd.DataFrame | None
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Return:
    - all_county_options (list[str])
    - mao_tier_by_county (dict)
    - mao_range_by_county (dict)
    """

    mao_tier_by_county: dict[str, str] = {}
    mao_range_by_county: dict[str, str] = {}

    tier_counties: list[str] = []
    if tiers is not None and not tiers.empty:
        mao_tier_by_county = dict(zip(tiers["County_clean_up"], tiers["MAO_Tier"]))
        mao_range_by_county = dict(zip(tiers["County_clean_up"], tiers["MAO_Range_Str"]))
        tier_counties = sorted(tiers["County_clean_up"].dropna().unique().tolist())

    deal_counties = sorted(df.get("County_clean_up", pd.Series(dtype=str)).dropna().unique().tolist())

    # Prefer tier sheet counties if present (covers all TN counties)
    all_county_options = tier_counties if tier_counties else deal_counties

    return all_county_options, mao_tier_by_county, mao_range_by_county


def apply_admin_filters(
    df_sold: pd.DataFrame,
    df_cut: pd.DataFrame,
    *,
    market_choice: str,
    acq_rep_choice: str,
    dispo_rep_choice_admin: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply Admin-only filters to sold/cut frames."""
    df_sold_f = df_sold
    df_cut_f = df_cut

    if dispo_rep_choice_admin != "All reps" and "Dispo_Rep_clean" in df_sold_f.columns:
        df_sold_f = df_sold_f[df_sold_f["Dispo_Rep_clean"] == dispo_rep_choice_admin]
        if "Dispo_Rep_clean" in df_cut_f.columns:
            df_cut_f = df_cut_f[df_cut_f["Dispo_Rep_clean"] == dispo_rep_choice_admin]

    if market_choice != "All markets" and "Market_clean" in df_sold_f.columns:
        df_sold_f = df_sold_f[df_sold_f["Market_clean"] == market_choice]
        if "Market_clean" in df_cut_f.columns:
            df_cut_f = df_cut_f[df_cut_f["Market_clean"] == market_choice]

    if acq_rep_choice != "All acquisition reps" and "Acquisition_Rep_clean" in df_sold_f.columns:
        df_sold_f = df_sold_f[df_sold_f["Acquisition_Rep_clean"] == acq_rep_choice]
        if "Acquisition_Rep_clean" in df_cut_f.columns:
            df_cut_f = df_cut_f[df_cut_f["Acquisition_Rep_clean"] == acq_rep_choice]

    return df_sold_f, df_cut_f


def compute_sold_cut_counts(
    df_sold_for_view: pd.DataFrame,
    df_cut_for_view: pd.DataFrame,
    *,
    team_view: str,
    rep_active: bool,
    dispo_rep_choice: str,
) -> tuple[dict[str, int], dict[str, int]]:
    """Compute county sold/cut counts; Dispo rep filter applies only to SOLD."""
    if df_sold_for_view is None:
        df_sold_for_view = pd.DataFrame()
    if df_cut_for_view is None:
        df_cut_for_view = pd.DataFrame()

    df_conv = pd.concat([df_sold_for_view, df_cut_for_view], ignore_index=True)

    # Dispo rep filter only narrows SOLD rows
    if team_view == "Dispo" and rep_active and "Dispo_Rep_clean" in df_conv.columns:
        df_conv = df_conv[(df_conv["Status_norm"] != "sold") | (df_conv["Dispo_Rep_clean"] == dispo_rep_choice)]

    grp = df_conv.groupby("County_clean_up")
    sold_counts = grp.apply(lambda g: (g["Status_norm"] == "sold").sum()).to_dict()
    cut_counts = grp.apply(lambda g: (g["Status_norm"] == "cut loose").sum()).to_dict()
    return sold_counts, cut_counts


def build_rank_df(
    *,
    sold_counts: dict[str, int],
    cut_counts: dict[str, int],
    buyer_count_by_county: dict[str, int],
    health_by_county: dict[str, float],
) -> pd.DataFrame:
    """Build the rankings dataframe (County / Sold / Cut / Totals / Buyer count / Health / Close rate)."""

    counties = sorted(set(list(sold_counts.keys()) + list(cut_counts.keys())))
    rows: list[dict] = []

    for c in counties:
        sold = int(sold_counts.get(c, 0))
        cut = int(cut_counts.get(c, 0))
        total = sold + cut
        close_rate = (sold / total) if total else 0.0

        rows.append(
            {
                "County": c.title(),
                "Sold": sold,
                "Cut loose": cut,
                "Total": total,
                "Buyer count": int(buyer_count_by_county.get(c, 0)),
                "Health score": round(float(health_by_county.get(c, 0.0)), 3),
                "Close rate": round(close_rate * 100, 1),
            }
        )

    return pd.DataFrame(rows)
