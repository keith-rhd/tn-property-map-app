import io
import pandas as pd
import requests
import streamlit as st

from config import SHEET_URL, MAO_TIERS_URL, REQUIRED_COLS, C


def read_csv_url(url: str) -> pd.DataFrame:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TNHeatMap/1.0)"
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


@st.cache_data(ttl=60, show_spinner=False)
def load_mao_tiers() -> pd.DataFrame:
    if not MAO_TIERS_URL:
        return pd.DataFrame(
            columns=["County_clean_up", "MAO_Tier", "MAO_Min", "MAO_Max", "MAO_Range_Str"]
        )

    t = read_csv_url(MAO_TIERS_URL)

    cols = {c.strip().lower(): c for c in t.columns}

    def pick(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    county_col = pick("county")
    tier_col = pick("tier", "mao tier")
    min_col = pick("mao min", "min", "mao_min")
    max_col = pick("mao max", "max", "mao_max")

    if not county_col or not tier_col:
        return pd.DataFrame(
            columns=["County_clean_up", "MAO_Tier", "MAO_Min", "MAO_Max", "MAO_Range_Str"]
        )

    out = t.copy()

    out["County_clean_up"] = (
        out[county_col]
        .astype(str)
        .str.replace(" County", "", case=False)
        .str.strip()
        .str.upper()
    )
    out.loc[out["County_clean_up"] == "STEWART COUTY", "County_clean_up"] = "STEWART"

    out["MAO_Tier"] = out[tier_col].astype(str).str.strip()

    out["MAO_Min"] = pd.to_numeric(out[min_col], errors="coerce") if min_col else pd.NA
    out["MAO_Max"] = pd.to_numeric(out[max_col], errors="coerce") if max_col else pd.NA

    def to_pct(x):
        if pd.isna(x):
            return pd.NA
        x = float(x)
        return x * 100 if x <= 1.0 else x

    out["MAO_Min"] = out["MAO_Min"].apply(to_pct)
    out["MAO_Max"] = out["MAO_Max"].apply(to_pct)

    def fmt_range(r):
        mn, mx = r["MAO_Min"], r["MAO_Max"]
        if pd.notna(mn) and pd.notna(mx):
            return f"{round(mn)}%–{round(mx)}%"
        if pd.notna(mn):
            return f"{round(mn)}%+"
        if pd.notna(mx):
            return f"≤{round(mx)}%"
        return ""

    out["MAO_Range_Str"] = out.apply(fmt_range, axis=1)

    return out[
        ["County_clean_up", "MAO_Tier", "MAO_Min", "MAO_Max", "MAO_Range_Str"]
    ]


@st.cache_data(ttl=60, show_spinner=False)
def load_data() -> pd.DataFrame:
    df = read_csv_url(SHEET_URL)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df["Status"] = df.get("Status", "Sold").fillna("Sold")
    df["Buyer"] = df.get("Buyer", "").fillna("")

    df["Date_dt"] = pd.to_datetime(df.get("Date"), errors="coerce")
    df["Year"] = df["Date_dt"].dt.year

    df["County_clean_up"] = (
        df["County"]
        .astype(str)
        .str.replace(" County", "", case=False)
        .str.strip()
        .str.upper()
    )
    df.loc[df["County_clean_up"] == "STEWART COUTY", "County_clean_up"] = "STEWART"

    tiers = load_mao_tiers()
    df = df.merge(tiers, on="County_clean_up", how="left")

    return df
