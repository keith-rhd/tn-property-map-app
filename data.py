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
    Robust join key for county names.
    - upper
    - strip spaces
    - remove word COUNTY
    - keep only letters
    """
    if x is None:
        return ""
    s = str(x).upper().strip()
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
        # Best effort fallback: first column
        county_col = tiers.columns[0]

    # MAO tier column
    tier_col = None
    for c in tiers.columns:
        if str(c).strip().lower() in ("mao tier", "mao_tier", "tier"):
            tier_col = c
            break
    if tier_col is None:
        tier_col = "MAO Tier" if "MAO Tier" in tiers.columns else None

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

    # Build output dataframe
    df = pd.DataFrame()
    df["County_clean_up"] = tiers[county_col].astype(str).str.strip().str.upper()
    df["County_key"] = df["County_clean_up"].apply(_normalize_county_key)
    df["MAO_Tier"] = tiers[tier_col].astype(str).str.strip() if tier_col else ""

    # Build MAO_Range_Str
    if range_col and range_col in tiers.columns:
        df["MAO_Range_Str"] = tiers[range_col].astype(str).str.strip()
    elif min_col and max_col and min_col in tiers.columns and max_col in tiers.columns:
        # Convert decimals to percents
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

        def fmt_range(row):
            lo, hi = row
            if lo is None and hi is None:
                return ""
            if lo is None:
                return f"≤{hi:.0f}%"
            if hi is None:
                return f"≥{lo:.0f}%"
            return f"{lo:.0f}%–{hi:.0f}%"

        df["MAO_Range_Str"] = list(map(fmt_range, zip(mins, maxs)))
    else:
        df["MAO_Range_Str"] = ""

    return df[out_cols]


@st.cache_data(ttl=300, show_spinner=False)
def load_data() -> pd.DataFrame:
    df = _read_csv(SHEET_URL)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Optional columns
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
    df.loc[df["County_clean_up"] == "STEWART COUTY", "County_clean_up"] = "STEWART"

    # NEW: robust join key (used only for merge)
    df["County_key"] = df["County_clean_up"].apply(_normalize_county_key)

    # Needed by filters.py / momentum.py
    df["Status_norm"] = df[C.status].astype(str).str.lower().str.strip()
    df["Buyer_clean"] = df[C.buyer].astype(str).str.strip()

    # Parse date (safe)
    df["Date_parsed"] = pd.to_datetime(df[C.date], errors="coerce")
    df["Year"] = df["Date_parsed"].dt.year

    # Merge MAO tiers (safe + robust)
    try:
        tiers = load_mao_tiers()
        if not tiers.empty:
            # merge on robust key, keep df's County_clean_up for display
            df = df.merge(
                tiers[["County_key", "MAO_Tier", "MAO_Range_Str"]],
                on="County_key",
                how="left",
            )
    except Exception:
        # don't break the app if the tiers sheet has issues
        df["MAO_Tier"] = ""
        df["MAO_Range_Str"] = ""

    return df
