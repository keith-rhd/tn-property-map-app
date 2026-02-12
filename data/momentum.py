# momentum.py
import pandas as pd

def compute_buyer_momentum(df_time_sold: pd.DataFrame) -> pd.DataFrame:
    sold = df_time_sold.copy()
    sold["Buyer_clean"] = sold["Buyer_clean"].fillna("").astype(str).str.strip()

    anchor = sold["Date_dt"].max()
    if pd.isna(anchor):
        anchor = pd.Timestamp.today()

    last12_start = anchor - pd.Timedelta(days=365)
    prev12_start = anchor - pd.Timedelta(days=730)

    df_last12 = sold[(sold["Date_dt"] > last12_start) & (sold["Date_dt"] <= anchor)]
    df_prev12 = sold[(sold["Date_dt"] > prev12_start) & (sold["Date_dt"] <= last12_start)]

    last12_counts = df_last12[df_last12["Buyer_clean"] != ""].groupby("Buyer_clean").size()
    prev12_counts = df_prev12[df_prev12["Buyer_clean"] != ""].groupby("Buyer_clean").size()

    bm = pd.DataFrame({"last12": last12_counts, "prev12": prev12_counts}).fillna(0).astype(int)
    bm["delta"] = bm["last12"] - bm["prev12"]
    return bm
