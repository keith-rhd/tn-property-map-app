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
        # Tier sheet should cover all TN counties (preferred for dropdown)
        mao_tier_by_county = dict(zip(tiers["County_clean_up"], tiers["MAO_Tier"]))
        mao_range_by_county = dict(zip(tiers["County_clean_up"], tiers["MAO_Range_Str"]))
        tier_counties = sorted(tiers["County_clean_up"].dropna().unique().tolist())

    deal_counties = sorted(df.get("County_clean_up", pd.Series(dtype=str)).dropna().unique().tolist())
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

    if dispo_rep_choice_admin not in ("All reps", "All dispo reps") and "Dispo_Rep_clean" in df_sold_f.columns:
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
    """Compute county sold/cut counts; Dispo rep filter applies only to SOLD.

    Vectorized version (faster + clearer) than groupby.apply(lambda ...).
    """
    if df_sold_for_view is None:
        df_sold_for_view = pd.DataFrame()
    if df_cut_for_view is None:
        df_cut_for_view = pd.DataFrame()

    df_conv = pd.concat([df_sold_for_view, df_cut_for_view], ignore_index=True)
    if df_conv.empty:
        return {}, {}

    if "County_clean_up" not in df_conv.columns or "Status_norm" not in df_conv.columns:
        return {}, {}

    # Dispo rep filter only narrows SOLD rows
    if team_view == "Dispo" and rep_active and "Dispo_Rep_clean" in df_conv.columns:
        df_conv = df_conv[(df_conv["Status_norm"] != "sold") | (df_conv["Dispo_Rep_clean"] == dispo_rep_choice)]

    df_conv = df_conv.dropna(subset=["County_clean_up"]).copy()
    df_conv["is_sold"] = df_conv["Status_norm"].eq("sold")
    df_conv["is_cut"] = df_conv["Status_norm"].eq("cut loose")

    grp = df_conv.groupby("County_clean_up", dropna=True)
    sold_counts = grp["is_sold"].sum().astype(int).to_dict()
    cut_counts = grp["is_cut"].sum().astype(int).to_dict()

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


def compute_gp_by_county(df_sold: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    """Compute total GP and avg GP per county (SOLD only)."""
    if df_sold is None or df_sold.empty:
        return {}, {}

    if "County_clean_up" not in df_sold.columns or "Gross_Profit" not in df_sold.columns:
        return {}, {}

    df = df_sold.copy()
    df["Gross_Profit_num"] = pd.to_numeric(df["Gross_Profit"], errors="coerce")
    df = df.dropna(subset=["County_clean_up"])

    grp = df.groupby("County_clean_up")["Gross_Profit_num"]
    gp_total = grp.sum(min_count=1).fillna(0)
    gp_avg = grp.mean().fillna(0)

    return gp_total.to_dict(), gp_avg.to_dict()


def build_admin_metrics(df_time_sold_for_view: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float], dict[str, float]]:
    """Build Admin-only county metrics once (single source of truth).

    Returns:
      - admin_rank_df: columns: County, Total GP, Avg GP, Sold Deals
      - gp_total_by_county: dict for map tooltips
      - gp_avg_by_county: dict for map tooltips
    """
    if df_time_sold_for_view is None or df_time_sold_for_view.empty:
        empty = pd.DataFrame(columns=["County", "Total GP", "Avg GP", "Sold Deals"])
        return empty, {}, {}

    df_admin_sold_only = (
        df_time_sold_for_view[df_time_sold_for_view["Status_norm"] == "sold"]
        if "Status_norm" in df_time_sold_for_view.columns
        else df_time_sold_for_view
    )

    gp_total_by_county, gp_avg_by_county = compute_gp_by_county(df_admin_sold_only)

    sold_deals_by_county = (
        df_admin_sold_only.groupby("County_clean_up").size().to_dict()
        if "County_clean_up" in df_admin_sold_only.columns and not df_admin_sold_only.empty
        else {}
    )

    rows: list[dict] = []
    counties = sorted(set(list(gp_total_by_county.keys()) + list(sold_deals_by_county.keys())))
    for county_up in counties:
        rows.append(
            {
                "County": str(county_up).title(),
                "Total GP": float(gp_total_by_county.get(county_up, 0.0) or 0.0),
                "Avg GP": float(gp_avg_by_county.get(county_up, 0.0) or 0.0),
                "Sold Deals": int(sold_deals_by_county.get(county_up, 0) or 0),
            }
        )

    admin_rank_df = pd.DataFrame(rows)
    return admin_rank_df, gp_total_by_county, gp_avg_by_county


def compute_admin_headline_metrics(df_sold_only: pd.DataFrame) -> dict[str, float | int]:
    """Compute Admin dashboard headline numbers once (sold-only frame)."""
    if df_sold_only is None or df_sold_only.empty:
        return {"total_gp": 0.0, "total_wholesale": 0.0, "sold_count": 0, "avg_gp": 0.0}

    df = df_sold_only.copy()

    gp = pd.to_numeric(df.get("Gross_Profit"), errors="coerce").fillna(0)
    total_gp = float(gp.sum())

    # Wholesale: prefer Wholesale_Price_num, else Wholesale_Price if present
    if "Wholesale_Price_num" in df.columns:
        wholesale = pd.to_numeric(df["Wholesale_Price_num"], errors="coerce").fillna(0)
    elif "Wholesale_Price" in df.columns:
        wholesale = pd.to_numeric(df["Wholesale_Price"], errors="coerce").fillna(0)
    else:
        wholesale = pd.Series([0] * len(df), dtype="float")

    total_wholesale = float(wholesale.sum())
    sold_count = int(len(df))
    avg_gp = float(total_gp / sold_count) if sold_count else 0.0

    return {
        "total_gp": total_gp,
        "total_wholesale": total_wholesale,
        "sold_count": sold_count,
        "avg_gp": avg_gp,
    }


def build_county_gp_table(df_sold_only: pd.DataFrame) -> pd.DataFrame:
    """Build the county-level table used on the Admin dashboard.

    Columns:
      County, Sold Deals, Total GP, Avg GP, (optional) Total Wholesale, Avg Wholesale
    """
    cols = ["County", "Sold Deals", "Total GP", "Avg GP", "Total Wholesale", "Avg Wholesale"]

    if df_sold_only is None or df_sold_only.empty:
        return pd.DataFrame(columns=cols)

    if "County_clean_up" not in df_sold_only.columns:
        return pd.DataFrame(columns=cols)

    df = df_sold_only.copy()
    df = df.dropna(subset=["County_clean_up"]).copy()

    # Numeric conversions once
    df["Gross_Profit_num"] = pd.to_numeric(df.get("Gross_Profit"), errors="coerce")

    if "Wholesale_Price_num" in df.columns:
        df["Wholesale_num"] = pd.to_numeric(df["Wholesale_Price_num"], errors="coerce")
    elif "Wholesale_Price" in df.columns:
        df["Wholesale_num"] = pd.to_numeric(df["Wholesale_Price"], errors="coerce")
    else:
        df["Wholesale_num"] = pd.NA

    grp = df.groupby("County_clean_up", dropna=True)

    out = pd.DataFrame(
        {
            "County": grp.size().index.astype(str).str.title(),
            "Sold Deals": grp.size().astype(int).values,
            "Total GP": grp["Gross_Profit_num"].sum(min_count=1).fillna(0).values,
            "Avg GP": grp["Gross_Profit_num"].mean().fillna(0).values,
        }
    )

    if df["Wholesale_num"].notna().any():
        out["Total Wholesale"] = grp["Wholesale_num"].sum(min_count=1).fillna(0).values
        out["Avg Wholesale"] = grp["Wholesale_num"].mean().fillna(0).values
    else:
        # keep columns present but empty to simplify downstream
        out["Total Wholesale"] = 0.0
        out["Avg Wholesale"] = 0.0

    # Ensure numeric
    for c in ["Total GP", "Avg GP", "Total Wholesale", "Avg Wholesale"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)

    return out.reset_index(drop=True)
