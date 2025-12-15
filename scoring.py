# scoring.py
import math
from typing import Dict, Iterable

def compute_health_score(
    counties: Iterable[str],
    sold_counts: Dict[str, int],
    cut_counts: Dict[str, int],
) -> Dict[str, float]:
    """
    Health score (0–100):
      raw = close_rate * log1p(total)
      normalized by max(raw) across counties
    """
    raw = {}
    for county_up in counties:
        s = int(sold_counts.get(county_up, 0))
        c = int(cut_counts.get(county_up, 0))
        t = s + c
        if t == 0:
            raw[county_up] = 0.0
        else:
            close_rate = s / t
            raw[county_up] = close_rate * math.log1p(t)

    max_raw = max(raw.values()) if raw else 0.0
    out = {}
    for k, v in raw.items():
        score = (v / max_raw * 100.0) if max_raw > 0 else 0.0
        out[k] = round(score, 1)
    return out
