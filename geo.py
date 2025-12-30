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


@st.cache_data(show_spinner=False)
def build_county_adjacency(tn_geo: dict) -> dict[str, list[str]]:
    """
    Build an adjacency mapping: COUNTY_NAME_UPPER -> [NEIGHBOR_COUNTY_NAME_UPPER, ...]
    Counties are neighbors if their polygons "touch" (share a boundary segment or point).

    Cached because shapely touches checks are relatively expensive.
    """
    try:
        from shapely.geometry import shape
    except Exception as e:
        raise RuntimeError(
            "Missing dependency: shapely. Add 'shapely' to requirements.txt and redeploy."
        ) from e

    features = tn_geo.get("features", [])

    names: list[str] = []
    geoms = []

    for f in features:
        props = f.get("properties", {}) or {}
        name = str(props.get("NAME", "")).strip().upper()
        geom = f.get("geometry")

        if not name or not geom:
            continue

        try:
            geoms.append(shape(geom))
            names.append(name)
        except Exception:
            # If a geometry is malformed, skip it.
            continue

    adjacency: dict[str, list[str]] = {n: [] for n in names}

    # O(n^2) over ~95 counties is fine with caching
    for i in range(len(names)):
        gi = geoms[i]
        ni = names[i]
        for j in range(i + 1, len(names)):
            gj = geoms[j]
            nj = names[j]

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
