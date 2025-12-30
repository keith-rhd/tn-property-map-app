from __future__ import annotations

from typing import Any, Dict


def build_context(**kwargs) -> Dict[str, Any]:
    """
    Central context dict used to pass data/derived values around the app.

    Phase B2: app.py computes values once, then passes a single ctx dict
    to UI functions instead of 15 separate arguments.
    """
    ctx = dict(kwargs)

    # Small convenience defaults (safe)
    ctx.setdefault("team_view", "Dispo")
    ctx.setdefault("selected", "")
    ctx.setdefault("all_county_options", [])
    ctx.setdefault("mao_tier_by_county", {})
    ctx.setdefault("mao_range_by_county", {})
    ctx.setdefault("buyer_count_by_county", {})
    ctx.setdefault("buyers_set_by_county", {})
    ctx.setdefault("adjacency", {})
    ctx.setdefault("top_buyers_dict", {})

    # Filtered datasets
    ctx.setdefault("fd", None)
    ctx.setdefault("df_view", None)

    return ctx
