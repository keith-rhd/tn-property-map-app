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
            {"Address": row["Address"], "City": row["City"], "SF_URL": row["Salesforce_URL"]}
        )
    return out


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
    """Attach computed values + popup HTML to each county feature."""

    team_view_norm = (team_view or "Dispo").strip().lower()

    for feature in tn_geo["features"]:
        props = feature["properties"]
        county_name = str(props.get("NAME", "")).strip()
        name_up = county_name.upper()

        sold = int(sold_counts.get(name_up, 0))
        cut = int(cut_counts.get(name_up, 0))
        total = sold + cut

        close_rate_num = (sold / total) if total > 0 else 0.0
        close_str = f"{close_rate_num * 100:.1f}%"

        # ---- REQUIRED for map_build.py tooltip fields ----
        props["SOLD_COUNT"] = sold
        props["CUT_COUNT"] = cut
        props["TOTAL_COUNT"] = total                  # ✅ FIX: was missing
        props["CLOSE_RATE"] = close_str               # show a nice % in tooltip
        # -------------------------------------------------

        # Used for coloring
        props["PROP_COUNT"] = int(county_counts_view.get(name_up, 0))

        # Buyer-specific sold count
        buyer_sold = int(buyer_sold_counts.get(name_up, 0))
        props["BUYER_SOLD_COUNT"] = buyer_sold

        # MAO info (can be blank)
        mao_tier = (mao_tier_by_county or {}).get(name_up, "") or ""
        mao_range = (mao_range_by_county or {}).get(name_up, "") or ""
        props["MAO_TIER"] = mao_tier
        props["MAO_RANGE"] = mao_range

        # Top buyers block (Dispo view only)
        top_buyers_html = ""
        if team_view_norm == "dispo":
            top_list = (top_buyers_dict.get(name_up, []) or [])[: int(top_n_buyers)]
            if top_list:
                top_buyers_html += "<div style='margin-top:6px; margin-bottom:6px;'>"
                top_buyers_html += "<b>Top buyers in this county:</b><br>"
                top_buyers_html += "<ol style='margin:4px 0 0 18px; padding:0;'>"
                for b, c in top_list:
                    top_buyers_html += f"<li>{b} — {int(c)}</li>"
                top_buyers_html += "</ol></div>"

        # Popup header + conversion
        lines = [
            f"<h4 style='margin-bottom:4px;'>{county_name} County</h4>",
            f"<span style='color:#2ca25f;'>●</span> <b>Sold:</b> {sold} &nbsp; "
            f"<span style='color:#cb181d;'>●</span> <b>Cut loose:</b> {cut}<br>",
            f"<b>Total:</b> {total} &nbsp; <b>Close rate:</b> {close_str}<br>",
        ]

        # MAO (always useful, but acquisitions emphasizes it)
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

        # Buyer-specific count (Dispo view only)
        if team_view_norm == "dispo" and buyer_active:
            lines.append(f"<b>{buyer_choice} (Sold):</b> {buyer_sold}<br>")

        if top_buyers_html:
            lines.append(top_buyers_html)

        # Property list (both views)
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
