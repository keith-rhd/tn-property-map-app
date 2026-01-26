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

    # Special option: rolling 12 months (relative to today).
    # Uses Date_dt which is created in data.normalize_inputs().
    if year_choice == "Rolling 12 months":
        end_dt = pd.Timestamp.now().normalize()
        start_dt = end_dt - pd.DateOffset(months=12)

        sold_mask = (df_time["Status_norm"] == "sold") & (df_time["Date_dt"].notna()) & (df_time["Date_dt"] >= start_dt)
        df_sold = df_time[sold_mask].copy()

        cut_mask = df_time["Status_norm"] == "cut loose"
        cut_has_date = cut_mask & df_time["Date_dt"].notna()
        cut_no_date = cut_mask & df_time["Date_dt"].isna()

        df_cut = pd.concat(
            [df_time[cut_has_date & (df_time["Date_dt"] >= start_dt)], df_time[cut_no_date]],
            ignore_index=True,
        )

        df_both = pd.concat([df_sold, df_cut], ignore_index=True)
        return df_sold, df_cut, df_both

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
    labels = ["All buyers"]
    label_to_buyer = {"All buyers": "All buyers"}

    if not buyer_momentum.empty:
        bm = buyer_momentum.sort_values("sort_val", ascending=False).copy()
        for _, row in bm.iterrows():
            b = str(row.get("Buyer_clean", "")).strip()
            if not b:
                continue
            pct = row.get("pct_change_6m", None)
            if pd.isna(pct):
                label = b
            else:
                label = f"{b} ({pct:+.0%} 6m)"
            labels.append(label)
            label_to_buyer[label] = b

    # Add any buyers not present in momentum calc (edge cases)
    for b in buyers_plain:
        if b not in label_to_buyer.values():
            labels.append(b)
            label_to_buyer[b] = b

    return labels, label_to_buyer

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

def build_view_df(df_sold: pd.DataFrame, df_cut: pd.DataFrame, mode: str) -> pd.DataFrame:
    if mode == "Sold":
        return df_sold.copy()
    if mode == "Cut Loose":
        return df_cut.copy()
    return pd.concat([df_sold, df_cut], ignore_index=True)

def compute_overall_stats(df_sold: pd.DataFrame, df_cut: pd.DataFrame) -> Dict[str, float]:
    out: Dict[str, float] = {}
    out["sold_count"] = float(len(df_sold))
    out["cut_count"] = float(len(df_cut))
    out["total_count"] = float(len(df_sold) + len(df_cut))
    return out
