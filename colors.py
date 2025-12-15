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

    if v == 1: return "#deebf7"
    if 2 <= v <= 5: return "#9ecae1"
    if 6 <= v <= 10: return "#4292c6"
    return "#084594"
