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

        # Layout: Admin + Dispo have one extra control row slot
    if team_view in ["Admin", "Dispo"]:
        col1, col2, col3, col4, col5 = st.columns([1.0, 1.4, 1.4, 1.5, 1.3], gap="small")
    else:
        col1, col2, col3, col4 = st.columns([1.1, 1.6, 1.7, 1.4], gap="small")

    with col1:
        mode = st.radio("View", ["Sold", "Cut Loose", "Both"], index=0, horizontal=True)

    years_available = (
        sorted([int(y) for y in df["Year"].dropna().unique().tolist()]) if "Year" in df.columns else []
    )
    with col2:
        year_choice = st.selectbox("Year", ["All years"] + years_available + ["Last 12 months"], index=0)

    fd = prepare_filtered_data(df, year_choice)

    # Defaults
    buyer_choice = "All buyers"
    buyer_active = False

    rep_active = False
    dispo_rep_choice = "All reps"

    # NEW: Dispo acquisition rep filter defaults
    acq_rep_active = False
    dispo_acq_rep_choice = "All acquisition reps"

    market_choice = "All markets"
    acq_rep_choice = "All acquisition reps"
    dispo_rep_choice_admin = "All reps"

    if team_view == "Dispo":
        # Buyer filter
        with col3:
            if mode in ["Sold", "Both"]:
                labels, label_to_buyer = build_buyer_labels(fd.buyer_momentum, fd.buyers_plain)
                chosen_label = st.selectbox("Buyer", labels, index=0)
                buyer_choice = label_to_buyer[chosen_label]
            else:
                buyer_choice = "All buyers"
                st.selectbox("Buyer", ["All buyers"], disabled=True)

        buyer_active = buyer_choice != "All buyers" and mode in ["Sold", "Both"]

        # Dispo Rep filter
        with col4:
            rep_values: list[str] = []
            if mode in ["Sold", "Both"] and "Dispo_Rep_clean" in fd.df_time_sold.columns:
                rep_values = sorted(
                    [
                        r
                        for r in fd.df_time_sold["Dispo_Rep_clean"]
                        .dropna()
                        .astype(str)
                        .str.strip()
                        .unique()
                        .tolist()
                        if r
                    ]
                )

            options = ["All reps"] + rep_values
            saved = st.session_state.get("dispo_rep_choice", "All reps")
            idx = options.index(saved) if saved in options else 0

            dispo_rep_choice = st.selectbox(
                "Dispo rep",
                options,
                index=idx,
                disabled=(mode == "Cut Loose"),
                key="dispo_rep_choice",
            )

            rep_active = (dispo_rep_choice != "All reps") and (mode in ["Sold", "Both"])

        # NEW: Acquisition Rep filter (applies to sold + cut; doesn't depend on mode)
        with col5:
            acq_values: list[str] = []
            # Use the time-filtered frame (sold+cut together) so options reflect the current year filter
            if "Acquisition_Rep_clean" in fd.df_time_filtered.columns:
                acq_values = sorted(
                    [
                        r
                        for r in fd.df_time_filtered["Acquisition_Rep_clean"]
                        .dropna()
                        .astype(str)
                        .str.strip()
                        .unique()
                        .tolist()
                        if r
                    ]
                )

            acq_options = ["All acquisition reps"] + acq_values
            saved_acq = st.session_state.get("dispo_acq_rep_choice", "All acquisition reps")
            idx_acq = acq_options.index(saved_acq) if saved_acq in acq_options else 0

            dispo_acq_rep_choice = st.selectbox(
                "Acquisition rep",
                acq_options,
                index=idx_acq,
                key="dispo_acq_rep_choice",
            )

            acq_rep_active = dispo_acq_rep_choice != "All acquisition reps"

    elif team_view == "Admin":
        with col3:
            markets: list[str] = []
            if "Market_clean" in df.columns:
                markets = sorted(
                    [m for m in df["Market_clean"].dropna().astype(str).str.strip().unique().tolist() if m]
                )
            market_choice = st.selectbox("Market", ["All markets"] + markets, index=0)

        with col4:
            acq_reps: list[str] = []
            if "Acquisition_Rep_clean" in df.columns:
                acq_reps = sorted(
                    [r for r in df["Acquisition_Rep_clean"].dropna().astype(str).str.strip().unique().tolist() if r]
                )
            acq_rep_choice = st.selectbox("Acquisition Rep", ["All acquisition reps"] + acq_reps, index=0)

        with col5:
            dispo_reps: list[str] = []
            if "Dispo_Rep_clean" in df.columns:
                dispo_reps = sorted(
                    [r for r in df["Dispo_Rep_clean"].dropna().astype(str).str.strip().unique().tolist() if r]
                )
            dispo_rep_choice_admin = st.selectbox("Dispo rep", ["All reps"] + dispo_reps, index=0)

    else:
        # Acquisitions: show disabled buyer/rep to keep layout familiar
        with col3:
            st.selectbox("Buyer", ["All buyers"], disabled=True)
        with col4:
            st.selectbox("Dispo rep", ["All reps"], disabled=True, key="dispo_rep_choice")

    return ControlsResult(
        mode=mode,
        year_choice=year_choice,
        buyer_choice=buyer_choice,
        buyer_active=buyer_active,
        dispo_rep_choice=dispo_rep_choice,
        rep_active=rep_active,

        # NEW: Dispo acquisition rep filter return values
        dispo_acq_rep_choice=dispo_acq_rep_choice,
        acq_rep_active=acq_rep_active,

        market_choice=market_choice,
        acq_rep_choice=acq_rep_choice,
        dispo_rep_choice_admin=dispo_rep_choice_admin,
        fd=fd,
    )
