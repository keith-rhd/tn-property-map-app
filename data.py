import io
import pandas as pd
import requests
import streamlit as st

from config import SHEET_URL, MAO_TIERS_URL, REQUIRED_COLS, C


def _read_csv(url: str) -> pd.DataFrame:
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


@st.cache_data(ttl=60, show_spinner=False)
def load_mao_tiers() -> pd.DataFrame:
    """
    Loads MAO tiers from the second tab of the same Google Sheet.
    Always returns a dataframe with expected columns.
    """
    cols = ["County_clean_up", "MAO_Tier", "MAO_Range_Str"]

    if not MAO_TIERS_URL:
        return pd.DataFrame(columns=cols)

    try:
        t = _read_csv(MAO_TIERS_URL)
    except Exception:
        return pd.DataFrame(columns=cols)

    # Normalize column names
    lower = {c.lower().strip(): c for c in t.columns}

    def pick(*names):
        for n in names:
            if n in lower:
                return lower[n]
        return None

    county_col = pick("county")
    tier_col = pick("tier", "mao tier")
    range_col = pick("mao range", "range", "mao_range")

    if not county_col or not tier_col:
        return pd.DataFrame(columns=cols)

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
    out["MAO_Range_Str"] = (
        out[range_col].astype(str).str.strip() if range_col else ""
    )

    return out[cols]


@st.cache_data(ttl=60, show_spinner=False)
def load_data() -> pd.DataFrame:
    df = _read_csv(SHEET_URL)

    # Required columns
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Ensure optional columns exist
    if C.status not in df.columns:
        df[C.status] = "Sold"
    if C.buyer not in df.columns:
        df[C.buyer] = ""

    df[C.status] = df[C.status].fillna("Sold")
    df[C.buyer] = df[C.buyer].fillna("")

    # Date parsing
    df["Date_dt"] = pd.to_datetime(df.get(C.date), errors="coerce")
    df["Year"] = df["Date_dt"].dt.year

    # County normalization
    df["County_clean_up"] = (
        df[C.county]
        .astype(str)
        .str.replace(" County", "", case=False)
        .str.strip()
        .str.upper()
    )
    df.loc[df["County_clean_up"] == "STEWART COUTY", "County_clean_up"] = "STEWART"

    # Fields required by filters/momentum
    df["Status_norm"] = df[C.status].astype(str).str.lower().str.strip()
    df["Buyer_clean"] = df[C.buyer].astype(str).str.strip()

    # Merge MAO tiers (safe)
    try:
        tiers = load_mao_tiers()
        if not tiers.empty:
            df = df.merge(tiers, on="County_clean_up", how="left")
    except Exception:
        pass

    # GUARANTEE columns always exist
    if "MAO_Tier" not in df.columns:
        df["MAO_Tier"] = ""
    if "MAO_Range_Str" not in df.columns:
        df["MAO_Range_Str"] = ""

    return df
