import io
import re
import pandas as pd
import requests
import streamlit as st

from core.config import SHEET_URL, MAO_TIERS_URL, REQUIRED_COLS, C


# -------------------------
# Low-level helpers
# -------------------------

def _read_csv(url: str) -> pd.DataFrame:
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


def _normalize_county_key(x: str) -> str:
    """
    Forgiving county join key:
    - uppercase
    - remove the word 'COUNTY'
    - remove anything that's not A-Z
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
    s = series.astype(str).str.replace(r"[\$,]", "", regex=True).str.strip()
    s = s.replace({"": None, "nan": None, "None": None})
    return pd.to_numeric(s, errors="coerce")



# -------------------------
# Phase A2: Single source of truth normalization
# -------------------------

def normalize_inputs(df: pd.DataFrame) -> pd.DataFrame:
    """
    One place to harden and normalize the raw deals sheet.

    Guarantees these columns exist and are correct:
      - County_clean_up, County_key
      - Buyer_clean
      - Status_norm
      - Date_dt, Year
    Also ensures optional columns exist (no KeyErrors).
    """
    df = df.copy()

    # Ensure expected columns exist (even if the sheet changes)
    # (Do not remove columns; only add missing ones.)
    optional_cols = [
    "Salesforce_URL", "Buyer", "Date", "Status", "County", "Address", "City",
    "Dispo Rep", "Contract Price", "Amended Price", "Wholesale Price", "Market", "Acquisition Rep",
]

    for col in optional_cols:
        if col not in df.columns:
            df[col] = ""

    # --- County normalization ---
    county_raw = df[C.county].astype(str).fillna("").str.strip().str.upper()

    # Strip trailing " COUNTY" because GeoJSON + app logic use "DAVIDSON", not "DAVIDSON COUNTY"
    county_clean = county_raw.str.replace(r"\s+COUNTY\b", "", regex=True).str.strip()

    # Known historical typo fix (keep it centralized here)
    county_clean = county_clean.replace({"STEWART COUTY": "STEWART"})

    df["County_clean_up"] = county_clean
    df["County_key"] = df["County_clean_up"].apply(_normalize_county_key)

    # --- Buyer normalization ---
    df["Buyer_clean"] = df[C.buyer].astype(str).fillna("").astype(str).str.strip()

    # --- Status normalization ---
    df["Status_norm"] = _normalize_status(df[C.status])

    # --- Date parsing (momentum.py expects Date_dt) ---
    df["Date_dt"] = pd.to_datetime(df.get(C.date), errors="coerce")
    df["Year"] = df["Date_dt"].dt.year

        # --- Dispo Rep (new column) ---
    # Accept a few possible header spellings
    dispo_col = None
    for cand in ["Dispo Rep", "Dispo_Rep", "DispoRep", "DISPO REP"]:
        if cand in df.columns:
            dispo_col = cand
            break

    if dispo_col is None:
        df["Dispo_Rep"] = ""
    else:
        df["Dispo_Rep"] = df[dispo_col]

    df["Dispo_Rep_clean"] = df["Dispo_Rep"].astype(str).fillna("").str.strip()

        # --- Market + Acquisition Rep (clean) ---
    if "Market" not in df.columns:
        df["Market"] = ""
    df["Market_clean"] = df["Market"].astype(str).fillna("").str.strip()

    if "Acquisition Rep" not in df.columns:
        df["Acquisition Rep"] = ""
    df["Acquisition_Rep_clean"] = df["Acquisition Rep"].astype(str).fillna("").str.strip()

    # --- Financials (numeric) ---
    df["Contract_Price_num"] = _to_number(df["Contract Price"]) if "Contract Price" in df.columns else pd.Series([None] * len(df))
    df["Amended_Price_num"] = _to_number(df["Amended Price"]) if "Amended Price" in df.columns else pd.Series([None] * len(df))
    df["Wholesale_Price_num"] = _to_number(df["Wholesale Price"]) if "Wholesale Price" in df.columns else pd.Series([None] * len(df))

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
        if str(c).strip().lower() in ("county", "county_name", "countyname"):
            county_col = c
            break
    if county_col is None:
        county_col = tiers.columns[0]  # fallback

    # Tier column
    tier_col = None
    for c in tiers.columns:
        lc = str(c).strip().lower()
        if lc in ("tier", "mao tier", "mao_tier"):
            tier_col = c
            break

    # Optional single range column
    range_col = None
    for c in tiers.columns:
        lc = str(c).strip().lower()
        if lc in ("mao range", "mao_range", "range"):
            range_col = c
            break

    # Min/Max columns (your sheet uses these)
    min_col = None
    max_col = None
    for c in tiers.columns:
        lc = str(c).strip().lower()
        if lc in ("mao min", "mao_min", "min"):
            min_col = c
        if lc in ("mao max", "mao_max", "max"):
            max_col = c

    df = pd.DataFrame()

    # Normalize county display name the same way as deals sheet
    county_raw = tiers[county_col].astype(str).fillna("").str.strip().str.upper()
    county_clean = county_raw.str.replace(r"\s+COUNTY\b", "", regex=True).str.strip()
    county_clean = county_clean.replace({"STEWART COUTY": "STEWART"})
    df["County_clean_up"] = county_clean
    df["County_key"] = df["County_clean_up"].apply(_normalize_county_key)

    df["MAO_Tier"] = tiers[tier_col].astype(str).str.strip() if tier_col else ""

    # Build MAO_Range_Str
    if range_col and range_col in tiers.columns:
        df["MAO_Range_Str"] = tiers[range_col].astype(str).str.strip()
    elif min_col and max_col and min_col in tiers.columns and max_col in tiers.columns:
        def to_pct(x):
            try:
                v = float(x)
                if v <= 1.0:
                    v *= 100.0
                return v
            except Exception:
                return None

        mins = tiers[min_col].apply(to_pct)
        maxs = tiers[max_col].apply(to_pct)

        def fmt_range(lo, hi):
            if lo is None and hi is None:
                return ""
            if lo is None:
                return f"≤{hi:.0f}%"
            if hi is None:
                return f"≥{lo:.0f}%"
            return f"{lo:.0f}%–{hi:.0f}%"

        df["MAO_Range_Str"] = [fmt_range(lo, hi) for lo, hi in zip(mins, maxs)]
    else:
        df["MAO_Range_Str"] = ""

    return df[out_cols]


# -------------------------
# Cached loaders (A1 + A2)
# -------------------------

@st.cache_data(ttl=300, show_spinner=False)
def load_mao_tiers() -> pd.DataFrame:
    raw = _read_csv(MAO_TIERS_URL)
    return normalize_tiers(raw)


@st.cache_data(ttl=300, show_spinner=False)
def load_data() -> pd.DataFrame:
    raw = _read_csv(SHEET_URL)

    missing = [c for c in REQUIRED_COLS if c not in raw.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = normalize_inputs(raw)

    # Merge tiers (keep app running if tiers sheet hiccups)
    try:
        tiers = load_mao_tiers()
        if not tiers.empty:
            df = df.merge(
                tiers[["County_key", "MAO_Tier", "MAO_Range_Str"]],
                on="County_key",
                how="left",
            )
    except Exception as e:
        # Internal app: keep running, but surface what happened.
        st.warning(f"Could not load/merge MAO tiers (showing blank tiers). Details: {type(e).__name__}")
        df["MAO_Tier"] = ""
        df["MAO_Range_Str"] = ""

    return df
