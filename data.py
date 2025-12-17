# data.py
import io
import requests
import pandas as pd
import streamlit as st
from config import SHEET_URL, REQUIRED_COLS, C, MAO_TIERS_URL


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

    def fmt_range(row) -> str:
        mn, mx = row["MAO_Min"], row["MAO_Max"]
        if pd.notna(mn) and pd.notna(mx):
            return f"{int(mn)}%–{int(mx)}%"
        if pd.notna(mn):
            return f"{int(mn)}%+"
        if pd.notna(mx):
            return f"≤{int(mx)}%"
        return ""

    out["MAO_Range_Str"] = out.apply(fmt_range, axis=1)

    return out[["County_clean_up", "MAO_Tier", "MAO_Min", "MAO_Max", "MAO_Range_Str"]]

@st.cache_data(ttl=60, show_spinner=False)
def load_data() -> pd.DataFrame:
    df = pd.read_csv(SHEET_URL)

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
