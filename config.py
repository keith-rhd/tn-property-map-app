# config.py
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
GEOJSON_LOCAL_PATH = BASE_DIR / "tn_counties.geojson"
