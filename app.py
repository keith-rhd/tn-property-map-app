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

# -----------------------------
# 3. COMPUTE CLOSE RATE STATS (FROM FULL DATA)
# -----------------------------

df_conv = df.copy()
df_conv["Status_norm"] = df_conv["Status"].str.lower().str.strip()
mask = df_conv["Status_norm"].isin(["sold", "cut loose"])
df_conv = df_conv[mask].copy()

grp = df_conv.groupby("County_clean_up")
sold_counts = grp.apply(lambda g: (g["Status_norm"] == "sold").sum())
cut_counts = grp.apply(lambda g: (g["Status_norm"] == "cut loose").sum())
total_counts = sold_counts + cut_counts

# For slider: max total deals in any county
max_total = int(total_counts.max()) if len(total_counts) > 0 else 0

min_total = st.slider(
    "Show only counties with at least this many total deals (Sold + Cut Loose)",
    min_value=0,
    max_value=max_total if max_total > 0 else 0,
    value=0,
    step=1,
)

sold_counts_dict = sold_counts.to_dict()
cut_counts_dict = cut_counts.to_dict()

# -----------------------------
# 4. APPLY MODE FILTER TO DATA FOR CURRENT VIEW
# -----------------------------

if mode == "Both":
    df_use = df.copy()
else:
    df_use = df[df["Status"].str.lower() == mode.lower()].copy()

# -----------------------------
# 5. LOAD TN COUNTY GEOJSON FROM WEB (PLOTLY DATASET)
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
# 6. BUILD COUNTY PROPERTY COUNTS + LISTS (BASED ON FILTERED DATA)
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
# 7. ENRICH GEOJSON WITH COUNTS + CLOSE RATE + POPUP_HTML
# -----------------------------

for feature in tn_geo["features"]:
    props = feature["properties"]

    # Plotly counties use NAME = county name (e.g., "Davidson")
    county_name = str(props.get("NAME", "")).strip()
    name_up = county_name.upper()

    # Counts for current view ( Sold / Cut Loose / Both )
    view_count = county_counts.get(name_up, 0)

    # Sold / Cut Loose / Total from *all* data
    sold = int(sold_counts_dict.get(name_up, 0))
    cut = int(cut_counts_dict.get(name_up, 0))
    total = sold + cut

    # Close rate
    if total > 0:
        close_frac = sold / total
        close_pct = close_frac * 100.0
        close_str = f"{close_pct:.1f}%"
    else:
        close_frac = None
        close_str = "N/A"

    props["PROP_COUNT"] = int(view_count)
    props["SOLD_COUNT"] = sold
    props["CUT_COUNT"] = cut
    props["TOTAL_COUNT"] = total
    props["CLOSE_RATE"] = close_frac
    props["CLOSE_RATE_STR"] = close_str

    # Build popup HTML
    lines = [
        f"<h4>{county_name} County</h4>",
        f"<b>Sold:</b> {sold}<br>",
        f"<b>Cut loose:</b> {cut}<br>",
        f"<b>Total deals:</b> {total}<br>",
        f"<b>Close rate:</b> {close_str}<br>",
    ]

    props_list = county_properties.get(name_up, [])
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
    props["NAME"] = county_name  # ensure for tooltip

# -----------------------------
# 8. COLOR SCALES (DIFFERENT BY MODE)
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
# 9. BUILD THE FOLIUM MAP
# -----------------------------

center_lat, center_lon = 35.8, -86.4

m = folium.Map(location=[center_lat, center_lon], zoom_start=7, tiles="cartodbpositron")


def style_function(feature):
    props = feature["properties"]
    v = props.get("PROP_COUNT", 0)
    total = props.get("TOTAL_COUNT", 0)

    # Apply min_total filter: counties below threshold go white
    if total < min_total:
        return {
            "fillColor": "#FFFFFF",
            "color": "black",
            "weight": 0.5,
            "fillOpacity": 0.2,
        }

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
        fields=[
            "NAME",
            "PROP_COUNT",
            "SOLD_COUNT",
            "CUT_COUNT",
            "TOTAL_COUNT",
            "CLOSE_RATE_STR",
        ],
        aliases=[
            "County:",
            "Properties (current view):",
            "Sold:",
            "Cut loose:",
            "Total deals:",
            "Close rate:",
        ],
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
# 10. LEGEND (MODE-AWARE)
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
        <div style="width:14px; height:14px; background:{category_color(1, mode)}; border:1px solid #000;"></div>
        1
    </span>

    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:{category_color(2, mode)}; border:1px solid #000;"></div>
        2–5
    </span>

    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:{category_color(6, mode)}; border:1px solid #000;"></div>
        6–10
    </span>

    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:{category_color(11, mode)}; border:1px solid #000;"></div>
        >10
    </span>

    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:#FFFFFF; border:1px solid #000;"></div>
        0 / filtered out
    </span>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))


# -----------------------------
# 11. DISPLAY MAP IN STREAMLIT
# -----------------------------

st.title("Closed RHD Properties Map")
st.write("This map pulls live data from your Google Sheet.")

st_folium(m, width=1600, height=500)
