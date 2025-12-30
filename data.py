import io
import re
import pandas as pd
import requests
import streamlit as st

from config import SHEET_URL, MAO_TIERS_URL, REQUIRED_COLS, C


def _read_csv(url: str) -> pd.DataFrame:
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


def _normalize_county_key(x: str) -> str:
    """
    Forgiving county normalizer used for joins.
    Removes:
      - word COUNTY
      - punctuation/spaces
    Keeps only A–Z.
    """
    s = "" if x is None else str(x)
    s = s.upper().strip()
    s = re.sub(r"\bCOUNTY\b", "", s)
    s = re.sub(r"[^A-Z]", "", s)
    return s


def _normalize_status(series: pd.Series) -> pd.Series:
    """
    Canonicalize to exactly:
      - 'sold'
      - 'cut loose'
    """
    s = series.fillna("").astype(str).str.strip().str.lower()
    compact = (
        s.str.replace(r"[\s\-_]+", "", regex=True)
         .str.replace(r"[^a-z]", "", regex=True)
    )

    out = pd.Series([""] * len(s), index=s.index, dtype="object")
    out.loc[compact.isin(["sold", "closed", "close", "closing", "settled"])] = "sold"
    out.loc[compact.isin(["cutloose", "cutlose", "cut"])] = "cut loose"
    return out


@st.cache_data(ttl=300, show_spinner=False)
def load_mao_tiers() -> pd.DataFrame:
    out_cols = ["County_clean_up", "County_key", "MAO_Tier", "MAO_Range_Str"]

    tiers = _read_csv(MAO_TIERS_URL)
    if tiers.empty:
        return pd.DataFrame(columns=out_cols)

    tiers.columns = [str(c).strip() for c in tiers.columns]

    # Find county column
    county_col = None
    for c in tiers.columns:
        if str(c).strip().lower() in ("county", "county_name", "countyname"):
            county_col = c
            break
    if county_col is None:
        county_col = tiers.columns[0]

    # Find tier column
    tier_col = None
    for c in tiers.columns:
        if str(c).strip().lower() in ("mao tier", "mao_tier", "tier"):
            tier_col = c
            break

    # Find range column
    range_col = None
    for c in tiers.columns:
        if str(c).strip().lower() in ("mao range", "mao_range", "range"):
            range_col = c
            break

    df = pd.DataFrame()
    df["County_clean_up"] = tiers[county_col].astype(str).str.strip().str.upper()
    # IMPORTANT: tiers sheet may already omit "County", but normalize key regardless
    df["County_key"] = df["County_clean_up"].apply(_normalize_county_key)
    df["MAO_Tier"] = tiers[tier_col].astype(str).str.strip() if tier_col else ""
    df["MAO_Range_Str"] = tiers[range_col].astype(str).str.strip() if range_col else ""

    return df[out_cols]


@st.cache_data(ttl=300, show_spinner=False)
def load_data() -> pd.DataFrame:
    df = _read_csv(SHEET_URL)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Ensure these exist even if the sheet changes
    for col in ("Salesforce_URL", "Buyer", "Date", "Status", "County", "Address", "City"):
        if col not in df.columns:
            df[col] = ""

    # -----------------------------
    # County cleanup (CRITICAL FIX)
    # -----------------------------
    # Sheet has "Marion County", GeoJSON has "MARION"
    county_raw = df[C.county].astype(str).fillna("").str.strip().str.upper()

    # Remove trailing " COUNTY" (and any standalone COUNTY word)
    county_clean = county_raw.str.replace(r"\s+COUNTY\b", "", regex=True).str.strip()

    # Keep your historical fix
    county_clean = county_clean.replace({"STEWART COUTY": "STEWART"})

    df["County_clean_up"] = county_clean

    # Join key for tiers merge
    df["County_key"] = df["County_clean_up"].apply(_normalize_county_key)

    # Buyer cleanup
    df["Buyer_clean"] = df[C.buyer].astype(str).fillna("").astype(str).str.strip()

    # Status normalization expected by filters.py
    df["Status_norm"] = _normalize_status(df[C.status])

    # Date parsing expected by momentum.py
    df["Date_dt"] = pd.to_datetime(df.get(C.date), errors="coerce")
    df["Year"] = df["Date_dt"].dt.year

    # Merge tiers (don’t crash app if tiers sheet has issues)
    try:
        tiers = load_mao_tiers()
        if not tiers.empty:
            df = df.merge(
                tiers[["County_key", "MAO_Tier", "MAO_Range_Str"]],
                on="County_key",
                how="left",
            )
    except Exception:
        df["MAO_Tier"] = ""
        df["MAO_Range_Str"] = ""

    return df
