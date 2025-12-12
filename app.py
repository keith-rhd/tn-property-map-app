import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

st.set_page_config(page_title="TN Property Map", layout="wide")

SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTw_-UeODGJQFKDMVXM59CG45SrbADPQpyWcALENIDqT8SUhHFm1URYNP3aB6vudjzpM1mBFRio3rWi/pub?output=csv"


@st.cache_data(ttl=60)
def load_data():
    df = pd.read_csv(SHEET_URL)

    required_cols = {"Address", "City", "County", "Salesforce_URL"}
    missing = required_cols - set(df.columns)
    if missing:
        st.error(f"Missing required columns in sheet: {missing}")
        st.stop()

    if "Status" not in df.columns:
        df["Status"] = "Sold"
    df["Status"] = df["Status"].fillna("Sold")

    if "Buyer" not in df.columns:
        df["Buyer"] = ""
    df["Buyer"] = df["Buyer"].fillna("")

    df["County_clean"] = (
        df["County"].astype(str).str.replace(" County", "", case=False).str.strip()
    )
    df["County_clean_up"] = df["County_clean"].str.upper()
    df.loc[df["County_clean_up"] == "STEWART COUTY", "County_clean_up"] = "STEWART"

    df["Status_norm"] = df["Status"].astype(str).str.lower().str.strip()
    df["Buyer_clean"] = df["Buyer"].astype(str).str.strip()

    return df


df = load_data()

# -----------------------------
# Precompute totals (used by slider + close rate)
# -----------------------------
df_conv = df[df["Status_norm"].isin(["sold", "cut loose"])].copy()
grp_all = df_conv.groupby("County_clean_up")
sold_counts = grp_all.apply(lambda g: (g["Status_norm"] == "sold").sum())
cut_counts = grp_all.apply(lambda g: (g["Status_norm"] == "cut loose").sum())
total_counts = sold_counts + cut_counts
max_total = int(total_counts.max()) if len(total_counts) else 0

sold_counts_dict = sold_counts.to_dict()
cut_counts_dict = cut_counts.to_dict()

# -----------------------------
# UI CONTROLS (ONE ROW, RE-ORDERED)
#   Left: View + Hide filter
#   Right: Buyer + Top buyers
# -----------------------------
colL, colR = st.columns([2.6, 2.4], gap="small")
col1, col2 = colL.columns([1.2, 1.4], gap="small")
col3, col4 = colR.columns([1.6, 0.8], gap="small")

with col1:
    mode = st.radio(
        "View",
        ["Sold", "Cut Loose", "Both"],
        index=0,
        horizontal=True,
    )

with col2:
    min_total = st.slider(
        "Hide counties with < N total deals",
        min_value=0,
        max_value=max_total if max_total > 0 else 0,
        value=0,
        step=1,
    )

# Buyer selector (only meaningful if Sold is part of the view)
buyers = (
    df.loc[df["Status_norm"] == "sold", "Buyer_clean"]
    .astype(str)
    .str.strip()
)
buyers = sorted([b for b in buyers.unique().tolist() if b])

with col3:
    if mode in ["Sold", "Both"]:
        buyer_choice = st.selectbox(
            "Buyer",
            ["All buyers"] + buyers,
            index=0,
        )
    else:
        buyer_choice = "All buyers"
        st.selectbox("Buyer", ["All buyers"], index=0, disabled=True)

with col4:
    TOP_N = st.number_input("Top buyers", min_value=3, max_value=15, value=3, step=1)

buyer_active = (buyer_choice != "All buyers") and (mode in ["Sold", "Both"])

# Buyer-specific sold counts by county (for highlighting + stats)
buyer_sold_counts_dict = {}
if buyer_active:
    df_buyer_sold = df[
        (df["Status_norm"] == "sold")
        & (df["Buyer_clean"] == buyer_choice)
    ]
    buyer_sold_counts_dict = df_buyer_sold.groupby("County_clean_up").size().to_dict()

# -----------------------------
# Top buyers by county (from SOLD data only)
# -----------------------------
df_sold_all = df[(df["Status_norm"] == "sold") & (df["Buyer_clean"] != "")].copy()

buyers_by_county = (
    df_sold_all.groupby(["County_clean_up", "Buyer_clean"])
    .size()
    .reset_index(name="Count")
)

top_buyers_dict = {}
for county, g in buyers_by_county.groupby("County_clean_up"):
    g_sorted = g.sort_values("Count", ascending=False)
    top_buyers_dict[county] = list(zip(g_sorted["Buyer_clean"].tolist(), g_sorted["Count"].tolist()))

# -----------------------------
# Choose rows included in the CURRENT VIEW (controls map counts + address list)
# Buyer filter affects SOLD rows only.
# -----------------------------
if mode == "Sold":
    df_view = df[df["Status_norm"] == "sold"].copy()
    if buyer_active:
        df_view = df_view[df_view["Buyer_clean"] == buyer_choice]
elif mode == "Cut Loose":
    df_view = df[df["Status_norm"] == "cut loose"].copy()
else:  # Both
    df_sold = df[df["Status_norm"] == "sold"].copy()
    if buyer_active:
        df_sold = df_sold[df_sold["Buyer_clean"] == buyer_choice]
    df_cut = df[df["Status_norm"] == "cut loose"].copy()
    df_view = pd.concat([df_sold, df_cut], ignore_index=True)

county_counts_view = df_view.groupby("County_clean_up").size().to_dict()

county_properties_view = {}
for _, row in df_view.iterrows():
    c = row["County_clean_up"]
    county_properties_view.setdefault(c, []).append(
        {"Address": row["Address"], "City": row["City"], "SF_URL": row["Salesforce_URL"]}
    )

# -----------------------------
# Load TN Counties GeoJSON (Plotly dataset filtered to TN)
# -----------------------------
@st.cache_data
def load_geojson():
    url = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    tn_features = [
        f for f in data["features"]
        if f.get("properties", {}).get("STATE") == "47"
    ]
    return {"type": "FeatureCollection", "features": tn_features}


tn_geo = load_geojson()

# -----------------------------
# Color scales by mode (darker when buyer filter active)
# -----------------------------
def category_color(v: int, mode_: str, buyer_active_: bool = False) -> str:
    if v == 0:
        return "#FFFFFF"

    if mode_ == "Sold":
        if buyer_active_:
            if v == 1: return "#c7e9c0"
            if 2 <= v <= 5: return "#74c476"
            if 6 <= v <= 10: return "#31a354"
            return "#006d2c"
        else:
            if v == 1: return "#e5f5e0"
            if 2 <= v <= 5: return "#a1d99b"
            if 6 <= v <= 10: return "#41ab5d"
            return "#006d2c"

    if mode_ == "Cut Loose":
        if v == 1: return "#fee5d9"
        if 2 <= v <= 5: return "#fcae91"
        if 6 <= v <= 10: return "#fb6a4a"
        return "#cb181d"

    if v == 1: return "#deebf7"
    if 2 <= v <= 5: return "#9ecae1"
    if 6 <= v <= 10: return "#4292c6"
    return "#084594"

# -----------------------------
# Enrich geojson properties (counts, close rate, popup html)
# -----------------------------
for feature in tn_geo["features"]:
    props = feature["properties"]
    county_name = str(props.get("NAME", "")).strip()
    name_up = county_name.upper()

    view_count = int(county_counts_view.get(name_up, 0))

    sold = int(sold_counts_dict.get(name_up, 0))
    cut = int(cut_counts_dict.get(name_up, 0))
    total = sold + cut

    close_str = f"{(sold/total)*100:.1f}%" if total > 0 else "N/A"

    buyer_sold = int(buyer_sold_counts_dict.get(name_up, 0)) if buyer_active else 0

    props["NAME"] = county_name
    props["PROP_COUNT"] = view_count
    props["SOLD_COUNT"] = sold
    props["CUT_COUNT"] = cut
    props["TOTAL_COUNT"] = total
    props["CLOSE_RATE_STR"] = close_str
    props["BUYER_SOLD_COUNT"] = buyer_sold
    props["BUYER_NAME"] = buyer_choice

    # ---- Top buyers block (Sold only) ----
    top_list = top_buyers_dict.get(name_up, [])[: int(TOP_N)]

    top_buyers_html = ""
    if top_list and mode in ["Sold", "Both"]:
        top_buyers_html += "<div style='margin-top:6px; margin-bottom:6px;'>"
        top_buyers_html += "<b>Top buyers in this county:</b><br>"
        top_buyers_html += "<ol style='margin:4px 0 0 18px; padding:0;'>"
        for b, c in top_list:
            top_buyers_html += f"<li>{b} — {int(c)}</li>"
        top_buyers_html += "</ol></div>"

    # Popup HTML (condensed)
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
        # Smaller list window (~5 items) but scrollable
        lines.append(
            '<div style="max-height: 130px; overflow-y: auto; margin-top: 2px; font-size: 13px;">'
        )
        lines.append("<ul style='padding-left:18px; margin:0;'>")
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

# -----------------------------
# Build folium map
# -----------------------------
center_lat, center_lon = 35.8, -86.4
m = folium.Map(location=[center_lat, center_lon], zoom_start=7, tiles="cartodbpositron")

def style_function(feature):
    p = feature["properties"]
    total = p.get("TOTAL_COUNT", 0)

    if total < min_total:
        return {"fillColor": "#FFFFFF", "color": "black", "weight": 0.5, "fillOpacity": 0.15}

    if buyer_active and p.get("BUYER_SOLD_COUNT", 0) == 0:
        return {"fillColor": "#FFFFFF", "color": "black", "weight": 0.5, "fillOpacity": 0.15}

    v_for_color = p.get("BUYER_SOLD_COUNT", 0) if buyer_active else p.get("PROP_COUNT", 0)

    return {
        "fillColor": category_color(v_for_color, mode, buyer_active),
        "color": "black",
        "weight": 0.5,
        "fillOpacity": 0.9,
    }

tooltip_fields = ["NAME", "SOLD_COUNT", "CUT_COUNT", "TOTAL_COUNT", "CLOSE_RATE_STR"]
tooltip_aliases = ["County:", "Sold:", "Cut loose:", "Total:", "Close rate:"]

if buyer_active:
    tooltip_fields.append("BUYER_SOLD_COUNT")
    tooltip_aliases.append(f"{buyer_choice} (Sold):")

tooltip = folium.GeoJsonTooltip(
    fields=tooltip_fields,
    aliases=tooltip_aliases,
    localize=True,
    sticky=False,
)

folium.GeoJson(
    tn_geo,
    name="TN Counties",
    style_function=style_function,
    tooltip=tooltip,
    popup=folium.GeoJsonPopup(
        fields=["POPUP_HTML"],
        labels=False,
        localize=True,
        parse_html=True,
        max_width=420,
        style="""
            font-size: 13.5px;
            line-height: 1.2;
            padding: 3px;
        """,
    ),
).add_to(m)

legend_html = f"""
<div style="
    position: fixed;
    bottom: 10px;
    left: 50%;
    transform: translateX(-50%);
    background-color: rgba(255,255,255,0.85);
    color: black;
    z-index: 9999;
    font-size: 13px;
    padding: 6px 14px;
    border-radius: 6px;
    border: 1px solid #888;
    display: flex;
    gap: 14px;
    align-items: center;
">
    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:{category_color(1, mode, buyer_active)}; border:1px solid #000;"></div> 1
    </span>
    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:{category_color(2, mode, buyer_active)}; border:1px solid #000;"></div> 2–5
    </span>
    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:{category_color(6, mode, buyer_active)}; border:1px solid #000;"></div> 6–10
    </span>
    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:{category_color(11, mode, buyer_active)}; border:1px solid #000;"></div> >10
    </span>
    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:#FFFFFF; border:1px solid #000;"></div> 0 / hidden
    </span>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

st.title("Closed RHD Properties Map")
st_folium(m, width=1700, height=630)
