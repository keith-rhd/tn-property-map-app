"""controls.py

UI controls for the top filter row.
"""

from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
import streamlit as st

from filters import build_buyer_labels, prepare_filtered_data


@dataclass(frozen=True)
class ControlsResult:
    mode: str
    year_choice: object
    buyer_choice: str
    buyer_active: bool
    dispo_rep_choice: str
    rep_active: bool
    market_choice: str
    acq_rep_choice: str
    dispo_rep_choice_admin: str
    fd: object


def ensure_year_column(df: pd.DataFrame, date_col: str = "Date") -> pd.DataFrame:
    df = df.copy()

    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

    if "Year" not in df.columns and date_col in df.columns:
        df["Year"] = df[date_col].dt.year

    if "Year" in df.columns:
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")

    return df


def render_top_controls(*, team_view: str, df: pd.DataFrame) -> ControlsResult:
    df = ensure_year_column(df)

    # ---- COLUMN LAYOUT ----
    if team_view == "Admin":
        col1, col2, col3, col4, col5, col6 = st.columns(
            [1.0, 1.3, 1.6, 1.4, 1.4, 1.4], gap="small"
        )
    else:
        col1, col2, col3, col4 = st.columns([1.1, 1.6, 1.7, 1.4], gap="small")

    # ---- VIEW MODE ----
    with col1:
        mode = st.radio("View", ["Sold", "Cut Loose", "Both"], horizontal=True)

    # ---- YEAR SELECT ----
    years_available = (
        sorted([int(y) for y in df["Year"].dropna().unique().tolist()])
        if "Year" in df.columns
        else []
    )

    year_options = ["All years"] + years_available
    if team_view == "Admin":
        year_options = ["Rolling 12 months"] + year_options

    with col2:
        year_choice = st.selectbox("Year", year_options)

    fd = prepare_filtered_data(df, year_choice)

    # ---- DEFAULTS ----
    buyer_choice = "All buyers"
    buyer_active = False
    rep_active = False
    dispo_rep_choice = "All reps"

    market_choice = "All markets"
    acq_rep_choice = "All acquisition reps"
    dispo_rep_choice_admin = "All reps"

    # ---- DISPO VIEW ----
    if team_view == "Dispo":
        with col3:
            if mode in ["Sold", "Both"]:
                labels, label_to_buyer = build_buyer_labels(
                    fd.buyer_momentum, fd.buyers_plain
                )
                chosen = st.selectbox("Buyer", labels)
                buyer_choice = label_to_buyer.get(chosen, "All buyers")
                buyer_active = buyer_choice != "All buyers"

        with col4:
            reps = ["All reps"]
            if "Dispo_Rep_clean" in fd.df_time_sold.columns:
                reps += sorted(
                    r for r in fd.df_time_sold["Dispo_Rep_clean"].dropna().unique()
                    if str(r).strip()
                )
            dispo_rep_choice = st.selectbox("Dispo Rep (Sold)", reps)
            rep_active = dispo_rep_choice != "All reps"

    # ---- ADMIN VIEW (ALL ON ONE LINE) ----
    elif team_view == "Admin":
        with col3:
            if mode in ["Sold", "Both"]:
                labels, label_to_buyer = build_buyer_labels(
                    fd.buyer_momentum, fd.buyers_plain
                )
                chosen = st.selectbox("Buyer", labels)
                buyer_choice = label_to_buyer.get(chosen, "All buyers")
                buyer_active = buyer_choice != "All buyers"

        with col4:
            markets = ["All markets"]
            if "Market_clean" in df.columns:
                markets += sorted(
                    m for m in df["Market_clean"].dropna().unique()
                    if str(m).strip()
                )
            market_choice = st.selectbox("Market", markets)

        with col5:
            acq_reps = ["All acquisition reps"]
            if "Acq_Rep_clean" in df.columns:
                acq_reps += sorted(
                    r for r in df["Acq_Rep_clean"].dropna().unique()
                    if str(r).strip()
                )
            acq_rep_choice = st.selectbox("Acq Rep", acq_reps)

        with col6:
            dispo_reps = ["All reps"]
            if "Dispo_Rep_clean" in df.columns:
                dispo_reps += sorted(
                    r for r in df["Dispo_Rep_clean"].dropna().unique()
                    if str(r).strip()
                )
            dispo_rep_choice_admin = st.selectbox("Dispo Rep", dispo_reps)

    return ControlsResult(
        mode=mode,
        year_choice=year_choice,
        buyer_choice=buyer_choice,
        buyer_active=buyer_active,
        dispo_rep_choice=dispo_rep_choice,
        rep_active=rep_active,
        market_choice=market_choice,
        acq_rep_choice=acq_rep_choice,
        dispo_rep_choice_admin=dispo_rep_choice_admin,
        fd=fd,
    )
