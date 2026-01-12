import io
import os
import re
import pandas as pd
import requests
import streamlit as st

from config import SHEET_URL, MAO_TIERS_URL, REQUIRED_COLS, C


# -------------------------
# Low-level helpers
# -------------------------

def _read_csv(url: str) -> pd.DataFrame:
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


def _normalize_county_key(x: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(x).strip().lower())


def _normalize_status(series: pd.Series) -> pd.Series:
    """
    Canonicalize to exactly:
      - 'sold'
      - 'cut loose'
    Everything else becomes ''.
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


def _to_number(series: pd.Series) -> pd.Series:
    """
    Convert money-like strings to floats.
    Examples: "$74,000" -> 74000.0 ; "" -> NaN
    """
    if series is None:
        return pd.Series(dtype="float64")
    s = series.copy()
    s = s.astype(str).str.replace(r"[\$,]", "", regex=True).str.strip()
    s = s.replace({"": None, "nan": None, "None": None})
    return pd.to_numeric(s, errors="coerce")


def normalize_inputs(df: pd.DataFrame) -> pd.DataFrame:
    """
    One place to harden and normalize the raw deals sheet.

    Guarantees these columns exist and are correct:
      - County_clean_up, County_key
      - Buyer_clean
      - Status_norm
      - Date_dt, Year
      - Dispo_Rep_clean
      - Market_clean, Acquisition_Rep_clean
      - Contract_Price_num, Amended_Price_num, Wholesale_Price_num
      - Effective_Contract_Price, Gross_Profit
    Also ensures optional columns exist (no KeyErrors).
    """
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Ensure expected columns exist (even if the sheet changes)
    optional_cols = [
        "Salesforce_URL", "Buyer", "Date", "Status", "County", "Address", "City",
        "Dispo Rep", "Contract Price", "Amended Price", "Wholesale Price", "Market", "Acquisition Rep"
    ]
    for col in optional_cols:
        if col not in df.columns:
            df[col] = ""

    # --- County normalization ---
    county_raw = df[C.county].astype(str).fillna("").str.strip().str.upper()
    county_clean = county_raw.str.replace(r"\s+COUNTY\b", "", regex=True).str.strip()
    county_clean = county_clean.replace({"STEWART COUTY": "STEWART"})  # historical typo fix
    df["County_clean_up"] = county_clean
    df["County_key"] = df["County_clean_up"].apply(_normalize_county_key)

    # --- Buyer normalization ---
    df["Buyer_clean"] = df[C.buyer].astype(str).fillna("").astype(str).str.strip()

    # --- Status normalization ---
    df["Status_norm"] = _normalize_status(df[C.status])

    # --- Date parsing ---
    df["Date_dt"] = pd.to_datetime(df.get(C.date), errors="coerce")
    df["Year"] = df["Date_dt"].dt.year

    # --- Dispo Rep ---
    dispo_col = None
    for cand in ["Dispo Rep", "Dispo_Rep", "DispoRep", "DISPO REP"]:
        if cand in df.columns:
            dispo_col = cand
            break
    df["Dispo_Rep"] = df[dispo_col] if dispo_col else ""
    df["Dispo_Rep_clean"] = df["Dispo_Rep"].astype(str).fillna("").str.strip()

    # --- Market ---
    market_col = None
    for cand in ["Market", "MARKET"]:
        if cand in df.columns:
            market_col = cand
            break
    df["Market"] = df[market_col] if market_col else ""
    df["Market_clean"] = df["Market"].astype(str).fillna("").str.strip()

    # --- Acquisition Rep ---
    acq_col = None
    for cand in ["Acquisition Rep", "Acq Rep", "Acquisitions Rep", "ACQUISITION REP"]:
        if cand in df.columns:
            acq_col = cand
            break
    df["Acquisition_Rep"] = df[acq_col] if acq_col else ""
    df["Acquisition_Rep_clean"] = df["Acquisition_Rep"].astype(str).fillna("").str.strip()

    # --- Financials (numeric) ---
    df["Contract_Price_num"] = _to_number(df.get("Contract Price"))
    df["Amended_Price_num"] = _to_number(df.get("Amended Price"))
    df["Wholesale_Price_num"] = _to_number(df.get("Wholesale Price"))

    # Effective contract price = amended if present else contract
    df["Effective_Contract_Price"] = df["Contract_Price_num"]
    has_amended = df["Amended_Price_num"].notna()
    df.loc[has_amended, "Effective_Contract_Price"] = df.loc[has_amended, "Amended_Price_num"]

    # Gross Profit = Wholesale - Effective Contract (only when both exist)
    df["Gross_Profit"] = df["Wholesale_Price_num"] - df["Effective_Contract_Price"]

    return df


def normalize_tiers(tiers: pd.DataFrame) -> pd.DataFrame:
    """
    One place to normalize the MAO tiers sheet so it matches the rest of the app.
    Returns:
      County_clean_up, County_key, MAO_Tier, MAO_Range_Str
    """
    out_cols = ["County_clean_up", "County_key", "MAO_Tier", "MAO_Range_Str"]
    if tiers is None or tiers.empty:
        return pd.DataFrame(columns=out_cols)

    tiers = tiers.copy()
    tiers.columns = [str(c).strip() for c in tiers.columns]

    # County column
    county_col = None
    for c in tiers.columns:
        if str(c).strip().lower() == "county":
            county_col = c
            break
    if county_col is None:
        return pd.DataFrame(columns=out_cols)

    tiers["County_clean_up"] = (
        tiers[county_col].astype(str).fillna("").str.strip().str.upper()
        .str.replace(r"\s+COUNTY\b", "", regex=True).str.strip()
    )
    tiers["County_key"] = tiers["County_clean_up"].apply(_normalize_county_key)

    # Tier column
    tier_col = None
    for c in tiers.columns:
        if str(c).strip().lower() == "tier":
            tier_col = c
            break
    tiers["MAO_Tier"] = tiers[tier_col] if tier_col else ""

    # MAO min/max columns
    min_col = None
    max_col = None
    for c in tiers.columns:
        if str(c).strip().lower() in ["mao min", "maomin"]:
            min_col = c
        if str(c).strip().lower() in ["mao max", "maomax"]:
            max_col = c

    def to_pct(x):
        try:
            v = float(x)
            if v <= 1.0:
                v *= 100.0
            return v
        except Exception:
            return None

    mins = tiers[min_col].apply(to_pct) if min_col else pd.Series([None] * len(tiers))
    maxs = tiers[max_col].apply(to_pct) if max_col else pd.Series([None] * len(tiers))

    def fmt_range(lo, hi):
        if lo is None and hi is None:
            return ""
        if lo is None:
            return f"≤{hi:.0f}%"
        if hi is None:
            return f"≥{lo:.0f}%"
        return f"{lo:.0f}–{hi:.0f}%"

    tiers["MAO_Range_Str"] = [fmt_range(lo, hi) for lo, hi in zip(mins, maxs)]

    return tiers[out_cols]


@st.cache_data(show_spinner=False)
def load_mao_tiers() -> pd.DataFrame:
    tiers = _read_csv(MAO_TIERS_URL)
    return normalize_tiers(tiers)


@st.cache_data(show_spinner=False)
def load_data() -> pd.DataFrame:
    df = _read_csv(SHEET_URL)

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in Google Sheet: {missing}")

    return normalize_inputs(df)
