# filters.py
from dataclasses import dataclass
from typing import Dict, List, Tuple
import pandas as pd
from momentum import compute_buyer_momentum


@dataclass(frozen=True)
class Selection:
    mode: str
    year_choice: str
    buyer_choice: str
    buyer_active: bool
    top_n: int


@dataclass(frozen=True)
class FilteredData:
    df_time_sold: pd.DataFrame
    df_time_cut: pd.DataFrame
    df_time_filtered: pd.DataFrame
    years_available: List[int]
    buyers_plain: List[str]
    buyer_momentum: pd.DataFrame


def get_years_available(df: pd.DataFrame) -> List[int]:
    ys = [int(y) for y in df["Year"].dropna().unique().tolist() if pd.notna(y)]
    return sorted(ys)


def split_by_year(df: pd.DataFrame, year_choice) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df_time = df.copy()

    # ✅ Special option: rolling 12 months (relative to "now" on Streamlit server)
    # Uses Date_dt which is created upstream in data normalization.
    if year_choice == "Rolling 12 months":
        end_dt = pd.Timestamp.now().normalize()
        start_dt = end_dt - pd.DateOffset(months=12)

        sold_mask = (
            (df_time["Status_norm"] == "sold")
            & (df_time["Date_dt"].notna())
            & (df_time["Date_dt"] >= start_dt)
            & (df_time["Date_dt"] <= end_dt)
        )
        df_sold = df_time[sold_mask].copy()

        # For cut loose, keep rows with missing dates (so they don't disappear),
        # and filter dated cut-loose rows to the rolling window.
        cut_mask = df_time["Status_norm"] == "cut loose"
        cut_has_date = cut_mask & df_time["Date_dt"].notna()
        cut_no_date = cut_mask & df_time["Date_dt"].isna()

        df_cut = pd.concat(
            [
                df_time[cut_has_date & (df_time["Date_dt"] >= start_dt) & (df_time["Date_dt"] <= end_dt)],
                df_time[cut_no_date],
            ],
            ignore_index=True,
        )

        df_both = pd.concat([df_sold, df_cut], ignore_index=True)
        return df_sold, df_cut, df_both

    # Existing behavior: All years or specific year
    if year_choice != "All years":
        y = int(year_choice)
        df_sold = df_time[(df_time["Status_norm"] == "sold") & (df_time["Year"] == y)].copy()

        cut_mask = df_time["Status_norm"] == "cut loose"
        cut_has_year = cut_mask & df_time["Year"].notna()
        cut_no_year = cut_mask & df_time["Year"].isna()

        df_cut = pd.concat(
            [df_time[cut_has_year & (df_time["Year"] == y)], df_time[cut_no_year]],
            ignore_index=True,
        )
    else:
        df_sold = df_time[df_time["Status_norm"] == "sold"].copy()
        df_cut = df_time[df_time["Status_norm"] == "cut loose"].copy()

    df_both = pd.concat([df_sold, df_cut], ignore_index=True)
    return df_sold, df_cut, df_both


def buyer_options(df_time_sold: pd.DataFrame):
    bm = compute_buyer_momentum(df_time_sold)
    buyers_plain = sorted([b for b in df_time_sold["Buyer_clean"].astype(str).str.strip().unique().tolist() if b])
    return buyers_plain, bm


def build_buyer_labels(buyer_momentum: pd.DataFrame, buyers_plain: List[str]):
    """
    Builds dropdown labels for buyers.

    Supports BOTH momentum formats:
    - "legacy" style: columns like last12/prev12/delta with Buyer_clean in the INDEX (your current momentum.py)
    - "new" style: columns like Buyer_clean + sort_val + pct_change_6m (from earlier refactors)
    """
    labels = ["All buyers"]
    label_to_buyer = {"All buyers": "All buyers"}

    if buyer_momentum is None or buyer_momentum.empty:
        for b in buyers_plain:
            labels.append(b)
            label_to_buyer[b] = b
        return labels, label_to_buyer

    bm = buyer_momentum.copy()

    # Normalize buyer name into a column named Buyer_clean
    if "Buyer_clean" not in bm.columns:
        # Often the index is Buyer_clean
        bm = bm.reset_index()
        # If the reset index column isn't named Buyer_clean, rename first column to Buyer_clean
        if "Buyer_clean" not in bm.columns and len(bm.columns) > 0:
            bm = bm.rename(columns={bm.columns[0]: "Buyer_clean"})

    bm["Buyer_clean"] = bm["Buyer_clean"].fillna("").astype(str).str.strip()
    bm = bm[bm["Buyer_clean"] != ""].copy()

    # Determine a sort strategy that works for either format
    if "sort_val" in bm.columns:
        bm = bm.sort_values("sort_val", ascending=False)
        for _, row in bm.iterrows():
            b = row["Buyer_clean"]
            pct = row.get("pct_change_6m", None)
            if pd.isna(pct):
                labels.append(f"{b}")
            else:
                labels.append(f"{b} ({pct:+.0%} 6m)")
            label_to_buyer[labels[-1]] = b
    else:
        # Your current momentum.py: last12 / prev12 / delta
        # If missing any columns, fill with 0 so we don't crash.
        for col in ["last12", "prev12", "delta"]:
            if col not in bm.columns:
                bm[col] = 0

        bm["last12"] = pd.to_numeric(bm["last12"], errors="coerce").fillna(0).astype(int)
        bm["prev12"] = pd.to_numeric(bm["prev12"], errors="coerce").fillna(0).astype(int)
        bm["delta"] = pd.to_numeric(bm["delta"], errors="coerce").fillna(0).astype(int)

        bm = bm.sort_values(["last12", "delta"], ascending=False)

        for _, row in bm.iterrows():
            b = row["Buyer_clean"]
            d = int(row["delta"])
            arrow = "▲" if d > 0 else ("▼" if d < 0 else "→")
            labels.append(f"{b}  {arrow} {d:+d}  ({int(row['last12'])} vs {int(row['prev12'])})")
            label_to_buyer[labels[-1]] = b

    # Add any buyers not covered in momentum (edge cases)
    for b in buyers_plain:
        if b and b not in label_to_buyer.values():
            labels.append(b)
            label_to_buyer[b] = b

    return labels, label_to_buyer


def build_view_df(df_time_sold: pd.DataFrame, df_time_cut: pd.DataFrame, sel: Selection) -> pd.DataFrame:
    if sel.mode == "Sold":
        df_view = df_time_sold.copy()
        if sel.buyer_active:
            df_view = df_view[df_view["Buyer_clean"] == sel.buyer_choice]
        return df_view

    if sel.mode == "Cut Loose":
        return df_time_cut.copy()

    df_sold = df_time_sold.copy()
    if sel.buyer_active:
        df_sold = df_sold[df_sold["Buyer_clean"] == sel.buyer_choice]
    return pd.concat([df_sold, df_time_cut.copy()], ignore_index=True)


def compute_overall_stats(df_time_sold: pd.DataFrame, df_time_cut: pd.DataFrame) -> Dict[str, object]:
    sold_total = int(len(df_time_sold))
    cut_total = int(len(df_time_cut))
    total_deals = sold_total + cut_total

    total_buyers = int(df_time_sold.loc[df_time_sold["Buyer_clean"] != "", "Buyer_clean"].nunique())

    close_rate = (sold_total / total_deals) if total_deals > 0 else None
    close_rate_str = f"{close_rate*100:.1f}%" if close_rate is not None else "N/A"

    return dict(
        sold_total=sold_total,
        cut_total=cut_total,
        total_deals=total_deals,
        total_buyers=total_buyers,
        close_rate_str=close_rate_str,
    )


def prepare_filtered_data(df: pd.DataFrame, year_choice) -> FilteredData:
    df_time_sold, df_time_cut, df_time_filtered = split_by_year(df, year_choice)
    buyers_plain, buyer_momentum = buyer_options(df_time_sold)
    return FilteredData(
        df_time_sold=df_time_sold,
        df_time_cut=df_time_cut,
        df_time_filtered=df_time_filtered,
        years_available=get_years_available(df),
        buyers_plain=buyers_plain,
        buyer_momentum=buyer_momentum,
    )
