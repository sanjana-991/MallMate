"""
nlp.py — Natural-language query processing for MallMate AI.

Responsibilities:
  - Normalize raw user input.
  - Detect query intent (navigate, search_category, find_nearest, clarify, unknown).
  - Extract destination names, start names, category hints, and floor hints.
  - Resolve name fragments to stable location IDs using exact matching,
    alias lookup, and fuzzy matching (RapidFuzz).
  - Return structured dicts suitable for the navigation engine.

Fuzzy thresholds (tune via constants):
  FUZZY_ACCEPT_THRESHOLD  — score ≥ this → confident match
  FUZZY_CLARIFY_THRESHOLD — score in [this, accept) → offer candidates
  Below FUZZY_CLARIFY_THRESHOLD → unknown / no suggestion

Public API
----------
process_query(query, mall_data, current_location=None)  -> dict
find_locations_by_category(category, mall_data, floor=None) -> list[dict]
resolve_destination(query_fragment, mall_data)           -> dict
normalize_query(query)                                   -> str
"""

import re
from rapidfuzz import fuzz, process as fuzz_process

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

FUZZY_ACCEPT_THRESHOLD: int = 80   # ≥ this → accepted as resolved
FUZZY_CLARIFY_THRESHOLD: int = 55  # ≥ this → show candidates for clarification
FUZZY_TOP_N: int = 5               # Max candidates returned

# ---------------------------------------------------------------------------
# Static knowledge: categories, floors, intent patterns
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "washroom":  ["washroom", "toilet", "restroom", "bathroom", "loo", "wc", "lavatory",
                  "wash room", "rest room"],
    "food":      ["food court", "food", "eat", "restaurant", "dining", "dine", "hungry",
                  "meal", "lunch", "dinner", "breakfast", "fast food", "burger",
                  "pizza", "chicken", "sandwich", "sub", "kfc", "mcdonalds",
                  "mcdonald", "subway", "pizza hut"],
    "cafe":      ["cafe", "coffee", "caffeine", "latte", "espresso", "starbucks",
                  "starbuks", "coffee shop", "tea"],
    "cinema":    ["cinema", "movie", "film", "theatre", "theater", "multiplex",
                  "cinemax", "screen"],
    "leisure":   ["bowling", "arcade", "gaming", "game zone", "game center",
                  "entertainment", "amusement", "fun", "activity", "sports"],
    "retail":    ["shop", "store", "shopping", "buy", "purchase", "clothes", "clothing",
                  "fashion", "apparel", "wear", "zara", "h&m", "hm",
                  "marks & spencer", "marks and spencer", "levi", "nike", "adidas"],
    "entrance":  ["entrance", "entry", "exit", "door", "gate", "way out"],
    "elevator":  ["elevator", "lift", "accessible", "wheelchair"],
    "escalator": ["escalator", "moving stairs", "travelator"],
    "stairs":    ["stairs", "staircase", "steps", "stairway"],
    "atm":       ["atm", "cash machine", "cash point", "cash", "money", "withdraw",
                  "bank machine"],
    "landmark":  ["information desk", "info desk", "info", "help desk",
                  "reception", "customer service"],
}

FLOOR_KEYWORDS: dict[int, list[str]] = {
    0: ["ground floor", "g floor", "floor 0", "floor g", "ground level",
        "ground", "level 0"],
    1: ["first floor", "1st floor", "floor 1", "floor one", "first level",
        "level 1", "1st level"],
    2: ["second floor", "2nd floor", "floor 2", "floor two", "second level",
        "level 2", "2nd level"],
}

# Phrases signalling find_nearest intent
NEAREST_KEYWORDS = [
    "nearest", "closest", "nearby", "near me", "close to", "closest to",
    "near the", "near a",
]

# Phrases signalling search_category intent
SEARCH_ALL_PATTERNS = [
    r"show (?:me )?all",
    r"list (?:all|the)",
    r"all .+ (?:on|at) (?:the )?floor",
    r"what .+ (?:are|is) (?:here|available|on|around)",
    r"any .+ (?:nearby|around|here|available)",
    r"find all",
    r"where are (?:all )?(?:the )?",
]

# Phrases strongly signalling navigate intent (ordered by specificity)
NAVIGATE_PATTERNS = [
    r"take me (?:to|from)",
    r"navigate (?:to|from)",
    r"get (?:me )?(?:to|from|directions?)",
    r"directions? (?:to|from)",
    r"how (?:do|can|would) i (?:get|go|reach|find) (?:to )?",
    r"i (?:want|need|would like) to (?:go|get) to",
    r"i(?:'m| am) (?:going|heading|trying to get) to",
    r"route (?:to|from)",
    r"path (?:to|from)",
    r"where (?:is|can i find|are|do i find)",
    r"find (?:a |the )?",
]

# Regex for "from X to Y" and "to Y from X" extraction
_FROM_TO_RE = re.compile(
    r"\bfrom\s+(.+?)\s+to\s+(.+?)(?:\s+on\s+|\s+at\s+|\s*$)", re.IGNORECASE
)
_TO_FROM_RE = re.compile(
    r"\bto\s+(.+?)\s+from\s+(.+?)(?:\s+on\s+|\s+at\s+|\s*$)", re.IGNORECASE
)

# Patterns to strip from a query before extracting a destination name
_STRIP_PREFIXES = [
    r"(?:can you |please |could you )?take me (?:to|from)\s+",
    r"(?:can you |please )?navigate (?:to|from)\s+",
    r"(?:can you |please )?go to\s+",
    r"(?:can you |please )?get (?:me )?(?:to|directions? to)\s+",
    r"i (?:want|need|would like) to (?:go|get) to\s+",
    r"i(?:'m| am) (?:going|heading) to\s+",
    r"directions? to\s+",
    r"route to\s+",
    r"path to\s+",
    r"where (?:is|can i find|are|do i find)\s+",
    r"find\s+",
    r"looking for\s+",
    r"searching for\s+",
    r"show me\s+",
    r"i need\s+",
]
_STRIP_ARTICLES = re.compile(r"\b(?:a|an|the|some|any|please|me)\b", re.IGNORECASE)
_FLOOR_SUFFIX = re.compile(
    r"\s+(?:on|at|on the|at the)\s+(?:the\s+)?(?:ground|first|second|1st|2nd|"
    r"floor\s*\d|floor\s*(?:one|two|three))\s*(?:floor)?\s*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_name_to_id(mall_data: dict) -> dict[str, str]:
    """
    Build a flat dict mapping every searchable name/alias (lowercase) to
    its location ID. Later entries override earlier ones (aliases last).
    """
    mapping: dict[str, str] = {}
    for loc in mall_data["locations"]:
        mapping[loc["name"].lower()] = loc["id"]
        for alias in loc.get("aliases", []):
            mapping[alias.lower()] = loc["id"]
    return mapping


def _id_to_loc(mall_data: dict) -> dict[str, dict]:
    return {loc["id"]: loc for loc in mall_data["locations"]}


def _detect_floor(query: str) -> int | None:
    """Return floor number if a floor keyword appears in the (normalized) query."""
    for floor_num, keywords in FLOOR_KEYWORDS.items():
        for kw in sorted(keywords, key=len, reverse=True):  # longer phrases first
            if kw in query:
                return floor_num
    return None


def _detect_category(query: str) -> str | None:
    """Return the first matching category from CATEGORY_KEYWORDS."""
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in sorted(keywords, key=len, reverse=True):
            if kw in query:
                return category
    return None


def _detect_intent(query: str) -> str:
    """Classify query intent from rule patterns."""
    # find_nearest takes priority
    if any(kw in query for kw in NEAREST_KEYWORDS):
        return "find_nearest"
    # search_category
    for pat in SEARCH_ALL_PATTERNS:
        if re.search(pat, query):
            return "search_category"
    # navigate
    for pat in NAVIGATE_PATTERNS:
        if re.search(pat, query):
            return "navigate"
    return "unknown"


def _strip_intent_phrases(query: str) -> str:
    """Remove intent-signalling phrases to isolate the destination fragment."""
    result = query
    for prefix in _STRIP_PREFIXES:
        result = re.sub(prefix, "", result, flags=re.IGNORECASE).strip()
    # Remove floor suffixes
    result = _FLOOR_SUFFIX.sub("", result).strip()
    # Remove stray articles
    result = _STRIP_ARTICLES.sub("", result).strip()
    # Collapse whitespace
    result = re.sub(r"\s+", " ", result).strip()
    return result


def _dedupe_candidates(candidates: list[dict], name_to_id: dict, id_to_loc: dict) -> list[dict]:
    """
    Deduplicate by location ID and enrich with display name.
    Candidates list has {name_key, score} from rapidfuzz.
    """
    seen: set[str] = set()
    result = []
    for name_key, score, _ in candidates:
        loc_id = name_to_id.get(name_key)
        if loc_id and loc_id not in seen:
            seen.add(loc_id)
            loc = id_to_loc.get(loc_id, {})
            result.append({
                "id": loc_id,
                "name": loc.get("name", name_key),
                "floor": loc.get("floor"),
                "score": round(score / 100.0, 3),
            })
    return result


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def normalize_query(query: str) -> str:
    """
    Lowercase, strip excess whitespace, and remove non-alphanumeric punctuation
    (except apostrophes and ampersands, which appear in shop names).
    """
    query = query.lower().strip()
    query = re.sub(r"[^\w\s'&]", " ", query)
    query = re.sub(r"\s+", " ", query)
    return query.strip()  # final strip removes any trailing space left by punctuation removal


def resolve_destination(query_fragment: str, mall_data: dict) -> dict:
    """
    Attempt to resolve a name fragment to a stable location ID.

    Strategy (in order):
      1. Exact match against names and aliases.
      2. RapidFuzz WRatio fuzzy match.
         ≥ FUZZY_ACCEPT_THRESHOLD  → resolved = True
         ≥ FUZZY_CLARIFY_THRESHOLD → resolved = False, candidates populated
         < FUZZY_CLARIFY_THRESHOLD → resolved = False, candidates empty

    Returns
    -------
    {
        "resolved"    : bool,
        "location_id" : str | None,
        "score"       : float,        # Best match score in [0, 1]
        "candidates"  : list[dict]    # Non-empty when unresolved but close
    }
    """
    fragment = normalize_query(query_fragment).strip()
    if not fragment:
        return {"resolved": False, "location_id": None, "score": 0.0, "candidates": []}

    name_to_id = _build_name_to_id(mall_data)
    id_to_loc = _id_to_loc(mall_data)

    # 1. Exact match
    if fragment in name_to_id:
        loc_id = name_to_id[fragment]
        return {
            "resolved": True,
            "location_id": loc_id,
            "score": 1.0,
            "candidates": [],
        }

    # 2. Fuzzy match
    matches = fuzz_process.extract(
        fragment,
        list(name_to_id.keys()),
        scorer=fuzz.WRatio,
        limit=FUZZY_TOP_N,
    )

    if not matches:
        return {"resolved": False, "location_id": None, "score": 0.0, "candidates": []}

    best_name, best_score, _ = matches[0]

    if best_score >= FUZZY_ACCEPT_THRESHOLD:
        loc_id = name_to_id[best_name]
        return {
            "resolved": True,
            "location_id": loc_id,
            "score": round(best_score / 100.0, 3),
            "candidates": [],
        }

    if best_score >= FUZZY_CLARIFY_THRESHOLD:
        candidates = _dedupe_candidates(matches, name_to_id, id_to_loc)
        return {
            "resolved": False,
            "location_id": None,
            "score": round(best_score / 100.0, 3),
            "candidates": candidates,
        }

    return {"resolved": False, "location_id": None, "score": round(best_score / 100.0, 3), "candidates": []}


def find_locations_by_category(
    category: str,
    mall_data: dict,
    floor: int | None = None,
) -> list[dict]:
    """
    Return all location records whose category or tags match the given string.

    Parameters
    ----------
    category : Category name (e.g. "washroom") or tag keyword (e.g. "coffee").
    mall_data: Parsed mall_data.json dict.
    floor    : If given, restrict to locations on that floor only.

    Returns
    -------
    List of matching location dicts. Empty list if none found.
    """
    results = []
    category_lower = category.lower()
    for loc in mall_data["locations"]:
        match = (
            loc["category"].lower() == category_lower
            or category_lower in [t.lower() for t in loc.get("tags", [])]
        )
        if match:
            if floor is None or loc["floor"] == floor:
                results.append(loc)
    return results


def process_query(
    query: str,
    mall_data: dict,
    current_location: str | None = None,
) -> dict:
    """
    Parse a natural-language query and return structured intent data.

    Parameters
    ----------
    query            : Raw user input string.
    mall_data        : Parsed mall_data.json dict.
    current_location : Location ID of the user's manually selected start (or None).

    Returns
    -------
    {
        "intent"             : str,          # navigate | search_category | find_nearest
                                             #   | clarify | unknown
        "start_id"           : str | None,   # Resolved start location ID
        "destination_id"     : str | None,   # Resolved destination location ID
        "category"           : str | None,   # Detected category
        "floor_hint"         : int | None,   # Floor extracted from query
        "confidence"         : float,        # 0–1; fuzzy score or rule certainty
        "needs_clarification": bool,
        "message"            : str,          # Human-readable status/prompt
        "candidates"         : list[dict]    # Suggestion buttons when clarifying
    }
    """
    normalized = normalize_query(query)

    floor_hint = _detect_floor(normalized)
    category = _detect_category(normalized)
    intent = _detect_intent(normalized)

    # Upgrade 'unknown' to 'search_category' if we found a category
    if intent == "unknown" and category:
        intent = "search_category"

    start_id: str | None = current_location
    destination_id: str | None = None
    candidates: list[dict] = []
    needs_clarification = False
    message = ""
    confidence = 0.0

    # ------------------------------------------------------------------ #
    # 1. Try "from X to Y" / "to Y from X" patterns first                #
    # ------------------------------------------------------------------ #
    from_to_match = _FROM_TO_RE.search(normalized)
    to_from_match = _TO_FROM_RE.search(normalized)

    if from_to_match:
        from_frag = from_to_match.group(1).strip()
        to_frag = from_to_match.group(2).strip()
        sr = resolve_destination(from_frag, mall_data)
        dr = resolve_destination(to_frag, mall_data)
        if sr["resolved"]:
            start_id = sr["location_id"]
        if dr["resolved"]:
            destination_id = dr["location_id"]
            confidence = dr["score"]
        elif dr["candidates"]:
            candidates = dr["candidates"]
            needs_clarification = True
            intent = "clarify"
        intent = intent if intent != "unknown" else "navigate"

    elif to_from_match:
        to_frag = to_from_match.group(1).strip()
        from_frag = to_from_match.group(2).strip()
        sr = resolve_destination(from_frag, mall_data)
        dr = resolve_destination(to_frag, mall_data)
        if sr["resolved"]:
            start_id = sr["location_id"]
        if dr["resolved"]:
            destination_id = dr["location_id"]
            confidence = dr["score"]
        elif dr["candidates"]:
            candidates = dr["candidates"]
            needs_clarification = True
            intent = "clarify"
        intent = intent if intent != "unknown" else "navigate"

    # ------------------------------------------------------------------ #
    # 2. No from/to pattern — extract a single destination                #
    # ------------------------------------------------------------------ #
    if destination_id is None and not needs_clarification:
        if intent in ("navigate", "find_nearest", "unknown"):
            frag = _strip_intent_phrases(normalized)
            # Remove category keywords from fragment if the fragment is ONLY a category
            # (e.g. "where is the washroom" → frag = "washroom" → resolve via category)
            if frag:
                dr = resolve_destination(frag, mall_data)
                if dr["resolved"]:
                    destination_id = dr["location_id"]
                    confidence = dr["score"]
                    intent = intent if intent != "unknown" else "navigate"
                elif dr["candidates"]:
                    candidates = dr["candidates"]
                    needs_clarification = True
                    intent = "clarify"

    # ------------------------------------------------------------------ #
    # 3. search_category path                                              #
    # ------------------------------------------------------------------ #
    if intent == "search_category" and category:
        locs = find_locations_by_category(category, mall_data, floor_hint)
        if locs:
            candidates = [
                {"id": l["id"], "name": l["name"], "floor": l["floor"], "score": 1.0}
                for l in locs
            ]
            floor_str = f" on {['Ground', 'First', 'Second'][floor_hint]} Floor" if floor_hint is not None else ""
            message = f"Found {len(locs)} '{category}' location(s){floor_str}."
        else:
            floor_str = f" on floor {floor_hint}" if floor_hint is not None else ""
            message = f"No '{category}' locations found{floor_str}."
            needs_clarification = True

    # ------------------------------------------------------------------ #
    # 4. find_nearest path                                                 #
    # ------------------------------------------------------------------ #
    elif intent == "find_nearest":
        if category:
            message = f"Finding the nearest '{category}' from your starting point."
        else:
            needs_clarification = True
            message = "What type of place are you looking for? (e.g. washroom, cafe, ATM)"

    # ------------------------------------------------------------------ #
    # 5. navigate with no destination — prompt clarification              #
    # ------------------------------------------------------------------ #
    elif intent == "navigate" and destination_id is None and not needs_clarification:
        needs_clarification = True
        message = (
            "I couldn't identify a specific destination. "
            "Try: 'Take me to Zara' or 'Find the nearest washroom'."
        )
        intent = "unknown"

    # ------------------------------------------------------------------ #
    # 6. clarify message                                                   #
    # ------------------------------------------------------------------ #
    if needs_clarification and not message:
        message = "Did you mean one of these places?"

    # ------------------------------------------------------------------ #
    # 7. Successful navigate message                                       #
    # ------------------------------------------------------------------ #
    if intent == "navigate" and destination_id and not message:
        id_to_loc = _id_to_loc(mall_data)
        dest_name = id_to_loc.get(destination_id, {}).get("name", destination_id)
        message = f"Destination identified: {dest_name}."

    return {
        "intent": intent,
        "start_id": start_id,
        "destination_id": destination_id,
        "category": category,
        "floor_hint": floor_hint,
        "confidence": round(confidence, 3),
        "needs_clarification": needs_clarification,
        "message": message,
        "candidates": candidates,
    }
