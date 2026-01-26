"""controls.py

UI controls for the top filter row.

This module returns plain python values (mode/year/buyer/rep/market/etc.)
so the rest of the app can stay logic-focused.
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
    # Admin-only
    market_choice: str
    acq_rep_choice: str
    dispo_rep_choice_admin: str
    # Filtered data bundle
    fd: object


def ensure_year_column(df: pd.DataFrame, date_col: str = "Date") -> pd.DataFrame:
    """Ensure df has a numeric Year column and a parsed datetime Date column."""
    df = df.copy()

    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

    if "Year" not in df.columns and date_col in df.columns:
        df["Year"] = df[date_col].dt.year

    if "Year" in df.columns:
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")

    return df


def render_top_controls(*, team_view: str, df: pd.DataFrame) -> ControlsResult:
    """Render the row of controls at the top of the app.

    Returns the chosen values plus the prepared filtered-data bundle (fd).
    """

    df = ensure_year_column(df)

    # Layout: Admin has one extra control
    if team_view == "Admin":
        col1, col2, col3, col4, col5 = st.columns([1.0, 1.4, 1.4, 1.5, 1.3], gap="small")
    else:
        col1, col2, col3, col4 = st.columns([1.1, 1.6, 1.7, 1.4], gap="small")

    with col1:
        mode = st.radio("View", ["Sold", "Cut Loose", "Both"], index=0, horizontal=True)

    years_available = (
        sorted([int(y) for y in df["Year"].dropna().unique().tolist()]) if "Year" in df.columns else []
    )

    # Year selector:
    # - Everyone can choose a specific calendar year or "All years"
    # - Admins also get "Rolling 12 months" (relative to today)
    year_options = ["All years"] + years_available
    if team_view == "Admin":
        year_options = ["Rolling 12 months"] + year_options

    with col2:
        year_choice = st.selectbox("Year", year_options, index=0)

    fd = prepare_filtered_data(df, year_choice)

    # Defaults
    buyer_choice = "All buyers"
    buyer_active = False

    rep_active = False
    dispo_rep_choice = "All reps"

    market_choice = "All markets"
    acq_rep_choice = "All acquisition reps"
    dispo_rep_choice_admin = "All reps"

    if team_view == "Dispo":
        # Buyer filter
        with col3:
            if mode in ["Sold", "Both"]:
                labels, label_to_buyer = build_buyer_labels(fd.buyer_momentum, fd.buyers_plain)
                chosen_label = st.selectbox("Buyer", labels, index=0)
                buyer_choice = label_to_buyer.get(chosen_label, "All buyers")
                buyer_active = buyer_choice != "All buyers"

        # Rep filter (sold only)
        with col4:
            dispo_reps = ["All reps"]
            if "Dispo_Rep_clean" in fd.df_time_sold.columns:
                dispo_reps += sorted(
                    [
                        r
                        for r in fd.df_time_sold["Dispo_Rep_clean"].astype(str).fillna("").str.strip().unique().tolist()
                        if r
                    ]
                )
            dispo_rep_choice = st.selectbox("Dispo Rep (Sold only)", dispo_reps, index=0)
            rep_active = dispo_rep_choice != "All reps"

    elif team_view == "Acq":
        # Acq view uses buyer + county quick lookup in sidebar, no extra controls here.
        pass

    elif team_view == "Admin":
        # Admin controls: Buyer + Market + Reps
        with col3:
            if mode in ["Sold", "Both"]:
                labels, label_to_buyer = build_buyer_labels(fd.buyer_momentum, fd.buyers_plain)
                chosen_label = st.selectbox("Buyer", labels, index=0)
                buyer_choice = label_to_buyer.get(chosen_label, "All buyers")
                buyer_active = buyer_choice != "All buyers"

        with col4:
            market_vals = ["All markets"]
            if "Market_clean" in df.columns:
                market_vals += sorted([m for m in df["Market_clean"].astype(str).str.strip().unique().tolist() if m])
            market_choice = st.selectbox("Market", market_vals, index=0)

        with col5:
            # Stack two rep pickers vertically
            acq_vals = ["All acquisition reps"]
            if "Acq_Rep_clean" in df.columns:
                acq_vals += sorted([r for r in df["Acq_Rep_clean"].astype(str).str.strip().unique().tolist() if r])

            dispo_vals = ["All reps"]
            if "Dispo_Rep_clean" in df.columns:
                dispo_vals += sorted([r for r in df["Dispo_Rep_clean"].astype(str).str.strip().unique().tolist() if r])

            acq_rep_choice = st.selectbox("Acq Rep", acq_vals, index=0)
            dispo_rep_choice_admin = st.selectbox("Dispo Rep", dispo_vals, index=0)

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
