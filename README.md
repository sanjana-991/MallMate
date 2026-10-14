# 🗺️ MallMate AI

**Ask naturally. Find easily. Navigate confidently.**

MallMate AI is an intelligent indoor mall navigation system built as a college mini-project. It understands natural-language queries, identifies destinations using fuzzy matching, calculates an optimal route through the mall graph, and displays the result on a dynamic SVG floor plan with step-by-step directions.

> **Note:** The mall data is a fictional sample. This is not a verified map of a real shopping mall.

---

## Features

- **Natural-language search** — "Where is Zara?", "Take me from the entrance to the food court", "Nearest washroom"
- **Fuzzy matching** — handles misspellings like "Starbuks" → Starbucks
- **Alias support** — "loo" → washroom, "m&s" → Marks & Spencer, "food hall" → Food Court
- **Category search** — "Show me all cafes", "Find all restaurants on the first floor"
- **Shortest-path routing** — Dijkstra's algorithm on a weighted NetworkX graph
- **Cross-floor navigation** — routes via stairs, escalators, and elevators with proper directions
- **Dynamic SVG map** — route highlighted per floor, start (🟢) and destination (🔴) markers
- **Floor selector** — view any of 3 floors; auto-jumps to the start floor after a search
- **Starting-point flexibility** — pick from a dropdown or type it in natural language
- **Clickable suggestion buttons** — shown when a query is ambiguous
- **39 locations across 3 floors** — Ground, First, Second

---

## Quick Start

### 1. Clone / copy the project

```
mallmate-ai/
├── app.py
├── nlp.py
├── navigation.py
├── map_renderer.py
├── mall_data.json
├── requirements.txt
├── README.md
└── tests/
    ├── conftest.py
    ├── test_navigation.py
    ├── test_nlp.py
    ├── test_map_renderer.py
    └── test_integration.py
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

Requirements: `streamlit`, `networkx`, `rapidfuzz`, `pytest`

### 3. Run the app

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

### 4. Run tests

```bash
python -m pytest tests/ -v
```

All 85 tests pass on Python 3.12.

---

## Example Queries

| Query | What happens |
|---|---|
| `Where is Zara?` | Navigates to Zara on First Floor |
| `Take me from the main entrance to the food court` | Full route with start + destination |
| `Nearest washroom` | Finds closest washroom from your starting point |
| `Take me to Starbuks` | Fuzzy-matches to Starbucks |
| `Show me all cafes` | Lists all cafe locations |
| `I want to go to the cinema` | Routes to Cinema on Second Floor |
| `Take me to m&s` | Alias resolves to Marks & Spencer |
| `Washroom on first floor` | Filters by floor |

---

## Architecture

```
app.py  (Streamlit UI + orchestration)
  │
  ├── nlp.py          (query → structured intent dict)
  │     ├── normalize_query()
  │     ├── resolve_destination()   ← RapidFuzz fuzzy match
  │     ├── find_locations_by_category()
  │     └── process_query()
  │
  ├── navigation.py   (graph → route dict)
  │     ├── build_graph()           ← NetworkX + Dijkstra
  │     ├── find_route()
  │     └── find_nearest()
  │
  ├── map_renderer.py (route → SVG string)
  │     └── render_map()
  │
  └── mall_data.json  (single source of truth)
        ├── locations[]   ← 39 nodes with id, name, category, floor, coords, aliases
        └── connections[] ← 44 edges with from, to, distance, type
```

### Key design decisions

- **No static SVG file** — the map is generated at runtime from `mall_data.json` coordinates, keeping the graph and visualisation permanently in sync.
- **Rule-based NLP only** — no spaCy model download required. All logic is explicit regex patterns + RapidFuzz fuzzy matching.
- **Single source of truth** — `mall_data.json` drives the graph, the map, the NLP alias lookup, and the category search. Data is never duplicated.
- **Graph validation at startup** — `build_graph()` raises `ValueError` if any connection references a missing node or has a negative distance.

---

## Mall Data Format

### Location record

```json
{
  "id": "L19",
  "name": "Zara",
  "category": "retail",
  "floor": 1,
  "aliases": ["zaraa", "zarra", "zara store"],
  "coordinates": {"x": 660, "y": 330},
  "description": "International fashion retail chain",
  "tags": ["clothing", "fashion", "retail"]
}
```

### Connection record

```json
{
  "from": "L07",
  "to": "L24",
  "distance": 50.0,
  "type": "escalator",
  "bidirectional": true
}
```

Connection types: `corridor`, `stairs`, `escalator`, `elevator`

---

## API Reference

### `nlp.process_query(query, mall_data, current_location=None)`

Returns:
```python
{
    "intent":              str,        # navigate | search_category | find_nearest | clarify | unknown
    "start_id":            str | None,
    "destination_id":      str | None,
    "category":            str | None,
    "floor_hint":          int | None,
    "confidence":          float,      # 0.0–1.0
    "needs_clarification": bool,
    "message":             str,
    "candidates":          list[dict]  # [{id, name, floor, score}]
}
```

### `navigation.find_route(mall_data, start_id, destination_id, graph=None)`

Returns:
```python
{
    "found":          bool,
    "path":           list[str],   # ordered location IDs
    "total_distance": float,
    "directions":     list[str],   # human-readable steps
    "error":          str | None
}
```

### `navigation.find_nearest(mall_data, start_id, category, graph=None)`

Same as `find_route` plus `destination_id` and `destination_name` fields.

### `map_renderer.render_map(mall_data, floor, route_path=None, start_id=None, destination_id=None)`

Returns an HTML string (containing SVG) for `st.components.v1.html()`.

---

## Fuzzy Matching

| Score | Behaviour |
|---|---|
| ≥ 80 | Accepted as a confident match |
| 55–79 | Returns suggestion candidates for clarification |
| < 55 | Treated as unknown |

Thresholds are named constants in `nlp.py` (`FUZZY_ACCEPT_THRESHOLD`, `FUZZY_CLARIFY_THRESHOLD`) and can be tuned without changing any other code.

---

## Test Results

```
85 passed in 4.24s (Python 3.12, pytest 9.1.1)
```

| Test file | Tests | Coverage |
|---|---|---|
| `test_navigation.py` | 25 | Graph building, routing, distance, directions, cross-floor, unreachable |
| `test_nlp.py` | 28 | Normalisation, exact/alias/fuzzy matching, category search, intent detection |
| `test_map_renderer.py` | 14 | SVG validity, floor labels, markers, route colours, legend |
| `test_integration.py` | 8 | End-to-end NLP → navigation pipeline |

---

## Limitations

- Starting point must be selected manually (no real-time indoor positioning).
- NLP is rule-based — complex or ambiguous phrasing may not be understood.
- Mall data is fictional — not a verified map of a real mall.
- No voice navigation, live crowd data, or store hours.
- Route distances are abstract units (approx. metres) for a fictional layout.

---

## Future Enhancements

- Real-time indoor positioning via Bluetooth beacons
- Voice navigation (text-to-speech directions)
- Live store opening hours
- Real mall data integration (verified floor plans)
- Multilingual NLP
- Accessibility routing (elevator-only paths)

---

## Team Responsibilities

| Person | Owns |
|---|---|
| **Person 1 — NLP** | `nlp.py`, `tests/test_nlp.py` |
| **Person 2 — Navigation + UI** | `navigation.py`, `map_renderer.py`, `app.py`, `mall_data.json`, `tests/test_navigation.py`, `tests/test_map_renderer.py` |
| **Shared** | `tests/test_integration.py`, `README.md`, `requirements.txt` |

---

## Technology Stack

| Tool | Purpose |
|---|---|
| Python 3.12 | Application logic |
| Streamlit | Web interface |
| NetworkX | Mall graph + Dijkstra routing |
| RapidFuzz | Fuzzy shop-name matching |
| pytest | Automated testing |
| JSON | Mall data storage |
| SVG | Dynamic floor-plan visualisation |
