# config.py
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
GEOJSON_LOCAL_PATH = BASE_DIR / "tn_counties.geojson"

SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTw_-UeODGJQFKDMVXM59CG45SrbADPQpyWcALENIDqT8SUhHFm1URYNP3aB6vudjzpM1mBFRio3rWi/pub?output=csv"

REQUIRED_COLS = {"Address", "City", "County", "Salesforce_URL"}

DEFAULT_PAGE = dict(
    page_title="TN Property Map",
    layout="wide",
    initial_sidebar_state="collapsed",
)

MAP_DEFAULTS = dict(
    center_lat=35.8,
    center_lon=-86.4,
    zoom_start=7,
    tiles="cartodbpositron",
)

GEOJSON_LOCAL_PATH = "tn_counties.geojson"

@dataclass(frozen=True)
class Cols:
    address: str = "Address"
    city: str = "City"
    county: str = "County"
    sf_url: str = "Salesforce_URL"
    status: str = "Status"
    buyer: str = "Buyer"
    date: str = "Date"

C = Cols()
