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
    Normalize county strings into a robust join key:
      - upper
      - strip
      - remove 'COUNTY'
      - keep letters only
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
    df = _read_csv(MAO_TIERS_URL).copy()

    if "County" not in df.columns:
        # allow alternate casing
        for col in df.columns:
            if str(col).strip().lower() == "county":
                df = df.rename(columns={col: "County"})
                break

    # Basic hardening
    df["County_clean_up"] = df.get("County", "").astype(str).str.strip()
    df["County_key"] = df["County_clean_up"].apply(_normalize_county_key)

    # Tier
    tier_col = None
    for c in df.columns:
        if str(c).strip().lower() in ("mao tier", "tier", "maotier"):
            tier_col = c
            break
    if tier_col is None:
        df["MAO_Tier"] = ""
    else:
        df["MAO_Tier"] = df[tier_col].astype(str).str.strip()

    # Range string
    range_col = None
    for c in df.columns:
        if str(c).strip().lower() in ("mao range", "range", "maorange"):
            range_col = c
            break

    if range_col:
        df["MAO_Range_Str"] = df[range_col].astype(str).str.strip()
    else:
        # Build from min/max if present
        min_col = None
        max_col = None
        for c in df.columns:
            lc = str(c).strip().lower()
            if lc in ("mao min", "min", "maomin"):
                min_col = c
            if lc in ("mao max", "max", "maomax"):
                max_col = c

        def _fmt_pct(x):
            try:
                v = float(x)
                if v <= 1.5:  # treat as decimal (0.73)
                    v *= 100.0
                return f"{v:.0f}%"
            except Exception:
                return ""

        if min_col and max_col:
            df["MAO_Range_Str"] = df.apply(
                lambda r: f"{_fmt_pct(r[min_col])}–{_fmt_pct(r[max_col])}".strip("–"),
                axis=1,
            )
        else:
            df["MAO_Range_Str"] = ""

    return df[["County_clean_up", "County_key", "MAO_Tier", "MAO_Range_Str"]].copy()


@st.cache_data(ttl=300, show_spinner=False)
def load_data() -> pd.DataFrame:
    """
    Load main Closed/Cut Loose sheet data and return a hardened dataframe.
    Ensures REQUIRED_COLS exist and standardizes County values.
    Also merges in MAO tiers (best effort).
    """
    df = _read_csv(SHEET_URL).copy()

    # ensure expected columns exist
    for col in REQUIRED_COLS:
        if col not in df.columns:
            df[col] = ""

    # normalize datatypes
    df["County_clean_up"] = df["County"].astype(str).str.strip()
    df["County_key"] = df["County_clean_up"].apply(_normalize_county_key)

    # Clean status
    df["Status_norm"] = df["Status"].astype(str).str.strip().str.title()

    # Parse Date (best effort)
    try:
        df["Date_parsed"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Year"] = df["Date_parsed"].dt.year.fillna(0).astype(int)
    except Exception:
        df["Date_parsed"] = pd.NaT
        df["Year"] = 0

    # Merge in tiers
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
