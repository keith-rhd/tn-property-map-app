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
    Very forgiving county normalizer used ONLY for joining tiers <-> deals.
    Removes:
      - 'COUNTY' word
      - punctuation
      - all whitespace
    Keeps only A–Z characters.
    """
    s = "" if x is None else str(x)
    s = s.upper().strip()
    s = re.sub(r"\bCOUNTY\b", "", s)  # remove word COUNTY if present
    s = re.sub(r"[^A-Z]", "", s)      # keep only letters (removes spaces, punctuation)
    return s


@st.cache_data(ttl=300, show_spinner=False)
def load_mao_tiers() -> pd.DataFrame:
    """
    Loads MAO tiers from the MAO Tiers tab.
    Supports either:
      - a single 'MAO Range' column, OR
      - 'MAO Min' / 'MAO Max' columns (decimals like 0.73 supported).
    Always returns: County_clean_up, County_key, MAO_Tier, MAO_Range_Str
    """
    out_cols = ["County_clean_up", "County_key", "MAO_Tier", "MAO_Range_Str"]

    tiers = _read_csv(MAO_TIERS_URL)
    if tiers.empty:
        return pd.DataFrame(columns=out_cols)

    # Normalize columns
    tiers.columns = [str(c).strip() for c in tiers.columns]

    # Try to find county column
    county_col = None
    for c in tiers.columns:
        if str(c).strip().lower() in ("county", "county_name", "countyname"):
            county_col = c
            break
    if county_col is None:
        county_col = tiers.columns[0]  # fallback

    # MAO tier column
    tier_col = None
    for c in tiers.columns:
        if str(c).strip().lower() in ("mao tier", "mao_tier", "tier"):
            tier_col = c
            break

    # Range handling
    range_col = None
    for c in tiers.columns:
        if str(c).strip().lower() in ("mao range", "mao_range", "range"):
            range_col = c
            break

    min_col = None
    max_col = None
    for c in tiers.columns:
        lc = str(c).strip().lower()
        if lc in ("mao min", "mao_min", "min"):
            min_col = c
        if lc in ("mao max", "mao_max", "max"):
            max_col = c

    df = pd.DataFrame()
    df["County_clean_up"] = tiers[county_col].astype(str).str.strip().str.upper()
    df["County_key"] = df["County_clean_up"].apply(_normalize_county_key)
    df["MAO_Tier"] = tiers[tier_col].astype(str).str.strip() if tier_col else ""

    if range_col and range_col in tiers.columns:
        df["MAO_Range_Str"] = tiers[range_col].astype(str).str.strip()
    elif min_col and max_col and min_col in tiers.columns and max_col in tiers.columns:
        def fmt_pct(x):
            try:
                v = float(x)
                if v <= 1.0:
                    v *= 100.0
                return v
            except Exception:
                return None

        mins = tiers[min_col].apply(fmt_pct)
        maxs = tiers[max_col].apply(fmt_pct)

        def fmt_range(pair):
            lo, hi = pair
            if lo is None and hi is None:
                return ""
            if lo is None:
                return f"≤{hi:.0f}%"
            if hi is None:
                return f"≥{lo:.0f}%"
            return f"{lo:.0f}%–{hi:.0f}%"

        df["MAO_Range_Str"] = [fmt_range(x) for x in zip(mins, maxs)]
    else:
        df["MAO_Range_Str"] = ""

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

    # Canonical cleanup used throughout app
    df["County_clean_up"] = (
        df[C.county]
        .astype(str)
        .fillna("")
        .str.strip()
        .str.upper()
    )
    # Keep your historical fix
    df.loc[df["County_clean_up"] == "STEWART COUTY", "County_clean_up"] = "STEWART"

    # Robust join key for tiers merge ONLY
    df["County_key"] = df["County_clean_up"].apply(_normalize_county_key)

    # Needed by filters.py / momentum.py
    df["Status_norm"] = df[C.status].astype(str).str.lower().str.strip()
    df["Buyer_clean"] = df[C.buyer].astype(str).fillna("").astype(str).str.strip()

    # IMPORTANT: momentum.py expects Date_dt
    df["Date_dt"] = pd.to_datetime(df.get(C.date), errors="coerce")
    df["Year"] = df["Date_dt"].dt.year

    # Merge MAO tiers (do not crash app if tiers sheet has issues)
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
