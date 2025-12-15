import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium
import folium
import math

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

    if "Date" not in df.columns:
        df["Date"] = pd.NA

    df["Date_dt"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Year"] = df["Date_dt"].dt.year

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
# Years available
# -----------------------------
years_available = sorted(
    [int(y) for y in df["Year"].dropna().unique().tolist() if pd.notna(y)]
)

# -----------------------------
# UI CONTROLS (ONE ROW)
#   View + Year + Buyer + Top Buyers
# -----------------------------
col1, col3, col4, col5 = st.columns([1.1, 1.6, 1.7, 0.9], gap="small")

with col1:
    mode = st.radio(
        "View",
        ["Sold", "Cut Loose", "Both"],
        index=0,
        horizontal=True,
    )

with col3:
    year_choice = st.selectbox(
        "Year",
        ["All years"] + years_available,
        index=0,
    )

# Apply Year filter rules (single year or all years)
df_time = df.copy()

if year_choice != "All years":
    y = int(year_choice)

    df_time_sold = df_time[
        (df_time["Status_norm"] == "sold") & (df_time["Year"] == y)
    ].copy()

    # Cut loose: filter if it has year; if year missing, keep it
    cut_mask = df_time["Status_norm"] == "cut loose"
    cut_has_year = cut_mask & df_time["Year"].notna()
    cut_no_year = cut_mask & df_time["Year"].isna()

    df_time_cut = pd.concat(
        [
            df_time[cut_has_year & (df_time["Year"] == y)],
            df_time[cut_no_year],
        ],
        ignore_index=True,
    )
else:
    df_time_sold = df_time[df_time["Status_norm"] == "sold"].copy()
    df_time_cut = df_time[df_time["Status_norm"] == "cut loose"].copy()

df_time_filtered = pd.concat([df_time_sold, df_time_cut], ignore_index=True)

# -----------------------------
# Buyer momentum (Sold only): last 12 months vs prior 12 months
# -----------------------------
sold_for_momentum = df_time_sold.copy()
sold_for_momentum["Buyer_clean"] = (
    sold_for_momentum["Buyer_clean"].fillna("").astype(str).str.strip()
)

anchor = sold_for_momentum["Date_dt"].max()
if pd.isna(anchor):
    anchor = pd.Timestamp.today()

last12_start = anchor - pd.Timedelta(days=365)
prev12_start = anchor - pd.Timedelta(days=730)

df_last12 = sold_for_momentum[
    (sold_for_momentum["Date_dt"] > last12_start)
    & (sold_for_momentum["Date_dt"] <= anchor)
]
df_prev12 = sold_for_momentum[
    (sold_for_momentum["Date_dt"] > prev12_start)
    & (sold_for_momentum["Date_dt"] <= last12_start)
]

last12_counts = df_last12[df_last12["Buyer_clean"] != ""].groupby("Buyer_clean").size()
prev12_counts = df_prev12[df_prev12["Buyer_clean"] != ""].groupby("Buyer_clean").size()

buyer_momentum = (
    pd.DataFrame({"last12": last12_counts, "prev12": prev12_counts})
    .fillna(0)
    .astype(int)
)
buyer_momentum["delta"] = buyer_momentum["last12"] - buyer_momentum["prev12"]

# -----------------------------
# Buyer selector options (with momentum labels)
# -----------------------------
buyers_plain = (
    df_time_sold["Buyer_clean"].astype(str).str.strip()
)
buyers_plain = sorted([b for b in buyers_plain.unique().tolist() if b])

with col4:
    if mode in ["Sold", "Both"]:
        labels = ["All buyers"]
        label_to_buyer = {"All buyers": "All buyers"}

        if not buyer_momentum.empty:
            bm = buyer_momentum.sort_values(["last12", "delta"], ascending=False)
            for b, row in bm.iterrows():
                d = int(row["delta"])
                arrow = "▲" if d > 0 else ("▼" if d < 0 else "→")
                labels.append(
                    f"{b}  {arrow} {d:+d}  ({int(row['last12'])} vs {int(row['prev12'])})"
                )
                label_to_buyer[labels[-1]] = b
        else:
            for b in buyers_plain:
                labels.append(b)
                label_to_buyer[b] = b

        chosen_label = st.selectbox("Buyer", labels, index=0)
        buyer_choice = label_to_buyer[chosen_label]
    else:
        buyer_choice = "All buyers"
        st.selectbox("Buyer", ["All buyers"], index=0, disabled=True)

with col5:
    TOP_N = st.number_input("Top buyers", min_value=3, max_value=15, value=3, step=1)

buyer_active = (buyer_choice != "All buyers") and (mode in ["Sold", "Both"])

# -----------------------------
# OVERALL STATS (respect year filter)
# -----------------------------
sold_total_overall = int(len(df_time_sold))
cut_total_overall = int(len(df_time_cut))
total_deals_overall = sold_total_overall + cut_total_overall

total_buyers_overall = int(
    df_time_sold.loc[df_time_sold["Buyer_clean"] != "", "Buyer_clean"].nunique()
)

close_rate_overall = (sold_total_overall / total_deals_overall) if total_deals_overall > 0 else None
close_rate_str = f"{close_rate_overall*100:.1f}%" if close_rate_overall is not None else "N/A"

# -----------------------------
# Sidebar: Overall stats at the top
# -----------------------------
st.sidebar.markdown("## Overall stats")
st.sidebar.caption(f"Year: **{year_choice}**")

st.sidebar.markdown(
    f"""
<div style="
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 10px;
    padding: 10px 12px;
">
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Sold</span><span><b>{sold_total_overall}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Cut loose</span><span><b>{cut_total_overall}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Total deals</span><span><b>{total_deals_overall}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Total buyers</span><span><b>{total_buyers_overall}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between;">
        <span>Close rate</span><span><b>{close_rate_str}</b></span>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

st.sidebar.markdown("---")

# -----------------------------
# Recompute county sold/cut/total using time-filtered dataset
# -----------------------------
df_conv = df_time_filtered[df_time_filtered["Status_norm"].isin(["sold", "cut loose"])].copy()
grp_all = df_conv.groupby("County_clean_up")
sold_counts = grp_all.apply(lambda g: (g["Status_norm"] == "sold").sum())
cut_counts = grp_all.apply(lambda g: (g["Status_norm"] == "cut loose").sum())

sold_counts_dict = sold_counts.to_dict()
cut_counts_dict = cut_counts.to_dict()

# -----------------------------
# County health score (0–100): close_rate × log1p(total)
#   (Still computed for rankings, but removed from hover/popup.)
# -----------------------------
health_raw = {}
all_counties = set(list(sold_counts_dict.keys()) + list(cut_counts_dict.keys()))
for county_up in all_counties:
    s = int(sold_counts_dict.get(county_up, 0))
    c = int(cut_counts_dict.get(county_up, 0))
    t = s + c
    if t == 0:
        health_raw[county_up] = 0.0
    else:
        close_rate = s / t
        health_raw[county_up] = close_rate * math.log1p(t)

max_raw = max(health_raw.values()) if health_raw else 0.0
health_score = {}
for county_up, raw in health_raw.items():
    score = (raw / max_raw * 100.0) if max_raw > 0 else 0.0
    health_score[county_up] = round(score, 1)

# Buyer-specific sold counts by county (time-filtered)
buyer_sold_counts_dict = {}
if buyer_active:
    df_buyer_sold = df_time_sold[df_time_sold["Buyer_clean"] == buyer_choice]
    buyer_sold_counts_dict = df_buyer_sold.groupby("County_clean_up").size().to_dict()

# -----------------------------
# County ranking panel (sidebar) — ONLY Health score + Buyer count
# -----------------------------
county_rows = []
all_counties_sorted = sorted(set(list(sold_counts_dict.keys()) + list(cut_counts_dict.keys())))

for c_up in all_counties_sorted:
    hs = float(health_score.get(c_up, 0.0))

    buyer_count = int(
        df_time_sold.loc[df_time_sold["County_clean_up"] == c_up, "Buyer_clean"]
        .replace("", pd.NA)
        .dropna()
        .nunique()
    )

    county_rows.append({
        "County": c_up.title(),
        "Health score": hs,
        "Buyer count": buyer_count,
    })

rank_df = pd.DataFrame(county_rows)

st.sidebar.markdown("## County rankings")
rank_metric = st.sidebar.selectbox(
    "Rank by",
    ["Health score", "Buyer count"],
    index=0
)
top_n = st.sidebar.slider("Top N", 5, 50, 15, 5)

rank_df_sorted = rank_df.sort_values(rank_metric, ascending=False).head(top_n)

st.sidebar.dataframe(
    rank_df_sorted,
    use_container_width=True,
    hide_index=True
)

# -----------------------------
# Top buyers by county (from SOLD data only, time-filtered)
# -----------------------------
df_sold_all = df_time_sold[df_time_sold["Buyer_clean"] != ""].copy()
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
    df_view = df_time_sold.copy()
    if buyer_active:
        df_view = df_view[df_view["Buyer_clean"] == buyer_choice]
elif mode == "Cut Loose":
    df_view = df_time_cut.copy()
else:  # Both
    df_sold = df_time_sold.copy()
    if buyer_active:
        df_sold = df_sold[df_sold["Buyer_clean"] == buyer_choice]
    df_view = pd.concat([df_sold, df_time_cut.copy()], ignore_index=True)

county_counts_view = df_view.groupby("County_clean_up").size().to_dict()

county_properties_view = {}
for _, row in df_view.iterrows():
    c = row["County_clean_up"]
    county_properties_view.setdefault(c, []).append(
        {"Address": row["Address"], "City": row["City"], "SF_URL": row["Salesforce_URL"]}
    )

# -----------------------------
# Load TN Counties GeoJSON
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
#   Health score removed from hover + popup.
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

    top_list = top_buyers_dict.get(name_up, [])[: int(TOP_N)]
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

    if buyer_active and p.get("BUYER_SOLD_COUNT", 0) == 0:
        return {"fillColor": "#FFFFFF", "color": "black", "weight": 0.5, "fillOpacity": 0.15}

    v_for_color = p.get("BUYER_SOLD_COUNT", 0) if buyer_active else p.get("PROP_COUNT", 0)

    return {
        "fillColor": category_color(v_for_color, mode, buyer_active),
        "color": "black",
        "weight": 0.5,
        "fillOpacity": 0.9,
    }

# Hover tooltip: health score removed
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

# -----------------------------
# Bottom bar legend (remove word "hidden" for 0)
# -----------------------------
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
        <div style="width:14px; height:14px; background:#FFFFFF; border:1px solid #000;"></div> 0
    </span>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

st.title("Closed RHD Properties Map")
st_folium(m, width=1800, height=500)
