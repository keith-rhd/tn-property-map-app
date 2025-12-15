# data.py
import pandas as pd
import streamlit as st
from config import SHEET_URL, REQUIRED_COLS, C

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

    df["Status_norm"] = df[C.status].astype(str).str.lower().str.strip()
    df["Buyer_clean"] = df[C.buyer].astype(str).str.strip()

    return df
