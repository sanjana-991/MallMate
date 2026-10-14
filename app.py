"""
app.py — MallMate AI: Streamlit-based intelligent mall navigator.

Run with:
    streamlit run app.py

The UI connects the NLP and navigation modules into a full user-facing experience:
  - Natural-language search box
  - Starting-location dropdown + free-text input
  - Intent-aware results with clickable suggestion buttons
  - Per-floor SVG map with highlighted computed route
  - Step-by-step directions panel
  - Route summary card
"""

import json
import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ─────────────────────────────────────────────────────────────────────────────
# Page configuration (must be the first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MallMate AI",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Local imports (after page_config)
# ─────────────────────────────────────────────────────────────────────────────
from navigation import build_graph, find_route, find_nearest
from nlp import process_query
from map_renderer import render_map

# ─────────────────────────────────────────────────────────────────────────────
# Global CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Global font ── */
html, body, [class*="css"] { font-family: 'Segoe UI', sans-serif; }

/* ── Header ── */
.mm-header {
    background: linear-gradient(135deg, #1565C0 0%, #283593 100%);
    border-radius: 14px;
    padding: 22px 28px 16px;
    margin-bottom: 18px;
    color: white;
}
.mm-header h1 { margin: 0; font-size: 2.1rem; letter-spacing: -0.5px; }
.mm-header p  { margin: 4px 0 0; font-size: 0.95rem; opacity: 0.85; }

/* ── Cards ── */
.mm-card {
    background: #ffffff;
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    border-left: 4px solid #1565C0;
}
.mm-card.success { border-left-color: #2E7D32; }
.mm-card.warning { border-left-color: #F57C00; }
.mm-card.error   { border-left-color: #B71C1C; }
.mm-card.info    { border-left-color: #0277BD; }

/* ── Route summary ── */
.route-meta { display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 10px; }
.route-stat { text-align: center; }
.route-stat .val { font-size: 1.5rem; font-weight: 700; color: #1565C0; }
.route-stat .lbl { font-size: 0.75rem; color: #78909C; text-transform: uppercase; }

/* ── Direction steps ── */
.dir-step {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 7px 0; border-bottom: 1px solid #ECEFF1;
}
.dir-step:last-child { border-bottom: none; }
.step-num {
    min-width: 24px; height: 24px; border-radius: 50%;
    background: #1565C0; color: white;
    font-size: 11px; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
}
.step-text { font-size: 0.9rem; color: #37474F; line-height: 1.5; }

/* ── Suggestion buttons ── */
.suggestion-label { font-size: 0.85rem; color: #546E7A; margin-bottom: 8px; }

/* ── Floor tab buttons ── */
div[data-testid="column"] button { width: 100%; }

/* ── Sidebar labels ── */
.sidebar-section { font-size: 0.75rem; font-weight: 700;
    color: #78909C; text-transform: uppercase;
    letter-spacing: 0.8px; margin: 12px 0 4px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Data loading (cached)
# ─────────────────────────────────────────────────────────────────────────────
DATA_PATH = Path(__file__).parent / "mall_data.json"


@st.cache_resource
def _load_data():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    g = build_graph(data)
    return data, g


mall_data, graph = _load_data()

# Sorted list of all locations for dropdown
ALL_LOCATIONS = sorted(
    [(loc["id"], f"{loc['name']} (Floor {loc['floor']})") for loc in mall_data["locations"]],
    key=lambda x: x[1],
)
ID_TO_LOC = {loc["id"]: loc for loc in mall_data["locations"]}
FLOOR_NAMES = {0: "Ground", 1: "First", 2: "Second"}

# ─────────────────────────────────────────────────────────────────────────────
# Session state initialisation
# ─────────────────────────────────────────────────────────────────────────────
_defaults = {
    "start_id": "L01",
    "nlp_result": None,
    "route_result": None,
    "selected_floor": 0,
    "pending_destination_id": None,
    "last_query": "",
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# Helper: run the full search pipeline
# ─────────────────────────────────────────────────────────────────────────────
def run_search(query: str, start_id: str):
    """Process query → route → store results in session_state."""
    nlp = process_query(query, mall_data, current_location=start_id)
    st.session_state.nlp_result = nlp
    st.session_state.route_result = None
    st.session_state.pending_destination_id = None

    if nlp["intent"] == "navigate" and nlp["destination_id"] and nlp["start_id"]:
        route = find_route(mall_data, nlp["start_id"], nlp["destination_id"], graph)
        st.session_state.route_result = route
        if route["found"] and route["path"]:
            # Auto-select the floor of the start node
            st.session_state.selected_floor = ID_TO_LOC[route["path"][0]]["floor"]

    elif nlp["intent"] == "find_nearest" and nlp["category"]:
        effective_start = nlp["start_id"] or start_id
        if effective_start:
            route = find_nearest(mall_data, effective_start, nlp["category"], graph)
            st.session_state.route_result = route
            if route["found"] and route["path"]:
                st.session_state.selected_floor = ID_TO_LOC[route["path"][0]]["floor"]


def pick_candidate(loc_id: str):
    """Called when user clicks a suggestion button."""
    start = st.session_state.start_id
    route = find_route(mall_data, start, loc_id, graph)
    st.session_state.route_result = route
    st.session_state.pending_destination_id = loc_id
    if route["found"] and route["path"]:
        st.session_state.selected_floor = ID_TO_LOC[route["path"][0]]["floor"]


def reset_search():
    st.session_state.nlp_result = None
    st.session_state.route_result = None
    st.session_state.pending_destination_id = None
    st.session_state.last_query = ""


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:10px 0 4px;">
        <span style="font-size:1.5rem;">🗺️</span>
        <span style="font-size:1.1rem; font-weight:700; color:#1565C0; margin-left:6px;">
        MallMate AI</span>
    </div>
    """, unsafe_allow_html=True)
    st.caption("Promenade Mall — Sample Map")
    st.divider()

    # ── Starting location ──
    st.markdown('<div class="sidebar-section">📍 Starting Point</div>', unsafe_allow_html=True)

    # Option 1: Dropdown
    dropdown_options = [("", "— Select a location —")] + ALL_LOCATIONS
    dropdown_ids = [x[0] for x in dropdown_options]
    dropdown_labels = [x[1] for x in dropdown_options]

    current_idx = dropdown_ids.index(st.session_state.start_id) if st.session_state.start_id in dropdown_ids else 0
    selected_idx = st.selectbox(
        "Select starting point",
        range(len(dropdown_options)),
        format_func=lambda i: dropdown_labels[i],
        index=current_idx,
        label_visibility="collapsed",
    )
    if selected_idx > 0:
        st.session_state.start_id = dropdown_ids[selected_idx]

    # Option 2: Free-text
    st.caption("Or type it:")
    start_text = st.text_input(
        "Type your starting location",
        placeholder="e.g. main entrance, Starbucks…",
        label_visibility="collapsed",
    )
    if start_text.strip():
        from nlp import resolve_destination
        res = resolve_destination(start_text.strip(), mall_data)
        if res["resolved"]:
            st.session_state.start_id = res["location_id"]
            name = ID_TO_LOC[res["location_id"]]["name"]
            st.success(f"✓ {name}", icon="📍")
        else:
            st.warning("Location not found. Try the dropdown.", icon="⚠️")

    # ── Start info ──
    if st.session_state.start_id and st.session_state.start_id in ID_TO_LOC:
        s = ID_TO_LOC[st.session_state.start_id]
        st.markdown(
            f'<div style="background:#E3F2FD;border-radius:8px;padding:8px 10px;'
            f'margin-top:6px;font-size:0.85rem;">'
            f'<b>📍 {s["name"]}</b><br/>'
            f'<span style="color:#546E7A;">{FLOOR_NAMES[s["floor"]]} Floor · {s["category"].title()}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Floor viewer ──
    st.markdown('<div class="sidebar-section">🏢 Map Floor</div>', unsafe_allow_html=True)
    floor_cols = st.columns(3)
    for i, (fnum, flbl) in enumerate([(0, "Ground"), (1, "First"), (2, "Second")]):
        with floor_cols[i]:
            active = st.session_state.selected_floor == fnum
            if st.button(flbl, key=f"floor_btn_{fnum}",
                         type="primary" if active else "secondary"):
                st.session_state.selected_floor = fnum

    st.divider()

    # ── Reset ──
    if st.button("🔄 Reset Search", use_container_width=True):
        reset_search()
        st.rerun()

    st.divider()
    st.caption(
        "**MallMate AI** · NLP-Based Mall Navigator  \n"
        "Sample fictional mall — not a verified real-world map."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main content
# ─────────────────────────────────────────────────────────────────────────────

# ── Header ──
st.markdown("""
<div class="mm-header">
    <h1>🗺️ MallMate AI</h1>
    <p>Ask naturally &nbsp;·&nbsp; Find easily &nbsp;·&nbsp; Navigate confidently</p>
</div>
""", unsafe_allow_html=True)

# ── Search box ──
col_search, col_btn = st.columns([5, 1])
with col_search:
    query = st.text_input(
        "Search",
        value=st.session_state.last_query,
        placeholder="e.g. 'Where is Zara?'  ·  'Nearest washroom'  ·  'Take me to the food court'",
        label_visibility="collapsed",
    )
with col_btn:
    search_clicked = st.button("🔍 Search", type="primary", use_container_width=True)

# Trigger search
if search_clicked and query.strip():
    st.session_state.last_query = query
    run_search(query.strip(), st.session_state.start_id)
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Results area
# ─────────────────────────────────────────────────────────────────────────────
nlp = st.session_state.nlp_result
route = st.session_state.route_result

col_map, col_details = st.columns([3, 2], gap="medium")

with col_map:
    # ── NLP intent banner ──
    if nlp:
        intent = nlp["intent"]
        msg = nlp.get("message", "")
        if intent == "navigate" and route and route["found"]:
            dest = ID_TO_LOC.get(nlp["destination_id"] or st.session_state.pending_destination_id, {})
            dest_name = dest.get("name", "")
            st.markdown(
                f'<div class="mm-card success">✅ <b>Route found</b> → {dest_name}</div>',
                unsafe_allow_html=True,
            )
        elif intent == "find_nearest" and route and route["found"]:
            dest_name = route.get("destination_name", "")
            st.markdown(
                f'<div class="mm-card success">📍 <b>Nearest found</b>: {dest_name}</div>',
                unsafe_allow_html=True,
            )
        elif intent == "search_category":
            st.markdown(
                f'<div class="mm-card info">🔎 {msg}</div>',
                unsafe_allow_html=True,
            )
        elif intent in ("clarify", "unknown") or nlp.get("needs_clarification"):
            st.markdown(
                f'<div class="mm-card warning">❓ {msg or "Could not identify destination."}</div>',
                unsafe_allow_html=True,
            )
        elif route and not route["found"]:
            st.markdown(
                f'<div class="mm-card error">⚠️ {route.get("error", "Route not found.")}</div>',
                unsafe_allow_html=True,
            )

        # ── Suggestion / candidate buttons ──
        candidates = nlp.get("candidates", [])
        pending_dest = st.session_state.pending_destination_id

        if candidates and not (route and route["found"]) and intent not in ("search_category",):
            st.markdown('<div class="suggestion-label">Did you mean:</div>', unsafe_allow_html=True)
            btn_cols = st.columns(min(3, len(candidates)))
            for i, cand in enumerate(candidates[:6]):
                floor_label = FLOOR_NAMES.get(cand.get("floor"), "?")
                with btn_cols[i % len(btn_cols)]:
                    if st.button(
                        f"📍 {cand['name']}\n({floor_label} Floor)",
                        key=f"cand_{cand['id']}",
                    ):
                        pick_candidate(cand["id"])
                        st.rerun()

        # ── Category results (search_category) ──
        if intent == "search_category" and candidates:
            with st.expander(f"📋 {len(candidates)} location(s) found", expanded=True):
                for c in candidates:
                    loc = ID_TO_LOC.get(c["id"], {})
                    floor_lbl = FLOOR_NAMES.get(loc.get("floor"), "?")
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.write(f"**{loc.get('name', c['id'])}** — {floor_lbl} Floor")
                    with col_b:
                        if st.button("Navigate", key=f"nav_{c['id']}"):
                            pick_candidate(c["id"])
                            st.rerun()

    # ── SVG Map ──
    effective_route = route["path"] if route and route["found"] else None
    effective_start = st.session_state.start_id
    effective_dest = (
        (route.get("destination_id") or nlp.get("destination_id") or st.session_state.pending_destination_id)
        if nlp else None
    )

    map_html = render_map(
        mall_data,
        floor=st.session_state.selected_floor,
        route_path=effective_route,
        start_id=effective_start,
        destination_id=effective_dest,
    )
    components.html(map_html, height=650, scrolling=False)

    if not nlp:
        st.markdown(
            '<div style="text-align:center;color:#90A4AE;font-size:0.85rem;margin-top:6px;">'
            'Type a query above to see your route highlighted on the map.</div>',
            unsafe_allow_html=True,
        )


with col_details:
    # ── Route summary card ──
    if route and route["found"]:
        steps = len(route["directions"])
        dist = route["total_distance"]
        # Estimate walking time (avg 80 units/min)
        est_min = max(1, round(dist / 80))

        path = route["path"]
        start_loc = ID_TO_LOC.get(path[0], {})
        end_loc = ID_TO_LOC.get(path[-1], {})

        st.markdown(
            f"""
            <div class="mm-card success">
                <div style="font-weight:700;font-size:1rem;margin-bottom:10px;">
                    🧭 Route Summary
                </div>
                <div class="route-meta">
                    <div class="route-stat">
                        <div class="val">{steps}</div>
                        <div class="lbl">Steps</div>
                    </div>
                    <div class="route-stat">
                        <div class="val">{dist:.0f}</div>
                        <div class="lbl">Distance (m)</div>
                    </div>
                    <div class="route-stat">
                        <div class="val">~{est_min}</div>
                        <div class="lbl">Min walk</div>
                    </div>
                </div>
                <div style="font-size:0.82rem;color:#546E7A;">
                    <b>From:</b> {start_loc.get('name','?')}
                    ({FLOOR_NAMES.get(start_loc.get('floor',0),'?')} Floor)<br/>
                    <b>To:</b> &nbsp;&nbsp;&nbsp;{end_loc.get('name','?')}
                    ({FLOOR_NAMES.get(end_loc.get('floor',0),'?')} Floor)
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── Floor jump buttons for multi-floor routes ──
        floors_in_route = sorted(
            {ID_TO_LOC[n]["floor"] for n in path if n in ID_TO_LOC}
        )
        if len(floors_in_route) > 1:
            st.markdown("**View route on floor:**")
            fcols = st.columns(len(floors_in_route))
            for i, fnum in enumerate(floors_in_route):
                with fcols[i]:
                    if st.button(
                        f"{FLOOR_NAMES[fnum]} Floor",
                        key=f"jump_floor_{fnum}",
                        type="primary" if st.session_state.selected_floor == fnum else "secondary",
                    ):
                        st.session_state.selected_floor = fnum
                        st.rerun()

        # ── Step-by-step directions ──
        st.markdown("---")
        st.markdown("**📋 Step-by-Step Directions**")
        directions_html = []
        for i, step in enumerate(route["directions"], 1):
            # Colour the step number by type
            if any(w in step.lower() for w in ("escalator", "stairs", "elevator")):
                bg = "#FFF3E0"
                icon = "⬆️" if "up" in step.lower() else ("⬇️" if "down" in step.lower() else "🔄")
            elif "already" in step.lower():
                bg = "#E8F5E9"
                icon = "✅"
            else:
                bg = "#E3F2FD"
                icon = "👣"
            directions_html.append(
                f'<div class="dir-step" style="background:{bg};border-radius:6px;'
                f'padding:8px 10px;margin-bottom:4px;">'
                f'<div class="step-num">{i}</div>'
                f'<div class="step-text">{icon} {step}</div>'
                f'</div>'
            )
        st.markdown(
            f'<div>{"".join(directions_html)}</div>',
            unsafe_allow_html=True,
        )

    elif nlp and not (route and route["found"]):
        # ── No route yet — show quick tips ──
        st.markdown("---")
        st.markdown("**💡 Try these searches**")
        examples = [
            "Where is Zara?",
            "Take me from the main entrance to the food court",
            "Nearest washroom",
            "Find the closest coffee shop",
            "Take me to Starbuks",
            "Show me all restaurants",
            "I want to go to the cinema",
        ]
        for ex in examples:
            if st.button(ex, key=f"ex_{ex}"):
                st.session_state.last_query = ex
                run_search(ex, st.session_state.start_id)
                st.rerun()

    else:
        # ── Initial state — no query yet ──
        st.markdown("""
        <div class="mm-card info">
            <b>🗺️ Welcome to MallMate AI</b><br/>
            <br/>
            Search for any shop, restaurant, washroom, or facility
            using natural language.<br/><br/>
            <b>Example queries:</b><br/>
            • Where is Zara?<br/>
            • Take me from the entrance to the food court<br/>
            • Nearest washroom<br/>
            • Find the closest coffee shop<br/>
            • Show me all restaurants<br/>
            • Take me to Starbuks (handles typos!)
        </div>
        """, unsafe_allow_html=True)

        st.markdown("**🏬 Mall at a glance**")
        cats = {}
        for loc in mall_data["locations"]:
            cats.setdefault(loc["category"], 0)
            cats[loc["category"]] += 1
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            if cat not in ("corridor",):
                st.markdown(f"- **{cat.title()}**: {count} location(s)")
