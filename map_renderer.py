"""
map_renderer.py — Dynamic SVG floor-plan generator for MallMate AI.

Responsibilities:
  - Render a per-floor SVG from mall_data.json coordinates.
  - Show all locations as styled, labeled shapes (colour-coded by category).
  - Draw walkable connections as lines.
  - Highlight a computed route path with a distinct colour.
  - Mark the start and destination with distinct icons.
  - Indicate cross-floor transitions with arrow labels.

The SVG is generated entirely from mall_data.json; no static SVG file is used.

Public API
----------
render_map(mall_data, floor, route_path=None, start_id=None, destination_id=None)
    -> str   (SVG string, safe for st.components.v1.html())
"""

from __future__ import annotations

import html as html_mod

# ---------------------------------------------------------------------------
# Visual configuration
# ---------------------------------------------------------------------------

CATEGORY_COLORS: dict[str, str] = {
    "entrance":  "#1565C0",   # Deep Blue
    "landmark":  "#6A1B9A",   # Deep Purple
    "atm":       "#E65100",   # Deep Orange
    "washroom":  "#00838F",   # Cyan / Teal
    "retail":    "#2E7D32",   # Dark Green
    "food":      "#B71C1C",   # Dark Red
    "cafe":      "#4E342E",   # Brown
    "cinema":    "#283593",   # Indigo
    "leisure":   "#00695C",   # Teal
    "stairs":    "#455A64",   # Blue Grey
    "escalator": "#455A64",
    "elevator":  "#37474F",
    "corridor":  "#78909C",   # Lighter Blue Grey
}

FLOOR_LABELS = {0: "Ground Floor", 1: "First Floor", 2: "Second Floor"}

# Node dimensions
_CORRIDOR_R = 8         # radius of junction circles
_NODE_W = 80            # width of shop rectangles
_NODE_H = 34            # height of shop rectangles
_NODE_RX = 6            # corner radius

# Colours for route + markers
_ROUTE_COLOR = "#FF6B35"       # Bright orange
_ROUTE_WIDTH = 5
_CONN_COLOR = "#B0BEC5"        # Light grey
_CONN_WIDTH = 2
_START_COLOR = "#00C853"       # Vivid green
_DEST_COLOR = "#D50000"        # Vivid red
_DIM_OPACITY = "0.22"          # Opacity for nodes/edges on other floors
_MARKER_R = 11

_FLOOR_CHANGE_TYPES = {"stairs", "escalator", "elevator"}

# Categories rendered as small circles (infrastructure) vs rectangles (places)
_CIRCLE_CATEGORIES = {"corridor", "stairs", "escalator", "elevator"}


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """HTML-escape text for safe SVG embedding."""
    return html_mod.escape(str(text), quote=True)


def _truncate(text: str, max_chars: int = 12) -> str:
    if len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


def _edge_key(a: str, b: str) -> frozenset:
    return frozenset([a, b])


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------

def render_map(
    mall_data: dict,
    floor: int,
    route_path: list[str] | None = None,
    start_id: str | None = None,
    destination_id: str | None = None,
) -> str:
    """
    Generate an SVG string for the given floor.

    Parameters
    ----------
    mall_data      : Parsed mall_data.json dict.
    floor          : Floor number to render (0, 1, or 2).
    route_path     : Ordered list of location IDs for the computed route.
    start_id       : Starting location ID (gets a green marker).
    destination_id : Destination location ID (gets a red marker).

    Returns
    -------
    Full HTML string (containing the SVG) ready for st.components.v1.html().
    """
    width = mall_data["mall"]["svg_width"]
    height = mall_data["mall"]["svg_height"]
    floor_label = FLOOR_LABELS.get(floor, f"Floor {floor}")

    # Build lookup structures
    loc_by_id: dict[str, dict] = {loc["id"]: loc for loc in mall_data["locations"]}
    route_set: set[str] = set(route_path or [])

    # Identify route edges (pairs of adjacent route nodes)
    route_edges: set[frozenset] = set()
    if route_path and len(route_path) > 1:
        for i in range(len(route_path) - 1):
            route_edges.add(_edge_key(route_path[i], route_path[i + 1]))

    # Identify cross-floor transition nodes in the route
    cross_floor_labels: dict[str, str] = {}  # node_id -> "↑ First Floor" etc.
    if route_path and len(route_path) > 1:
        for i in range(len(route_path) - 1):
            a, b = route_path[i], route_path[i + 1]
            la = loc_by_id.get(a, {})
            lb = loc_by_id.get(b, {})
            if la.get("floor") == floor and lb.get("floor") != floor:
                direction = "↑" if lb.get("floor", 0) > floor else "↓"
                cross_floor_labels[a] = f"{direction} {FLOOR_LABELS.get(lb['floor'], 'Floor ?')}"

    # ------------------------------------------------------------------ #
    # Build SVG                                                            #
    # ------------------------------------------------------------------ #
    parts: list[str] = []

    # SVG header
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" '
        f'style="font-family: \'Segoe UI\', Arial, sans-serif; background:#F5F7FA;">'
    )

    # Background
    parts.append(
        f'<rect width="{width}" height="{height}" fill="#F0F4F8" rx="14" />'
    )

    # Floor label (top-left)
    parts.append(
        f'<text x="16" y="26" font-size="14" font-weight="700" '
        f'fill="#37474F" letter-spacing="0.5">{_esc(floor_label)}</text>'
    )
    # Fictional mall disclaimer
    parts.append(
        f'<text x="{width - 12}" y="26" font-size="9" fill="#90A4AE" '
        f'text-anchor="end">Sample map — not a real mall</text>'
    )

    # ------------------------------------------------------------------ #
    # Draw connections                                                     #
    # ------------------------------------------------------------------ #
    drawn_conn: set[frozenset] = set()

    for conn in mall_data["connections"]:
        a_id = conn["from"]
        b_id = conn["to"]
        edge_key = _edge_key(a_id, b_id)
        if edge_key in drawn_conn:
            continue
        drawn_conn.add(edge_key)

        a = loc_by_id.get(a_id)
        b = loc_by_id.get(b_id)
        if not a or not b:
            continue

        a_floor = a["floor"]
        b_floor = b["floor"]

        # Only draw connections that touch the current floor
        if a_floor != floor and b_floor != floor:
            continue

        ax, ay = a["coordinates"]["x"], a["coordinates"]["y"]
        bx, by = b["coordinates"]["x"], b["coordinates"]["y"]

        is_route_edge = edge_key in route_edges
        is_cross = (a_floor != b_floor)

        if is_route_edge:
            color = _ROUTE_COLOR
            stroke_w = _ROUTE_WIDTH
            dash = "8,4" if is_cross else "none"
            opacity = "1"
        elif is_cross:
            color = "#90A4AE"
            stroke_w = 1
            dash = "5,5"
            opacity = "0.7"
        else:
            color = _CONN_COLOR
            stroke_w = _CONN_WIDTH
            dash = "none"
            opacity = "1"

        dash_attr = f'stroke-dasharray="{dash}"' if dash != "none" else ""
        parts.append(
            f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" '
            f'stroke="{color}" stroke-width="{stroke_w}" '
            f'opacity="{opacity}" {dash_attr} stroke-linecap="round"/>'
        )

    # ------------------------------------------------------------------ #
    # Draw location nodes                                                  #
    # ------------------------------------------------------------------ #
    for loc in mall_data["locations"]:
        loc_id = loc["id"]
        loc_floor = loc["floor"]
        x = loc["coordinates"]["x"]
        y = loc["coordinates"]["y"]
        category = loc["category"]
        name = loc["name"]

        base_color = CATEGORY_COLORS.get(category, "#607D8B")
        is_on_floor = (loc_floor == floor)
        in_route = loc_id in route_set

        # Opacity: full for current floor nodes, dim others
        opacity = "1" if is_on_floor else _DIM_OPACITY
        # Extra outline glow for route nodes on this floor
        outline = ""
        if is_on_floor and in_route and loc_id not in (start_id, destination_id):
            outline = (
                f'<circle cx="{x}" cy="{y}" r="{_MARKER_R + 6}" '
                f'fill="{_ROUTE_COLOR}" opacity="0.25"/>'
            )

        if category in _CIRCLE_CATEGORIES:
            # Small infrastructure circles
            label = _truncate(name, 10)
            r = _CORRIDOR_R
            parts.append(
                f'<g opacity="{opacity}">'
                f'{outline}'
                f'<circle cx="{x}" cy="{y}" r="{r}" fill="{base_color}" />'
                f'<text x="{x}" y="{y + r + 11}" font-size="8" fill="#546E7A" '
                f'text-anchor="middle">{_esc(label)}</text>'
                f'</g>'
            )
        else:
            # Rectangular shop nodes
            label = _truncate(name, 12)
            rx_attr = _NODE_RX
            nx_ = x - _NODE_W // 2
            ny_ = y - _NODE_H // 2
            shadow = (
                f'<rect x="{nx_ + 2}" y="{ny_ + 2}" width="{_NODE_W}" '
                f'height="{_NODE_H}" rx="{rx_attr}" fill="#000" opacity="0.12"/>'
            ) if is_on_floor else ""
            parts.append(
                f'<g opacity="{opacity}">'
                f'{shadow}'
                f'{outline}'
                f'<rect x="{nx_}" y="{ny_}" width="{_NODE_W}" height="{_NODE_H}" '
                f'rx="{rx_attr}" fill="{base_color}" />'
                f'<text x="{x}" y="{y + 5}" font-size="9.5" font-weight="600" '
                f'fill="white" text-anchor="middle">{_esc(label)}</text>'
                f'</g>'
            )

        # Cross-floor transition label (arrow to next floor)
        if is_on_floor and loc_id in cross_floor_labels:
            label_text = cross_floor_labels[loc_id]
            parts.append(
                f'<text x="{x}" y="{y - _MARKER_R - 6}" font-size="9" '
                f'fill="{_ROUTE_COLOR}" font-weight="700" text-anchor="middle">'
                f'{_esc(label_text)}</text>'
            )

    # ------------------------------------------------------------------ #
    # Start marker                                                         #
    # ------------------------------------------------------------------ #
    if start_id and start_id in loc_by_id:
        s = loc_by_id[start_id]
        sx, sy = s["coordinates"]["x"], s["coordinates"]["y"]
        s_floor = s["floor"]
        opacity = "1" if s_floor == floor else _DIM_OPACITY
        parts.append(
            f'<g opacity="{opacity}">'
            # Outer glow
            f'<circle cx="{sx}" cy="{sy}" r="{_MARKER_R + 5}" '
            f'fill="{_START_COLOR}" opacity="0.3"/>'
            # Solid circle
            f'<circle cx="{sx}" cy="{sy}" r="{_MARKER_R}" '
            f'fill="{_START_COLOR}" stroke="white" stroke-width="2.5"/>'
            # "S" label
            f'<text x="{sx}" y="{sy + 4}" font-size="10" font-weight="800" '
            f'fill="white" text-anchor="middle">S</text>'
            f'</g>'
        )

    # ------------------------------------------------------------------ #
    # Destination marker                                                   #
    # ------------------------------------------------------------------ #
    if destination_id and destination_id in loc_by_id:
        d = loc_by_id[destination_id]
        dx, dy = d["coordinates"]["x"], d["coordinates"]["y"]
        d_floor = d["floor"]
        opacity = "1" if d_floor == floor else _DIM_OPACITY
        parts.append(
            f'<g opacity="{opacity}">'
            # Outer glow
            f'<circle cx="{dx}" cy="{dy}" r="{_MARKER_R + 5}" '
            f'fill="{_DEST_COLOR}" opacity="0.3"/>'
            # Solid circle
            f'<circle cx="{dx}" cy="{dy}" r="{_MARKER_R}" '
            f'fill="{_DEST_COLOR}" stroke="white" stroke-width="2.5"/>'
            # "D" label
            f'<text x="{dx}" y="{dy + 4}" font-size="10" font-weight="800" '
            f'fill="white" text-anchor="middle">D</text>'
            f'</g>'
        )

    # SVG close
    parts.append("</svg>")

    svg_string = "\n".join(parts)

    # Wrap in minimal HTML with legend
    # Build legend only for items that are actually displayed
    legend_items = []
    if start_id and start_id in loc_by_id:
        legend_items.append(("S", _START_COLOR, "Start"))
    if destination_id and destination_id in loc_by_id:
        legend_items.append(("D", _DEST_COLOR, "Destination"))
    legend_circles = " ".join(
        f'<span style="display:inline-flex;align-items:center;margin-right:12px;">'
        f'<span style="width:18px;height:18px;border-radius:50%;background:{c};'
        f'color:white;font-size:10px;font-weight:800;display:inline-flex;'
        f'align-items:center;justify-content:center;margin-right:4px;">{lbl}</span>'
        f'<span style="font-size:12px;color:#546E7A;">{name}</span>'
        f'</span>'
        for lbl, c, name in legend_items
    )
    route_legend = (
        f'<span style="display:inline-flex;align-items:center;margin-right:12px;">'
        f'<span style="width:24px;height:4px;background:{_ROUTE_COLOR};'
        f'border-radius:2px;margin-right:4px;"></span>'
        f'<span style="font-size:12px;color:#546E7A;">Route</span>'
        f'</span>'
    ) if route_path else ""

    html = (
        f'<div style="background:#F0F4F8;border-radius:12px;padding:8px;">'
        f'{svg_string}'
        f'<div style="padding:6px 4px 2px;display:flex;flex-wrap:wrap;align-items:center;">'
        f'{legend_circles}{route_legend}'
        f'</div>'
        f'</div>'
    )
    return html
