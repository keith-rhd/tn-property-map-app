import pandas as pd

from services.controller_services import compute_sold_cut_counts
from calculator_logic import compute_feasibility


def test_dispo_rep_filter_applies_to_sold_and_cut():
    df_sold = pd.DataFrame(
        {
            "County_clean_up": ["DAVIDSON", "DAVIDSON", "SHELBY"],
            "Status_norm": ["sold", "sold", "sold"],
            "Dispo_Rep_clean": ["ALICE", "BOB", "ALICE"],
        }
    )

    df_cut = pd.DataFrame(
        {
            "County_clean_up": ["DAVIDSON", "DAVIDSON", "SHELBY"],
            "Status_norm": ["cut loose", "cut loose", "cut loose"],
            "Dispo_Rep_clean": ["ALICE", "BOB", "ALICE"],
        }
    )

    sold_counts, cut_counts = compute_sold_cut_counts(
        df_sold,
        df_cut,
        team_view="Dispo",
        rep_active=True,
        dispo_rep_choice="ALICE",
    )

    assert sold_counts.get("DAVIDSON", 0) == 1
    assert cut_counts.get("DAVIDSON", 0) == 1
    assert sold_counts.get("SHELBY", 0) == 1
    assert cut_counts.get("SHELBY", 0) == 1


def test_compute_feasibility_support_fallback_uses_neighbors():
    # County has low/no data, neighbors have data
    df_sold = pd.DataFrame(
        {
            "County_clean_up": ["NEIGHBOR1", "NEIGHBOR1", "NEIGHBOR2"],
            "County": ["NEIGHBOR1", "NEIGHBOR1", "NEIGHBOR2"],
            "Effective_Contract_Price": [100000, 110000, 120000],
        }
    )
    df_cut = pd.DataFrame(
        {
            "County_clean_up": ["NEIGHBOR1"],
            "County": ["NEIGHBOR1"],
            "Effective_Contract_Price": [130000],
        }
    )
    adjacency = {"TARGET": ["NEIGHBOR1", "NEIGHBOR2"], "NEIGHBOR1": ["TARGET"], "NEIGHBOR2": ["TARGET"]}

    result = compute_feasibility(
        county_key="TARGET",
        input_price=115000,
        df_time_sold_for_view=df_sold,
        df_time_cut_for_view=df_cut,
        adjacency=adjacency,
    )

    assert result["support"]["used"] is True
    assert result["support"]["label"] in ("Nearby counties", "Statewide")
    assert result["support"]["n"] > 0
