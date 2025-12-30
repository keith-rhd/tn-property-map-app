# config.py
from dataclasses import dataclass
from pathlib import Path
import urllib.parse

# Base directory of the repo (reliable in Streamlit Cloud)
BASE_DIR = Path(__file__).resolve().parent

# -----------------------------
# Data / files
# -----------------------------
# Google Sheet ID (from your link)
SHEET_ID = "1XVrJ1lz-oIf9AjnKtyuzb8PmH9zk2nPy1aZ1VEotubA"

# The main data tab is gid=0 in your link.
DATA_GID = "0"

# "MAO Tiers" is a second tab in the same sheet.
MAO_TIERS_SHEET_NAME = "MAO Tiers"

def gsheet_csv_url(*, sheet_id: str, gid: str | None = None, sheet_name: str | None = None) -> str:
    """Public Google Sheets -> CSV export URL.
    Works when the sheet is shared publicly ("Anyone with the link" can view).
    Prefer gid; fall back to sheet_name.
    """
    base = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    if gid is not None:
        return f"{base}&gid={gid}"
    if sheet_name is not None:
        return f"{base}&sheet={urllib.parse.quote(sheet_name)}"
    raise ValueError("Provide gid or sheet_name")

# Main dataset CSV (Sold/Cut Loose rows)
SHEET_URL = gsheet_csv_url(sheet_id=SHEET_ID, gid=DATA_GID)

# Live MAO tiers CSV (from the 'MAO Tiers' tab)
MAO_TIERS_URL = gsheet_csv_url(sheet_id=SHEET_ID, sheet_name=MAO_TIERS_SHEET_NAME)

REQUIRED_COLS = {"Address", "City", "County", "Salesforce_URL"}

# GeoJSON file (local, in repo root)
GEOJSON_LOCAL_PATH = BASE_DIR / "tn_counties.geojson"

# -----------------------------
# Streamlit page config
# -----------------------------
DEFAULT_PAGE = dict(
    page_title="TN Property Map",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# -----------------------------
# Map defaults
# -----------------------------
MAP_DEFAULTS = dict(
    center_lat=35.8,
    center_lon=-86.4,
    zoom_start=7,
    tiles="cartodbpositron",
)

# -----------------------------
# Column names (single source of truth)
# -----------------------------
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

