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
        top_buyers[county] = list(zip(g_sorted["Buyer_clean"].tolist(), g_sorted["Count"].tolist()))
    return top_buyers

def build_county_properties_view(df_view: pd.DataFrame) -> Dict[str, list]:
    out = {}
    for _, row in df_view.iterrows():
        c = row["County_clean_up"]
        out.setdefault(c, []).append(
            {"Address": row["Address"], "City": row["City"], "SF_URL": row["Salesforce_URL"]}
        )
    return out

def enrich_geojson_properties(
    tn_geo: dict,
    *,
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
) -> dict:
    for feature in tn_geo["features"]:
        props = feature["properties"]
        county_name = str(props.get("NAME", "")).strip()
        name_up = county_name.upper()

        view_count = int(county_counts_view.get(name_up, 0))
        sold = int(sold_counts.get(name_up, 0))
        cut = int(cut_counts.get(name_up, 0))
        total = sold + cut

        close_str = f"{(sold/total)*100:.1f}%" if total > 0 else "N/A"
        buyer_sold = int(buyer_sold_counts.get(name_up, 0)) if buyer_active else 0

        props["NAME"] = county_name
        props["PROP_COUNT"] = view_count
        props["SOLD_COUNT"] = sold
        props["CUT_COUNT"] = cut
        props["TOTAL_COUNT"] = total
        props["CLOSE_RATE_STR"] = close_str
        props["BUYER_SOLD_COUNT"] = buyer_sold
        props["BUYER_NAME"] = buyer_choice

        top_list = top_buyers_dict.get(name_up, [])[: int(top_n_buyers)]
        top_buyers_html = ""
        if top_list and mode in ["Sold", "Both"]:
            top_buyers_html += "<div style='margin-top:6px; margin-bottom:6px;'>"
            top_buyers_html += "<b>Top buyers in this county:</b><br>"
            top_buyers_html += "<ol style='margin:4px 0 0 18px; padding:0;'>"
            for b, c in top_list:
                top_buyers_html += f"<li>{b} — {int(c)}</li>"
            top_buyers_html += "</ol></div>"

        lines = [
            f"<h4 style='margin-bottom:4px;'>{county_name} County</h4>",
            f"<span style='color:#2ca25f;'>●</span> <b>Sold:</b> {sold} &nbsp; "
            f"<span style='color:#cb181d;'>●</span> <b>Cut loose:</b> {cut}<br>",
            f"<b>Total:</b> {total} &nbsp; <b>Close rate:</b> {close_str}<br>",
        ]

        if buyer_active:
            lines.append(f"<b>{buyer_choice} (Sold):</b> {buyer_sold}<br>")

        if top_buyers_html:
            lines.append(top_buyers_html)

        props_list = county_properties_view.get(name_up, [])
        if props_list:
            lines.append('<div style="max-height: 130px; overflow-y: auto; margin-top: 2px; font-size: 13px;">')
            lines.append("<ul style='padding-left:18px; margin:0;'>")
            for p in props_list:
                addr = p["Address"]
                city = p["City"]
                url = p["SF_URL"]
                display_text = f"{addr}, {city}" if city else addr
                if isinstance(url, str) and url.strip():
                    lines.append(f'<li style="margin-bottom:2px;"><a href="{url}" target="_blank">{display_text}</a></li>')
                else:
                    lines.append(f"<li style='margin-bottom:2px;'>{display_text}</li>")
            lines.append("</ul></div>")

        props["POPUP_HTML"] = "\n".join(lines)

    return tn_geo
