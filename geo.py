# geo.py
import requests
import streamlit as st

# A small, reliable TN counties geojson (Plotly dataset filtered to TN)
TN_GEOJSON_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
TN_STATE_FIPS = "47"


@st.cache_data(ttl=86400, show_spinner=False)
def load_tn_geojson() -> dict:
    resp = requests.get(TN_GEOJSON_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    tn_features = [
        f for f in data.get("features", [])
        if str(f.get("properties", {}).get("STATE")) == TN_STATE_FIPS
    ]
    return {"type": "FeatureCollection", "features": tn_features}


@st.cache_resource(show_spinner=False)
def build_county_adjacency(tn_geo: dict) -> dict[str, list[str]]:
    """
    Returns adjacency dict: COUNTY_NAME_UPPER -> [NEIGHBOR_COUNTY_NAME_UPPER, ...]
    Counties are neighbors if their polygons touch.

    Note: expensive; cache_resource keeps it stable across reruns.
    """
    from shapely.geometry import shape

    feats = tn_geo.get("features", [])
    names = []
    geoms = []

    for f in feats:
        props = f.get("properties", {})
        # Some geojsons use "NAME"; if not, fall back to something else
        name = str(props.get("NAME") or props.get("name") or "").upper().strip()
        if not name:
            continue
        try:
            geom = shape(f.get("geometry"))
        except Exception:
            continue
        names.append(name)
        geoms.append(geom)

    adjacency: dict[str, list[str]] = {n: [] for n in names}

    # brute-force pairwise touches (TN has 95 counties; ok)
    for i in range(len(names)):
        ni = names[i]
        gi = geoms[i]
        for j in range(i + 1, len(names)):
            nj = names[j]
            gj = geoms[j]

            try:
                if gi.touches(gj):
                    adjacency[ni].append(nj)
                    adjacency[nj].append(ni)
            except Exception:
                continue

    # sort for stable UI
    for k in adjacency:
        adjacency[k] = sorted(set(adjacency[k]))

    return adjacency
