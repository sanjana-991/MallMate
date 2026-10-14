"""
tests/test_nlp.py

Tests for nlp.py:
  - normalize_query
  - resolve_destination: exact, alias, fuzzy, unknown
  - find_locations_by_category: category, floor filtering
  - process_query: intent detection, from/to extraction, find_nearest, clarify
"""

import pytest
from nlp import (
    normalize_query,
    resolve_destination,
    find_locations_by_category,
    process_query,
    FUZZY_ACCEPT_THRESHOLD,
)


# ---------------------------------------------------------------------------
# normalize_query
# ---------------------------------------------------------------------------

class TestNormalizeQuery:
    def test_lowercase(self):
        assert normalize_query("WHERE IS ZARA?") == "where is zara"

    def test_strips_whitespace(self):
        assert normalize_query("  find the ATM  ") == "find the atm"

    def test_collapses_spaces(self):
        assert normalize_query("take  me   to   food court") == "take me to food court"

    def test_removes_punctuation(self):
        # Apostrophes and & should be preserved; other punctuation removed
        result = normalize_query("Where's H&M?")
        assert "?" not in result
        assert "h&m" in result or "hm" in result  # & preserved or collapsed


# ---------------------------------------------------------------------------
# resolve_destination
# ---------------------------------------------------------------------------

class TestResolveDestination:
    def test_exact_match_by_name(self, mall_data):
        """'Zara' should resolve exactly to L19."""
        result = resolve_destination("Zara", mall_data)
        assert result["resolved"] is True
        assert result["location_id"] == "L19"
        assert result["score"] == 1.0

    def test_exact_match_case_insensitive(self, mall_data):
        """'zara' (lowercase) should still resolve."""
        result = resolve_destination("zara", mall_data)
        assert result["resolved"] is True
        assert result["location_id"] == "L19"

    def test_alias_resolution(self, mall_data):
        """'mcdonald' (alias) should resolve to McDonald's (L10)."""
        result = resolve_destination("mcdonald", mall_data)
        assert result["resolved"] is True
        assert result["location_id"] == "L10"

    def test_alias_food_court(self, mall_data):
        """'food hall' (alias) should resolve to Food Court (L15)."""
        result = resolve_destination("food hall", mall_data)
        assert result["resolved"] is True
        assert result["location_id"] == "L15"

    def test_fuzzy_misspelling_starbucks(self, mall_data):
        """'Starbuks' should fuzzy-match to Starbucks (L16) with score >= threshold."""
        result = resolve_destination("Starbuks", mall_data)
        assert result["resolved"] is True
        assert result["location_id"] == "L16"
        assert result["score"] >= FUZZY_ACCEPT_THRESHOLD / 100.0

    def test_fuzzy_misspelling_adidas(self, mall_data):
        """'addidas' (alias) should resolve to Adidas (L33)."""
        result = resolve_destination("addidas", mall_data)
        assert result["resolved"] is True
        assert result["location_id"] == "L33"

    def test_fuzzy_misspelling_zara(self, mall_data):
        """'zaraa' (alias) should resolve to Zara."""
        result = resolve_destination("zaraa", mall_data)
        assert result["resolved"] is True
        assert result["location_id"] == "L19"

    def test_unknown_destination_returns_unresolved(self, mall_data):
        """A completely nonsense name should return resolved=False."""
        result = resolve_destination("abcxyzqwerty12345", mall_data)
        assert result["resolved"] is False
        assert result["location_id"] is None

    def test_candidates_provided_for_partial_match(self, mall_data):
        """A partial/ambiguous name should return candidates when it partially matches."""
        result = resolve_destination("marks", mall_data)
        # "Marks & Spencer" should be in the candidates or resolved
        if result["resolved"]:
            assert result["location_id"] == "L20"
        else:
            ids = [c["id"] for c in result["candidates"]]
            assert "L20" in ids, f"L20 not in candidates: {result['candidates']}"

    def test_empty_fragment(self, mall_data):
        """Empty string should return resolved=False gracefully."""
        result = resolve_destination("", mall_data)
        assert result["resolved"] is False

    def test_main_entrance_resolves(self, mall_data):
        """'main entrance' should resolve to L01."""
        result = resolve_destination("main entrance", mall_data)
        assert result["resolved"] is True
        assert result["location_id"] == "L01"

    def test_washroom_alias_loo(self, mall_data):
        """'loo' alias should resolve to a washroom location."""
        result = resolve_destination("loo", mall_data)
        # Multiple washrooms have 'loo' in aliases; any washroom is acceptable
        if result["resolved"]:
            from navigation import load_mall_data
            locs = {loc["id"]: loc for loc in mall_data["locations"]}
            assert locs[result["location_id"]]["category"] == "washroom"
        else:
            # Candidates should include washrooms
            assert len(result["candidates"]) > 0


# ---------------------------------------------------------------------------
# find_locations_by_category
# ---------------------------------------------------------------------------

class TestFindLocationsByCategory:
    def test_find_washrooms(self, mall_data):
        """Should return all 3 washrooms (one per floor)."""
        results = find_locations_by_category("washroom", mall_data)
        assert len(results) == 3
        for r in results:
            assert r["category"] == "washroom"

    def test_find_washrooms_floor_filter(self, mall_data):
        """Filtering by floor=1 should return only the First Floor washroom."""
        results = find_locations_by_category("washroom", mall_data, floor=1)
        assert len(results) == 1
        assert results[0]["id"] == "L22"
        assert results[0]["floor"] == 1

    def test_find_cafes(self, mall_data):
        """Should find at least one cafe (Starbucks)."""
        results = find_locations_by_category("cafe", mall_data)
        assert len(results) >= 1
        ids = [r["id"] for r in results]
        assert "L16" in ids  # Starbucks

    def test_find_retail(self, mall_data):
        """Should find multiple retail locations."""
        results = find_locations_by_category("retail", mall_data)
        assert len(results) >= 5  # H&M, Zara, M&S, Levi's, Nike, Adidas

    def test_empty_category(self, mall_data):
        """Non-existent category should return empty list."""
        results = find_locations_by_category("unicorn_category", mall_data)
        assert results == []

    def test_floor_filter_no_results(self, mall_data):
        """Cinema is only on floor 2; filtering for cinema on floor 0 returns empty."""
        results = find_locations_by_category("cinema", mall_data, floor=0)
        assert results == []

    def test_tag_keyword_match(self, mall_data):
        """'coffee' tag should match Starbucks (tagged 'coffee')."""
        results = find_locations_by_category("coffee", mall_data)
        ids = [r["id"] for r in results]
        assert "L16" in ids, "Starbucks not found via 'coffee' tag"


# ---------------------------------------------------------------------------
# process_query
# ---------------------------------------------------------------------------

class TestProcessQuery:
    def test_navigate_explicit_name(self, mall_data):
        """'Where is Zara?' → intent=navigate, destination_id=L19."""
        result = process_query("Where is Zara?", mall_data)
        assert result["intent"] == "navigate"
        assert result["destination_id"] == "L19"
        assert result["needs_clarification"] is False

    def test_navigate_misspelling(self, mall_data):
        """'Take me to Starbuks' → resolves to Starbucks (L16)."""
        result = process_query("Take me to Starbuks", mall_data)
        assert result["destination_id"] == "L16", (
            f"Expected L16, got {result['destination_id']}. "
            f"Full result: {result}"
        )

    def test_from_to_pattern(self, mall_data):
        """'Take me from the main entrance to the food court' → start=L01, dest=L15."""
        result = process_query(
            "Take me from the main entrance to the food court", mall_data
        )
        assert result["start_id"] == "L01", f"start_id: {result['start_id']}"
        assert result["destination_id"] == "L15", f"dest_id: {result['destination_id']}"

    def test_current_location_used_as_start(self, mall_data):
        """When current_location is set and no start is in the query, it propagates."""
        result = process_query("Where is Zara?", mall_data, current_location="L01")
        assert result["start_id"] == "L01"

    def test_category_search_intent(self, mall_data):
        """'Show me all cafes' → intent=search_category, category=cafe."""
        result = process_query("Show me all cafes", mall_data)
        assert result["intent"] == "search_category"
        assert result["category"] == "cafe"
        assert len(result["candidates"]) >= 1

    def test_find_nearest_washroom(self, mall_data):
        """'Where is the nearest washroom?' → intent=find_nearest, category=washroom."""
        result = process_query("Where is the nearest washroom?", mall_data)
        assert result["intent"] == "find_nearest"
        assert result["category"] == "washroom"

    def test_find_nearest_coffee(self, mall_data):
        """'Find the closest coffee shop' → intent=find_nearest, category=cafe."""
        result = process_query("Find the closest coffee shop", mall_data)
        assert result["intent"] == "find_nearest"
        assert result["category"] in ("cafe", "food")

    def test_floor_hint_extraction(self, mall_data):
        """'Washroom on first floor' → floor_hint=1."""
        result = process_query("Washroom on first floor", mall_data)
        assert result["floor_hint"] == 1

    def test_ambiguous_query_returns_candidates(self, mall_data):
        """A partial name that matches multiple places should return candidates."""
        result = process_query("Take me to the store", mall_data)
        # Either clarification or a resolved destination is acceptable,
        # but if unresolved, candidates must be provided
        if result["needs_clarification"]:
            assert len(result["candidates"]) > 0 or result["message"]

    def test_completely_unknown_query(self, mall_data):
        """Gibberish query should return unknown intent or clarification."""
        result = process_query("qwerty zxcvbn abcxyz", mall_data)
        assert result["intent"] in ("unknown", "clarify")

    def test_category_keyword_washroom(self, mall_data):
        """'I need to use the toilet' → category=washroom detected."""
        result = process_query("I need to use the toilet", mall_data)
        assert result["category"] == "washroom"

    def test_navigate_cinema(self, mall_data):
        """'I want to go to the cinema' → destination resolves to Cinema (L29)."""
        result = process_query("I want to go to the cinema", mall_data)
        assert result["destination_id"] == "L29", (
            f"Expected L29, got {result['destination_id']}. Result: {result}"
        )

    def test_marks_and_spencer_alias(self, mall_data):
        """'Take me to m&s' (alias) → resolves to Marks & Spencer (L20)."""
        result = process_query("Take me to m&s", mall_data)
        assert result["destination_id"] == "L20", (
            f"Expected L20 for 'm&s', got {result['destination_id']}. Result: {result}"
        )

    def test_food_court_by_alias(self, mall_data):
        """'Where is the food hall?' (alias) → destination=L15."""
        result = process_query("Where is the food hall?", mall_data)
        assert result["destination_id"] == "L15"
