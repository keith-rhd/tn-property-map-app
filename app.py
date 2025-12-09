import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium

st.set_page_config(page_title="TN Property Map", layout="wide")

# -----------------------------
# 1. LOAD LIVE DATA FROM GOOGLE SHEET
# -----------------------------

SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTw_-UeODGJQFKDMVXM59CG45SrbADPQpyWcALENIDqT8SUhHFm1URYNP3aB6vudjzpM1mBFRio3rWi/pub?output=csv"


@st.cache_data(ttl=60)
def load_data():
    df = pd.read_csv(SHEET_URL)

    # Must have these columns
    required_cols = {"Address", "City", "County", "Salesforce_URL"}
    missing = required_cols - set(df.columns)
    if missing:
        st.error(f"Missing required columns in sheet: {missing}")
        st.stop()

    # Status: if missing, treat as Sold
    if "Status" not in df.columns:
        df["Status"] = "Sold"
    else:
        df["Status"] = df["Status"].fillna("Sold")

    # Normalize county names
    df["County_clean"] = (
        df["County"]
        .astype(str)
        .str.replace(" County", "", case=False)
        .str.strip()
    )
    df["County_clean_up"] = df["County_clean"].str.upper()

    # Fix known typo if it appears
    df.loc[df["County_clean_up"] == "STEWART COUTY", "County_clean_up"] = "STEWART"

    return df


df = load_data()

# -----------------------------
# 2. UI TOGGLE: SOLD vs CUT LOOSE vs BOTH
# -----------------------------

mode = st.radio(
    "Which properties do you want to view?",
    ["Sold", "Cut Loose", "Both"],
    index=0,
    horizontal=True,
)

if mode == "Both":
    df_use = df.copy()
else:
    df_use = df[df["Status"].str.lower() == mode.lower()].copy()

# -----------------------------
# 3. LOAD TN COUNTY GEOJSON FROM WEB (PLOTLY DATASET)
# -----------------------------


@st.cache_data
def load_geojson():
    # Full US counties GeoJSON from Plotly, then filter to Tennessee (STATE == "47")
    url = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()

    tn_features = [
        f
        for f in data["features"]
        if f.get("properties", {}).get("STATE") == "47"
    ]

    return {
        "type": "FeatureCollection",
        "features": tn_features,
    }


tn_geo = load_geojson()

# -----------------------------
# 4. BUILD COUNTY PROPERTY COUNTS + LISTS (BASED ON FILTERED DATA)
# -----------------------------

county_counts = df_use.groupby("County_clean_up").size().to_dict()

county_properties = {}
for _, row in df_use.iterrows():
    c = row["County_clean_up"]
    county_properties.setdefault(c, []).append(
        {
            "Address": row["Address"],
            "City": row["City"],
            "SF_URL": row["Salesforce_URL"],
        }
    )

# -----------------------------
# 5. COMPUTE CONVERSION RATES PER COUNTY (FROM FULL DATA)
# -----------------------------

df_conv = df.copy()
df_conv["Status_norm"] = df_conv["Status"].str.lower().str.strip()
mask = df_conv["Status_norm"].isin(["sold", "cut loose"])
df_conv = df_conv[mask].copy()

grp = df_conv.groupby("County_clean_up")

sold_counts = grp.apply(lambda g: (g["Status_norm"] == "sold").sum())
cut_counts = grp.apply(lambda g: (g["Status_norm"] == "cut loose").sum())
total_counts = sold_counts + cut_counts

conv_rate = sold_counts / total_counts.replace(0, pd.NA)  # fraction 0–1

# Dict: COUNTY -> conversion fraction (e.g., 0.73)
conversion_dict = conv_rate.to_dict()

# -----------------------------
# 6. ENRICH GEOJSON WITH PROP_COUNT + POPUP_HTML + CONVERSION
# -----------------------------

for feature in tn_geo["features"]:
    props = feature["properties"]

    # Plotly counties use NAME = county name (e.g., "Davidson")
    county_name = str(props.get("NAME", "")).strip()
    name_up = county_name.upper()

    count = county_counts.get(name_up, 0)
    props_list = county_properties.get(name_up, [])

    # Conversion
    conv_val = conversion_dict.get(name_up)
    if pd.notna(conv_val):
        conv_pct = float(conv_val * 100.0)
        conv_str = f"{conv_pct:.1f}%"
    else:
        conv_pct = None
        conv_str = "N/A"

    props["PROP_COUNT"] = int(count)
    props["CONVERSION"] = conv_pct
    props["CONVERSION_STR"] = conv_str

    # Build popup HTML: county, count, conversion, scrollable list of properties
    lines = [
        f"<h4>{county_name} County</h4>",
        f"<b>Properties {mode.lower()}:</b> {count}<br>",
        f"<b>Conversion:</b> {conv_str}<br>",
    ]

    if props_list:
        lines.append(
            '<div style="max-height: 260px; overflow-y: auto; margin-top: 4px;">'
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
                lines.append(
                    f"<li style='margin-bottom:2px;'>{display_text}</li>"
                )
        lines.append("</ul>")
        lines.append("</div>")

    props["POPUP_HTML"] = "\n".join(lines)
    # Ensure NAME exists for tooltip
    props["NAME"] = county_name

# -----------------------------
# 7. COLOR SCALES (DIFFERENT BY MODE)
# -----------------------------


def category_color(v: int, mode: str) -> str:
    """
    0 = white
    1 = light
    2–5 = medium
    6–10 = darker
    >10 = darkest

    Sold     -> green scheme
    Cut Loose-> red scheme
    Both     -> blue scheme
    """
    if v == 0:
        return "#FFFFFF"

    if mode == "Sold":
        # greens
        if v == 1:
            return "#e5f5e0"
        if 2 <= v <= 5:
            return "#a1d99b"
        if 6 <= v <= 10:
            return "#41ab5d"
        return "#006d2c"
    elif mode == "Cut Loose":
        # reds
        if v == 1:
            return "#fee5d9"
        if 2 <= v <= 5:
            return "#fcae91"
        if 6 <= v <= 10:
            return "#fb6a4a"
        return "#cb181d"
    else:
        # Both -> blue scheme
        if v == 1:
            return "#deebf7"
        if 2 <= v <= 5:
            return "#9ecae1"
        if 6 <= v <= 10:
            return "#4292c6"
        return "#084594"


# -----------------------------
# 8. BUILD THE FOLIUM MAP
# -----------------------------

center_lat, center_lon = 35.8, -86.4

m = folium.Map(location=[center_lat, center_lon], zoom_start=7, tiles="cartodbpositron")


def style_function(feature):
    v = feature["properties"].get("PROP_COUNT", 0)
    return {
        "fillColor": category_color(v, mode),
        "color": "black",
        "weight": 0.5,
        "fillOpacity": 0.9,
    }


folium.GeoJson(
    tn_geo,
    name="TN Counties",
    style_function=style_function,
    tooltip=folium.GeoJsonTooltip(
        fields=["NAME", "PROP_COUNT", "CONVERSION_STR"],
        aliases=["County:", "Properties:", "Conversion:"],
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
# 9. ADD LEGEND (MODE-AWARE, NO WATERMARK)
# -----------------------------

if mode == "Sold":
    legend_title = "Sold properties"
elif mode == "Cut Loose":
    legend_title = "Cut loose properties"
else:
    legend_title = "Total properties"

legend_html = f"""
<div style="
    position: fixed; 
    bottom: 80px; left: 30px; 
    width: 230px; height: 170px; 
    background-color: white; 
    color: black;
    z-index:9999; font-size:14px;
    border:2px solid grey; 
    border-radius:8px; 
    padding:10px;">
<b>Legend – {legend_title}</b><br>
<span style="background:{category_color(1, mode)}; border:1px solid #000; padding:2px 12px;"></span> 1 property<br>
<span style="background:{category_color(2, mode)}; border:1px solid #000; padding:2px 12px;"></span> 2–5 properties<br>
<span style="background:{category_color(6, mode)}; border:1px solid #000; padding:2px 12px;"></span> 6–10 properties<br>
<span style="background:{category_color(11, mode)}; border:1px solid #000; padding:2px 12px;"></span> >10 properties<br>
<span style="background:#FFFFFF; border:1px solid #000; padding:2px 12px;"></span> 0 properties
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

# -----------------------------
# 10. DISPLAY MAP IN STREAMLIT
# -----------------------------

st.title("Tennessee Property Acquisition Map")
st.write("This map pulls live data from your Google Sheet.")

st_folium(m, width=900, height=650)
