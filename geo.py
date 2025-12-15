# geo.py
import json
import streamlit as st
from config import GEOJSON_LOCAL_PATH

@st.cache_data(show_spinner=False)
def load_tn_geojson() -> dict:
    with open(GEOJSON_LOCAL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
