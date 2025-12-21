import folium

from colors import category_color, mao_color


def add_legend(m, *, legend_mode: str, mode: str, buyer_active: bool):
    """Bottom, centered legend."""
    if legend_mode == "mao":
        legend_html = f"""
<div style="
    position: fixed;
    bottom: 10px;
    left: 50%;
    transform: translateX(-50%);
    background-color: rgba(255,255,255,0.88);
    color: black;
    z-index: 9999;
    font-size: 13px;
    padding: 6px 14px;
    border-radius: 6px;
    border: 1px solid #888;
    display: flex;
    gap: 14px;
    align-items: center;
">
    <span style='display:flex; align-items:center; gap:6px;'>
        <div style="width:14px; height:14px; background:{mao_color(0.73)}; border:1px solid #000;"></div>
        <b>A</b> (higher)
    </span>
    <span style='display:flex; align-items:center; gap:6px;'>
        <div style="width:14px; height:14px; background:{mao_color(0.68)}; border:1px solid #000;"></div>
        <b>B</b>
    </span>
    <span style='display:flex; align-items:center; gap:6px;'>
        <div style="width:14px; height:14px; background:{mao_color(0.61)}; border:1px solid #000;"></div>
        <b>C</b>
    </span>
    <span style='display:flex; align-items:center; gap:6px;'>
        <div style="width:14px; height:14px; background:{mao_color(0.53)}; border:1px solid #000;"></div>
        <b>D</b> (lower)
    </span>
    <span style='display:flex; align-items:center; gap:6px;'>
        <div style="width:14px; height:14px; background:#FFFFFF; border:1px solid #000;"></div>
        blank
    </span>
</div>
"""
        m.get_root().html.add_child(folium.Element(legend_html))
        return

    legend_html = f"""
<div style="
    position: fixed;
    bottom: 10px;
    left: 50%;
    transform: translateX(-50%);
    background-color: rgba(255,255,255,0.85);
    color: black;
    z-index: 9999;
    font-size: 13px;
    padding: 6px 14px;
    border-radius: 6px;
    border: 1px solid #888;
    display: flex;
    gap: 14px;
    align-items: center;
">
    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:{category_color(1, mode, buyer_active)}; border:1px solid #000;"></div> 1
    </span>
    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:{category_color(2, mode, buyer_active)}; border:1px solid #000;"></div> 2–5
    </span>
    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:{category_color(6, mode, buyer_active)}; border:1px solid #000;"></div> 6–10
    </span>
    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:{category_color(11, mode, buyer_active)}; border:1px solid #000;"></div> >10
    </span>
    <span style='display:flex; align-items:center; gap:4px;'>
        <div style="width:14px; height:14px; background:#FFFFFF; border:1px solid #000;"></div> 0
    </span>
</div>
"""
    m.get_root().html.add_child(folium.Element(legend_html))


def build_map(
    tn_geo: dict,
    *,
    team_view: str,
    mode: str,
    buyer_active: bool,
    buyer_choice: str,
    center_lat: float,
    center_lon: float,
    zoom_start: int,
    tiles: str,
    color_scheme: str = "activity",  # "activity" or "mao"
):
    """Build the Folium choropleth map."""
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom_start,
        tiles=tiles,
        control_scale=True,
        dragging=False,
        scrollWheelZoom=False,
        doubleClickZoom=False,
        boxZoom=False,
        keyboard=False,
        zoom_control=False,
    )

    def style_function(feature):
        p = feature.get("properties", {})

        if color_scheme == "mao":
            mn = p.get("MAO_MIN_PCT", "")
            try:
                mn_val = float(mn) if mn != "" else None
            except Exception:
                mn_val = None

            if mn_val is None:
                return {"fillColor": "#FFFFFF", "color": "black", "weight": 0.5, "fillOpacity": 0.15}

            return {"fillColor": mao_color(mn_val), "color": "black", "weight": 0.5, "fillOpacity": 0.9}

        if buyer_active and p.get("BUYER_SOLD_COUNT", 0) == 0:
            return {"fillColor": "#FFFFFF", "color": "black", "weight": 0.5, "fillOpacity": 0.15}

        v_for_color = p.get("BUYER_SOLD_COUNT", 0) if buyer_active else p.get("PROP_COUNT", 0)
        return {"fillColor": category_color(v_for_color, mode, buyer_active), "color": "black", "weight": 0.5, "fillOpacity": 0.9}

    team_view_norm = (team_view or "").strip().lower()

    if color_scheme == "mao" or team_view_norm == "acquisitions":
        tooltip_fields = ["NAME", "MAO_TIER", "MAO_RANGE", "BUYER_COUNT"]
        tooltip_aliases = ["County:", "MAO Tier:", "MAO Range:", "# Buyers:"]
    else:
        tooltip_fields = ["NAME", "SOLD_COUNT", "CLOSE_RATE_STR"]
        tooltip_aliases = ["County:", "Sold:", "Close rate:"]

        if buyer_active:
            tooltip_fields.append("BUYER_SOLD_COUNT")
            tooltip_aliases.append(f"{buyer_choice} (Sold):")

    tooltip = folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases, localize=True, sticky=False)

    folium.GeoJson(
        tn_geo,
        name="TN Counties",
        style_function=style_function,
        tooltip=tooltip,
        popup=folium.GeoJsonPopup(
            fields=["POPUP_HTML"],
            labels=False,
            localize=True,
            parse_html=True,
            max_width=420,
            style="""
                font-size: 13.5px;
                line-height: 1.2;
                padding: 3px;
                max-height: 240px;
                overflow-y: auto;
                overflow-x: hidden;
            """,
        ),
    ).add_to(m)

    add_legend(m, legend_mode=("mao" if color_scheme == "mao" else "activity"), mode=mode, buyer_active=buyer_active)
    return m
