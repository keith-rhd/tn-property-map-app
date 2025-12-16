# county_trends.py
import pandas as pd


def compute_county_trends(df_time_sold: pd.DataFrame) -> pd.DataFrame:
    """
    County trend based on SOLD deals only:
      delta = sold deals in last 12 months - sold deals in prior 12 months

    Returns a DataFrame indexed by County_clean_up with columns:
      last12, prev12, delta
    """
    sold = df_time_sold.copy()

    anchor = sold["Date_dt"].max()
    if pd.isna(anchor):
        anchor = pd.Timestamp.today()

    last12_start = anchor - pd.Timedelta(days=365)
    prev12_start = anchor - pd.Timedelta(days=730)

    last12 = sold[(sold["Date_dt"] > last12_start) & (sold["Date_dt"] <= anchor)]
    prev12 = sold[(sold["Date_dt"] > prev12_start) & (sold["Date_dt"] <= last12_start)]

    last12_counts = last12.groupby("County_clean_up").size()
    prev12_counts = prev12.groupby("County_clean_up").size()

    trends = (
        pd.DataFrame({"last12": last12_counts, "prev12": prev12_counts})
        .fillna(0)
        .astype(int)
    )
    trends["delta"] = trends["last12"] - trends["prev12"]
    return trends


def format_trend(delta: int) -> str:
    """
    Formats delta as arrows for display.
    """
    if delta > 0:
        return f"▲ +{delta}"
    if delta < 0:
        return f"▼ {delta}"
    return "→ 0"
