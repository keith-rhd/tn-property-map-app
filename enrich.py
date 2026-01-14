# enrich.py
from __future__ import annotations

import re
from typing import Dict, List, Tuple

import pandas as pd


def build_top_buyers_dict(df_time_sold: pd.DataFrame) -> Dict[str, List[Tuple[str, int]]]:
    """Top buyers per county (sold only)."""
    df_sold_all = df_time_sold[df_time_sold["Buyer_clean"] != ""].copy()

    buyers_by_county = (
        df_sold_all.groupby(["County_clean_up", "Buyer_clean"])
        .size()
        .reset_index(name="Count")
    )

    top_buyers: Dict[str, List[Tuple[str, int]]] = {}
    for county, g in buyers_by_county.groupby("County_clean_up"):
        g_sorted = g.sort_values("Count", ascending=False)
        top_buyers[county] = list(
            zip(g_sorted["Buyer_clean"].tolist(), g_sorted["Count"].tolist())
        )

    return top_buyers


def build_county_properties_view(df_view: pd.DataFrame) -> Dict[str, list]:
    """Properties currently in view (based on mode/year/buyer filters) grouped by county."""
    out: Dict[str, list] = {}
    for _, row in df_view.iterrows():
        c = row["County_clean_up"]
        out.setdefault(c, []).append(
            {
                "Address": row.get("Address", ""),
                "City": row.get("City", ""),
                "SF_URL": row.get("Salesforce_URL", ""),
                "Status": row.get("Status", ""),
                "Buyer": row.get("Buyer_clean", row.get("Buyer", "")),
                "Date": row.get("Date", ""),
            }
        )
    return out


# -----------------------------
# Phase B2: Split map enrichment
# -----------------------------

def _apply_common_props(
    props: dict,
    *,
    name_up: str,
    county_counts_view: Dict[str, int],
    sold_counts: Dict[str, int],
    cut_counts: Dict[str, int],
) -> None:
    sold = int(sold_counts.get(name_up, 0))
    cut = int(cut_counts.get(name_up, 0))
    total = sold + cut

    close_rate = (sold / total) if total > 0 else None
    close_rate_str = f"{close_rate*100:.1f}%" if close_rate is not None else "N/A"

    props["SOLD_COUNT"] = sold
    props["CUT_COUNT"] = cut
    props["TOTAL_COUNT"] = total
    props["CLOSE_RATE_STR"] = close_rate_str

    # Counts in *current* view (mode/year/buyer filters)
    props["PROP_COUNT"] = int(county_counts_view.get(name_up, 0))


def enrich_geojson_dispo(
    tn_geo: dict,
    *,
    buyer_active: bool,
    buyer_choice: str,
    county_counts_view: Dict[str, int],
    sold_counts: Dict[str, int],
    cut_counts: Dict[str, int],
    buyer_sold_counts: Dict[str, int],
    buyer_count_by_county: Dict[str, int],
    mao_tier_by_county: Dict[str, str],   # kept for compatibility (can be blank)
    mao_range_by_county: Dict[str, str],  # kept for compatibility (can be blank)
) -> dict:
    """Dispo enrichment: focuses on activity + buyer filter counts.
    (We still attach MAO props if present, but they’re not required for Dispo coloring.)
    """
    for feature in tn_geo.get("features", []):
        props = feature.get("properties", {})
        name = str(props.get("NAME", "")).strip()
        name_up = name.upper()

        _apply_common_props(
            props,
            name_up=name_up,
            county_counts_view=county_counts_view,
            sold_counts=sold_counts,
            cut_counts=cut_counts,
        )

        # buyer counts (sold only, all buyers)
        props["BUYER_COUNT"] = int(buyer_count_by_county.get(name_up, 0))

        # buyer specific sold counts (only meaningful when a buyer filter is active)
        buyer_sold = int(buyer_sold_counts.get(name_up, 0)) if buyer_active else 0
        props["BUYER_SOLD_COUNT"] = buyer_sold

        # MAO fields (allowed to be blank; harmless for Dispo)
        props["MAO_TIER"] = str(mao_tier_by_county.get(name_up, "")) or ""
        props["MAO_RANGE"] = str(mao_range_by_county.get(name_up, "")) or ""
        props["MAO_MIN_PCT"] = ""  # Dispo doesn’t need MAO coloring

        # Popup HTML (short)
        sold = int(props.get("SOLD_COUNT", 0))
        cut = int(props.get("CUT_COUNT", 0))
        total = int(props.get("TOTAL_COUNT", 0))
        close_rate_str = str(props.get("CLOSE_RATE_STR", "N/A"))

        lines: List[str] = [
            f"<div style='font-size:14px;'><b>{name.title()} County</b></div>",
            "<div style='margin-top:4px;'>",
            f"<span style='color:#238b45;'>●</span> <b>Sold:</b> {sold} &nbsp; ",
            f"<span style='color:#cb181d;'>●</span> <b>Cut loose:</b> {cut}<br>",
            f"<b>Total:</b> {total} &nbsp; <b>Close rate:</b> {close_rate_str}<br>",
            "</div>",
        ]

        if buyer_active:
            lines.append(
                f"<div style='margin-top:6px;'><b>{buyer_choice} (Sold):</b> {buyer_sold}</div>"
            )

        lines.append(
            "<div style='margin-top:8px; font-size:12.5px; opacity:0.85;'>"
            "Tip: click a county to see full details below the map."
            "</div>"
        )

        props["POPUP_HTML"] = "\n".join(lines)

    return tn_geo


def enrich_geojson_acq(
    tn_geo: dict,
    *,
    county_counts_view: Dict[str, int],
    sold_counts: Dict[str, int],
    cut_counts: Dict[str, int],
    mao_tier_by_county: Dict[str, str],
    mao_range_by_county: Dict[str, str],
    buyer_count_by_county: Dict[str, int],
) -> dict:
    """Acquisitions enrichment: focuses on MAO tier/range + MAO coloring + buyer activity."""
    for feature in tn_geo.get("features", []):
        props = feature.get("properties", {})
        name = str(props.get("NAME", "")).strip()
        name_up = name.upper()

        _apply_common_props(
            props,
            name_up=name_up,
            county_counts_view=county_counts_view,
            sold_counts=sold_counts,
            cut_counts=cut_counts,
        )

        # MAO tier + range
        props["MAO_TIER"] = str(mao_tier_by_county.get(name_up, "")) or ""
        props["MAO_RANGE"] = str(mao_range_by_county.get(name_up, "")) or ""

        # for MAO map coloring: parse a "min" from MAO range
        mn_val = None
        rng = (props.get("MAO_RANGE") or "").strip()
        if rng:
            # examples: "73%–77%", "73%-77%", "0.73–0.77", "0.73-0.77"
            m_num = re.search(r"(\d+(?:\.\d+)?)", rng)
            if m_num:
                try:
                    x = float(m_num.group(1))
                    mn_val = x / 100.0 if x > 1.5 else x
                except Exception:
                    mn_val = None
        props["MAO_MIN_PCT"] = mn_val if mn_val is not None else ""

        # Buyer counts (sold only)
        props["BUYER_COUNT"] = int(buyer_count_by_county.get(name_up, 0))

        # Popup HTML (short)
        sold = int(props.get("SOLD_COUNT", 0))
        cut = int(props.get("CUT_COUNT", 0))
        total = int(props.get("TOTAL_COUNT", 0))
        close_rate_str = str(props.get("CLOSE_RATE_STR", "N/A"))
        mao_tier = props.get("MAO_TIER", "")
        mao_range = props.get("MAO_RANGE", "")

        lines: List[str] = [
            f"<div style='font-size:14px;'><b>{name.title()} County</b></div>",
            "<div style='margin-top:4px;'>",
            f"<span style='color:#238b45;'>●</span> <b>Sold:</b> {sold} &nbsp; ",
            f"<span style='color:#cb181d;'>●</span> <b>Cut loose:</b> {cut}<br>",
            f"<b>Total:</b> {total} &nbsp; <b>Close rate:</b> {close_rate_str}<br>",
            "</div>",
        ]

        if mao_tier or mao_range:
            label = (
                f"{mao_tier} ({mao_range})"
                if mao_tier and mao_range
                else (mao_tier or mao_range)
            )
            lines.append(f"<div style='margin-top:6px;'><b>MAO Tier:</b> {label}</div>")

        lines.append(
            f"<div style='margin-top:4px;'><b># Buyers:</b> {int(props.get('BUYER_COUNT', 0))}</div>"
        )

        lines.append(
            "<div style='margin-top:8px; font-size:12.5px; opacity:0.85;'>"
            "Tip: click a county to see full details below the map."
            "</div>"
        )

        props["POPUP_HTML"] = "\n".join(lines)

    return tn_geo


def enrich_geojson_properties(
    tn_geo: dict,
    *,
    team_view: str,
    mode: str,
    buyer_active: bool,
    buyer_choice: str,
    top_n_buyers: int,
    county_counts_view: Dict[str, int],
    sold_counts: Dict[str, int],
    cut_counts: Dict[str, int],
    buyer_sold_counts: Dict[str, int],
    top_buyers_dict: Dict[str, List[Tuple[str, int]]],
    county_properties_view: Dict[str, list],
    mao_tier_by_county: Dict[str, str],
    mao_range_by_county: Dict[str, str],
    buyer_count_by_county: Dict[str, int],
) -> dict:
    """Backward-compatible wrapper.
    Routes to the correct enrichment based on team_view.
    """
    team_view_norm = (team_view or "").strip().lower()

    if team_view_norm == "acquisitions":
        return enrich_geojson_acq(
            tn_geo,
            county_counts_view=county_counts_view,
            sold_counts=sold_counts,
            cut_counts=cut_counts,
            mao_tier_by_county=mao_tier_by_county,
            mao_range_by_county=mao_range_by_county,
            buyer_count_by_county=buyer_count_by_county,
        )

    # Default to Dispo behavior
    return enrich_geojson_dispo(
        tn_geo,
        buyer_active=buyer_active,
        buyer_choice=buyer_choice,
        county_counts_view=county_counts_view,
        sold_counts=sold_counts,
        cut_counts=cut_counts,
        buyer_sold_counts=buyer_sold_counts,
        buyer_count_by_county=buyer_count_by_county,
        mao_tier_by_county=mao_tier_by_county,
        mao_range_by_county=mao_range_by_county,
    )
