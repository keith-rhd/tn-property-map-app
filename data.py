# data.py
import io
import requests
import pandas as pd
import streamlit as st
from config import SHEET_URL, REQUIRED_COLS, C, MAO_TIERS_URL


def read_csv_url(url: str) -> pd.DataFrame:
    """
    Fetch CSV via requests (more reliable than pandas+urllib on Streamlit Cloud),
    then parse with pandas.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TNHeatMap/1.0; +https://streamlit.io)"
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


@st.cache_data(ttl=60, show_spinner=False)
def load_mao_tiers() -> pd.DataFrame:
    """Load MAO tiers from the live 'MAO Tiers' tab."""
    try:
        tiers = pd.read_csv(MAO_TIERS_URL)
    except Exception:
        # If the sheet isn't public / published correctly yet, fail softly.
        return pd.DataFrame(columns=["County_clean_up", "MAO_Tier", "MAO_Min", "MAO_Max", "MAO_Range_Str"])

    # Normalize columns (handles small naming differences)
    cols = {c.strip().lower(): c for c in tiers.columns}

    def pick(*names: str) -> str | None:
        for n in names:
            if n in cols:
                return cols[n]
        return None

    county_col = pick("county", "counties")
    tier_col = pick("tier", "mao tier", "mao_tier")
    min_col = pick("mao_min", "mao min", "min", "min mao")
    max_col = pick("mao_max", "mao max", "max", "max mao")

    if not county_col or not tier_col:
        return pd.DataFrame(columns=["County_clean_up", "MAO_Tier", "MAO_Min", "MAO_Max", "MAO_Range_Str"])

    out = tiers.copy()
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

    @st.cache_data(ttl=60, show_spinner=False)
def load_mao_tiers() -> pd.DataFrame:
    if not MAO_TIERS_URL:
        return pd.DataFrame(
            columns=["County_clean_up", "MAO_Tier", "MAO_Min", "MAO_Max", "MAO_Range_Str"]
        )

    t = read_csv_url(MAO_TIERS_URL)

    # Normalize column names
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

    # Normalize county
    out["County_clean_up"] = (
        out[county_col]
        .astype(str)
        .str.replace(" County", "", case=False)
        .str.strip()
        .str.upper()
    )
    out.loc[out["County_clean_up"] == "STEWART COUTY", "County_clean_up"] = "STEWART"

    out["MAO_Tier"] = out[tier_col].astype(str).str.strip()

    # Convert MAO min/max to numeric
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



    return out[["County_clean_up", "MAO_Tier", "MAO_Min", "MAO_Max", "MAO_Range_Str"]]

@st.cache_data(ttl=60, show_spinner=False)
def load_data() -> pd.DataFrame:
    df = read_csv_url(SHEET_URL)

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        st.error(f"Missing required columns in sheet: {missing}")
        st.stop()

    if C.status not in df.columns:
        df[C.status] = "Sold"
    df[C.status] = df[C.status].fillna("Sold")

    if C.buyer not in df.columns:
        df[C.buyer] = ""
    df[C.buyer] = df[C.buyer].fillna("")

    if C.date not in df.columns:
        df[C.date] = pd.NA

    df["Date_dt"] = pd.to_datetime(df[C.date], errors="coerce")
    df["Year"] = df["Date_dt"].dt.year

    df["County_clean"] = (
        df[C.county].astype(str).str.replace(" County", "", case=False).str.strip()
    )
    df["County_clean_up"] = df["County_clean"].str.upper()
    df.loc[df["County_clean_up"] == "STEWART COUTY", "County_clean_up"] = "STEWART"

    # Merge live MAO tiers (County -> Tier + Range)
    tiers = load_mao_tiers()
    if not tiers.empty:
        df = df.merge(tiers, on="County_clean_up", how="left")
    else:
        df["MAO_Tier"] = ""
        df["MAO_Range_Str"] = ""

    df["Status_norm"] = df[C.status].astype(str).str.lower().str.strip()
    df["Buyer_clean"] = df[C.buyer].astype(str).str.strip()

    return df
