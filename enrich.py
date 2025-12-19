# enrich.py
import pandas as pd
from typing import Dict, List, Tuple


def build_top_buyers_dict(df_time_sold: pd.DataFrame) -> Dict[str, List[Tuple[str, int]]]:
    df_sold_all = df_time_sold[df_time_sold["Buyer_clean"] != ""].copy()
    buyers_by_county = (
        df_sold_all.groupby(["County_clean_up", "Buyer_clean"])
        .size()
        .reset_index(name="Count")
    )
    top_buyers = {}
    for county, g in buyers_by_county.groupby("County_clean_up"):
        g_sorted = g.sort_values("Count", ascending=False)
        top_buyers[county] = list(
            zip(g_sorted["Buyer_clean"].tolist(), g_sorted["Count"].tolist())
        )
    return top_buyers


def build_county_properties_view(df_view: pd.DataFrame) -> Dict[str, list]:
    out: Dict[str, list] = {}
    for _, row in df_view.iterrows():
        c = row["County_clean_up"]
        out.setdefault(c, []).append(
            {
                "Address": row["Address"],
                "City": row["City"],
                "SF_URL": row["Salesforce_URL"],
            }
        )
    return out


def _parse_mao_range_to_min_max(range_str: str) -> tuple[float | None, float | None]:
    """
    Supports:
      - '75%–80%'
      - '75%+'
      - '≤80%'
      - ''
    Returns (min_pct, max_pct) as floats like 75.0
    """
    if not isinstance(range_str, str):
        return None, None

    s = range_str.strip()
    if not s:
        return None, None

    s = s.replace(" ", "")
    s = s.replace("–", "-")  # normalize dash

    # ≤80%
    if s.startswith("≤"):
        try:
            mx = float(s.replace("≤", "").replace("%", ""))
            return None, mx
        except Exception:
            return None, None

    # 75%+
    if s.endswith("+"):
        try:
            mn = float(s.replace("+", "").replace("%", ""))
            return mn, None
        except Exception:
            return None, None

    # 75%-80%
    if "-" in s:
        a, b = s.split("-", 1)
        try:
            mn = float(a.replace("%", ""))
            mx = float(b.replace("%", ""))
            return mn, mx
        except Exception:
            return None, None

    # single number '80%'
    try:
        val = float(s.replace("%", ""))
        return val, val
    except Exception:
        return None, None


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
    top_buyers_dict: Dict[str, list],
    county_properties_view: Dict[str, list],
    mao_tier_by_county: Dict[str, str] | None = None,
    mao_range_by_county: Dict[str, str] | None = None,
) -> dict:
    team_view_norm = (team_view or "Dispo").strip().lower()

    for feature in tn_geo["features"]:
        props = feature["properties"]
        county_name = str(props.get("NAME", "")).strip()
        name_up = county_name.upper()

        sold = int(sold_counts.get(name_up, 0))
        cut = int(cut_counts.get(name_up, 0))
        total = sold + cut

        close_rate_num = (sold / total) if total > 0 else 0.0
        close_rate_str = f"{close_rate_num * 100:.1f}%"

        # Tooltip-required keys
        props["SOLD_COUNT"] = sold
        props["CUT_COUNT"] = cut
        props["TOTAL_COUNT"] = total
        props["CLOSE_RATE_STR"] = close_rate_str

        # Used for default coloring in Dispo
        props["PROP_COUNT"] = int(county_counts_view.get(name_up, 0))

        # Buyer-specific sold count
        buyer_sold = int(buyer_sold_counts.get(name_up, 0))
        props["BUYER_SOLD_COUNT"] = buyer_sold

        # MAO keys (must exist even if blank)
        mao_tier = (mao_tier_by_county or {}).get(name_up, "") or ""
        mao_range = (mao_range_by_county or {}).get(name_up, "") or ""
        props["MAO_TIER"] = mao_tier
        props["MAO_RANGE"] = mao_range

        # NEW: numeric MAO min/max for coloring in acquisitions
        mn, mx = _parse_mao_range_to_min_max(mao_range)
        props["MAO_MIN_PCT"] = mn if mn is not None else ""
        props["MAO_MAX_PCT"] = mx if mx is not None else ""

        # -----------------------------
        # Popup HTML
        # -----------------------------
        lines = [
            f"<h4 style='margin-bottom:4px;'>{county_name} County</h4>",
            f"<span style='color:#2ca25f;'>●</span> <b>Sold:</b> {sold} &nbsp; "
            f"<span style='color:#cb181d;'>●</span> <b>Cut loose:</b> {cut}<br>",
            f"<b>Total:</b> {total} &nbsp; <b>Close rate:</b> {close_rate_str}<br>",
        ]

        if mao_tier or mao_range:
            label = (
                f"{mao_tier} ({mao_range})"
                if mao_tier and mao_range
                else (mao_tier or mao_range)
            )
            if team_view_norm == "acquisitions":
                lines.append(f"<div style='margin-top:6px;'><b>MAO Tier:</b> {label}</div>")
            else:
                lines.append(f"<b>MAO Tier:</b> {label}<br>")

        if team_view_norm == "dispo" and buyer_active:
            lines.append(f"<b>{buyer_choice} (Sold):</b> {buyer_sold}<br>")

        if team_view_norm == "dispo":
            top_list = (top_buyers_dict.get(name_up, []) or [])[: int(top_n_buyers)]
            if top_list:
                lines.append("<div style='margin-top:6px; margin-bottom:6px;'>")
                lines.append("<b>Top buyers in this county:</b><br>")
                lines.append("<ol style='margin:4px 0 0 18px; padding:0;'>")
                for b, c in top_list:
                    lines.append(f"<li>{b} — {int(c)}</li>")
                lines.append("</ol></div>")

        props_list = county_properties_view.get(name_up, [])
        if props_list:
            lines.append(
                '<div style="max-height: 240px; overflow-y: auto; margin-top: 6px; font-size: 13px;">'
            )
            lines.append("<b>Properties in view:</b>")
            lines.append("<ul style='padding-left:18px; margin:6px 0 0 0;'>")
            for p in props_list:
                addr = p["Address"]
                city = p["City"]
                url = p["SF_URL"]
                display_text = f"{addr}, {city}" if city else addr
                if isinstance(url, str) and url.strip():
                    lines.append(
                        f'<li style="margin-bottom:2px;"><a href="{url}" target="_blank">{display_text}</a></li>'
                    )
                else:
                    lines.append(f"<li style='margin-bottom:2px;'>{display_text}</li>")
            lines.append("</ul></div>")

        props["POPUP_HTML"] = "\n".join(lines)

    return tn_geo
