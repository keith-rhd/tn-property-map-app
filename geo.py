# geo.py
import requests
import streamlit as st

# A small, reliable TN counties geojson (Plotly dataset filtered to TN)
TN_GEOJSON_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
TN_STATE_FIPS = "47"

@st.cache_data(show_spinner=False)
def load_tn_geojson() -> dict:
    resp = requests.get(TN_GEOJSON_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    tn_features = [
        f for f in data["features"]
        if f.get("properties", {}).get("STATE") == TN_STATE_FIPS
    ]
    return {"type": "FeatureCollection", "features": tn_features}
