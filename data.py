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
    Loads MAO tiers from the MAO Tiers tab.
    Supports either:
      - a single 'MAO Range' column, OR
      - 'MAO Min' / 'MAO Max' columns (decimals like 0.73 supported).
    Always returns: County_clean_up, MAO_Tier, MAO_Range_Str
    """
    out_cols = ["County_clean_up", "MAO_Tier", "MAO_Range_Str"]

    if not MAO_TIERS_URL:
        return pd.DataFrame(columns=out_cols)

    try:
        t = _read_csv(MAO_TIERS_URL)
    except Exception:
        return pd.DataFrame(columns=out_cols)

    lower = {c.lower().strip(): c for c in t.columns}

    def pick(*names):
        for n in names:
            if n in lower:
                return lower[n]
        return None

    county_col = pick("county")
    tier_col = pick("tier", "mao tier")
    range_col = pick("mao range", "range", "mao_range")

    min_col = pick("mao min", "min", "mao_min", "min mao")
    max_col = pick("mao max", "max", "mao_max", "max mao")

    if not county_col or not tier_col:
        return pd.DataFrame(columns=out_cols)

    df = t.copy()

    df["County_clean_up"] = (
        df[county_col]
        .astype(str)
        .str.replace(" County", "", case=False)
        .str.strip()
        .str.upper()
    )
    df.loc[df["County_clean_up"] == "STEWART COUTY", "County_clean_up"] = "STEWART"

    df["MAO_Tier"] = df[tier_col].astype(str).str.strip()

    # Preferred: a single explicit MAO Range column
    if range_col:
        df["MAO_Range_Str"] = df[range_col].astype(str).str.strip()
        return df[out_cols]

    # Fallback: build from min/max
    df["_mn"] = pd.to_numeric(df[min_col], errors="coerce") if min_col else pd.NA
    df["_mx"] = pd.to_numeric(df[max_col], errors="coerce") if max_col else pd.NA

    def to_pct(x):
        if pd.isna(x):
            return pd.NA
        x = float(x)
        return x * 100 if x <= 1.0 else x  # handle 0.73 vs 73

    df["_mn"] = df["_mn"].apply(to_pct)
    df["_mx"] = df["_mx"].apply(to_pct)

    def fmt_range(r):
        mn, mx = r["_mn"], r["_mx"]
        if pd.notna(mn) and pd.notna(mx):
            return f"{round(mn)}%–{round(mx)}%"
        if pd.notna(mn):
            return f"{round(mn)}%+"
        if pd.notna(mx):
            return f"≤{round(mx)}%"
        return ""

    df["MAO_Range_Str"] = df.apply(fmt_range, axis=1)

    return df[out_cols]


@st.cache_data(ttl=60, show_spinner=False)
def load_data() -> pd.DataFrame:
    df = _read_csv(SHEET_URL)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Optional columns
    if C.status not in df.columns:
        df[C.status] = "Sold"
    if C.buyer not in df.columns:
        df[C.buyer] = ""

    df[C.status] = df[C.status].fillna("Sold")
    df[C.buyer] = df[C.buyer].fillna("")

    # Dates
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

    # Needed by filters.py / momentum.py
    df["Status_norm"] = df[C.status].astype(str).str.lower().str.strip()
    df["Buyer_clean"] = df[C.buyer].astype(str).str.strip()

    # Merge MAO tiers (safe)
    try:
        tiers = load_mao_tiers()
        if not tiers.empty:
            df = df.merge(tiers, on="County_clean_up", how="left")
    except Exception:
        pass

    # Guarantee columns exist (prevents KeyError in app.py)
    if "MAO_Tier" not in df.columns:
        df["MAO_Tier"] = ""
    if "MAO_Range_Str" not in df.columns:
        df["MAO_Range_Str"] = ""

    return df
