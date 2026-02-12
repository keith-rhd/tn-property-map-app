# colors.py

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

    # Both
    if v == 1: return "#deebf7"
    if 2 <= v <= 5: return "#9ecae1"
    if 6 <= v <= 10: return "#4292c6"
    return "#084594"


# -----------------------------
# MAO coloring (Acq view)
# -----------------------------

def _to_fraction(v: float | None) -> float | None:
    """
    Accepts either:
      - fraction (0.73)
      - percent (73)
    Returns fraction (0.73).
    """
    if v is None:
        return None
    try:
        v = float(v)
    except Exception:
        return None

    if v > 1.5:  # treat as percent
        return v / 100.0
    return v


def mao_tier_from_min(min_val: float | None) -> str | None:
    """
    Tier bands based on MAO Min (fraction form):
      A: 0.73–0.77
      B: 0.68–0.72
      C: 0.61–0.66
      D: 0.53–0.58

    We classify primarily by the MIN value (what acquisitions cares about).
    """
    mn = _to_fraction(min_val)
    if mn is None:
        return None

    if 0.73 <= mn <= 0.77:
        return "A"
    if 0.68 <= mn <= 0.72:
        return "B"
    if 0.61 <= mn <= 0.66:
        return "C"
    if 0.53 <= mn <= 0.58:
        return "D"

    # If it's outside the specified bands, assign to nearest lower tier bucket:
    # (keeps map colored even if a county is slightly off-band)
    if mn > 0.77:
        return "A"
    if mn >= 0.67:
        return "B"
    if mn >= 0.59:
        return "C"
    if mn >= 0.50:
        return "D"
    return None


def mao_color(min_val: float | None) -> str:
    """
    Tier colors (A hottest/most aggressive MAO => green).
    Blank/unknown => white.
    """
    t = mao_tier_from_min(min_val)
    if t is None:
        return "#FFFFFF"

    if t == "A": return "#1a9850"  # green
    if t == "B": return "#91cf60"  # light green
    if t == "C": return "#fdae61"  # orange
    return "#d73027"               # red (D)
