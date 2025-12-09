import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import json

st.set_page_config(page_title="TN Property Map", layout="wide")

# -----------------------------
# 1. LOAD LIVE DATA FROM GOOGLE SHEET
# -----------------------------

SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTw_-UeODGJQFKDMVXM59CG45SrbADPQpyWcALENIDqT8SUhHFm1URYNP3aB6vudjzpM1mBFRio3rWi/pub?output=csv"

@st.cache_data(ttl=60)
def load_data():
    df = pd.read_csv(SHEET_URL)

    # Expecting columns: Address, City, County, Salesforce_URL
    required_cols = {"Address", "City", "County", "Salesforce_URL"}
    missing = required_cols - set(df.columns)
    if missing:
        st.error(f"Missing required columns in sheet: {missing}")
        st.stop()

    # Clean county names
    df["County_clean"] = (
        df["County"]
        .astype(str)
        .str.replace(" County", "", case=False)
        .str.strip()
    )
    df["County_clean_up"] = df["County_clean"].str.upper()

    # Fix typo if it appears
    df.loc[df["County_clean_up"] == "STEWART COUTY", "County_clean_up"] = "STEWART"

    return df

df = load_data()

# -----------------------------
# 2. LOAD TN COUNTY GEOJSON (LOCAL FILE)
# -----------------------------

@st.cache_data
def load_geojson():
    url = "https://eric.clst.org/assets/us/json/county/47.json"
    return requests.get(url).json()


# -----------------------------
# 3. BUILD COUNTY PROPERTY COUNTS + LISTS
# -----------------------------

county_counts = df.groupby("County_clean_up").size().to_dict()

county_properties = {}
for _, row in df.iterrows():
    c = row["County_clean_up"]
    county_properties.setdefault(c, []).append({
        "Address": row["Address"],
        "City": row["City"],
        "SF_URL": row["Salesforce_URL"],
    })

# -----------------------------
# 4. ADD POPUP HTML + PROP_COUNT TO EACH COUNTY
# -----------------------------

for feature in tn_geo["features"]:
    props = feature["properties"]
    name = props["NAME"]
    name_up = name.upper()

    count = county_counts.get(name_up, 0)
    props_list = county_properties.get(name_up, [])

    props["PROP_COUNT"] = int(count)

    lines = [
        f"<h4>{name} County</h4>",
        f"<b>Properties sold:</b> {count}<br>",
    ]

    # Scrollable list so big counties don't blow up the screen
    if props_list:
        lines.append('<div style="max-height: 260px; overflow-y: auto; margin-top: 4px;">')
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
        lines.append("</ul>")
        lines.append("</div>")

    props["POPUP_HTML"] = "\n".join(lines)

# -----------------------------
# 5. COLOR SCALE FUNCTION
# -----------------------------

def category_color(v: int) -> str:
    if v == 0:
        return "#FFFFFF"
    if v == 1:
        return "#ADD8E6"      # light blue
    if 2 <= v <= 5:
        return "#F4A6A6"      # light red
    if 6 <= v <= 10:
        return "#FFFACD"      # light yellow
    return "#90EE90"          # light green (>10)

# -----------------------------
# 6. BUILD THE FOLIUM MAP
# -----------------------------

# Compute center of TN
lats = [float(f["properties"]["INTPTLAT"]) for f in tn_geo["features"]]
lons = [float(f["properties"]["INTPTLON"]) for f in tn_geo["features"]]
center_lat = sum(lats) / len(lats)
center_lon = sum(lons) / len(lons)

m = folium.Map(location=[center_lat, center_lon], zoom_start=7, tiles="cartodbpositron")

def style_function(feature):
    v = feature["properties"].get("PROP_COUNT", 0)
    return {
        "fillColor": category_color(v),
        "color": "black",
        "weight": 0.5,
        "fillOpacity": 0.9,
    }

folium.GeoJson(
    tn_geo,
    name="TN Counties",
    style_function=style_function,
    tooltip=folium.GeoJsonTooltip(
        fields=["NAME", "PROP_COUNT"],
        aliases=["County:", "Properties sold:"],
        localize=True,
        sticky=False,
    ),
    popup=folium.GeoJsonPopup(
        fields=["POPUP_HTML"],
        labels=False,
        localize=True,
        parse_html=True,
        max_width=500,
    ),
).add_to(m)

# -----------------------------
# 7. ADD LEGEND + WATERMARK
# -----------------------------

legend_html = """
<div style="
    position: fixed; 
    bottom: 80px; left: 30px; 
    width: 210px; height: 170px; 
    background-color: white; 
    z-index:9999; font-size:14px;
    border:2px solid grey; 
    border-radius:8px; 
    padding:10px;">
<b>Legend</b><br>
<span style="background:#FFFFFF; border:1px solid #000; padding:2px 12px;"></span> 0 properties<br>
<span style="background:#ADD8E6; border:1px solid #000; padding:2px 12px;"></span> 1 property<br>
<span style="background:#F4A6A6; border:1px solid #000; padding:2px 12px;"></span> 2–5 properties<br>
<span style="background:#FFFACD; border:1px solid #000; padding:2px 12px;"></span> 6–10 properties<br>
<span style="background:#90EE90; border:1px solid #000; padding:2px 12px;"></span> &gt;10 properties
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

watermark_html = """
<div style="
    position: fixed;
    bottom: 35px; left: 30px;
    background-color: rgba(255,255,255,0.75);
    padding: 6px 12px;
    font-size: 14px;
    border-radius: 5px;
    z-index: 9999;
    border: 1px solid #888;
    font-weight: bold;">
Created by Keith Frislid
</div>
"""
m.get_root().html.add_child(folium.Element(watermark_html))

# -----------------------------
# 8. DISPLAY IN STREAMLIT
# -----------------------------

st.title("Tennessee Property Acquisition Map")
st.write("This map pulls live data from your Google Sheet.")

st_folium(m, width=900, height=650)
