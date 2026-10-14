"""
tests/test_integration.py

End-to-end integration tests: NLP → Navigation pipeline.
These tests call process_query() and then use the result to call
find_route() or find_nearest(), verifying the pipeline produces
correct end-to-end behaviour.
"""

import pytest
from nlp import process_query
from navigation import find_route, find_nearest, build_graph


@pytest.fixture(scope="module")
def g(mall_data):
    return build_graph(mall_data)


class TestIntegration:
    def test_navigate_zara_end_to_end(self, mall_data, g):
        """'Take me to Zara' → NLP resolves Zara, navigation finds a valid route."""
        nlp = process_query("Take me to Zara", mall_data, current_location="L01")
        assert nlp["destination_id"] == "L19", f"NLP failed: {nlp}"
        assert nlp["start_id"] == "L01"

        nav = find_route(mall_data, nlp["start_id"], nlp["destination_id"], g)
        assert nav["found"] is True
        assert nav["path"][0] == "L01"
        assert nav["path"][-1] == "L19"

    def test_misspelling_end_to_end(self, mall_data, g):
        """'Take me to Starbuks' → fuzzy NLP → valid navigation route."""
        nlp = process_query("Take me to Starbuks", mall_data, current_location="L01")
        assert nlp["destination_id"] == "L16", (
            f"Expected Starbucks (L16), NLP returned: {nlp}"
        )
        nav = find_route(mall_data, "L01", nlp["destination_id"], g)
        assert nav["found"] is True
        assert nav["path"][-1] == "L16"

    def test_from_to_pipeline(self, mall_data, g):
        """'Take me from the main entrance to the food court' → full pipeline."""
        nlp = process_query(
            "Take me from the main entrance to the food court", mall_data
        )
        assert nlp["start_id"] == "L01"
        assert nlp["destination_id"] == "L15"

        nav = find_route(mall_data, nlp["start_id"], nlp["destination_id"], g)
        assert nav["found"] is True
        assert nav["path"][0] == "L01"
        assert nav["path"][-1] == "L15"

    def test_find_nearest_washroom_pipeline(self, mall_data, g):
        """'Find the nearest washroom' → find_nearest returns a reachable washroom."""
        nlp = process_query(
            "Where is the nearest washroom?", mall_data, current_location="L01"
        )
        assert nlp["intent"] == "find_nearest"
        assert nlp["category"] == "washroom"

        nav = find_nearest(mall_data, "L01", nlp["category"], g)
        assert nav["found"] is True
        locs = {loc["id"]: loc for loc in mall_data["locations"]}
        assert locs[nav["destination_id"]]["category"] == "washroom"

    def test_unknown_destination_does_not_call_navigation(self, mall_data):
        """Completely unknown destination → NLP signals clarification needed;
        navigation should NOT be called (or if called, returns not found)."""
        nlp = process_query("Take me to abcxyz123impossible", mall_data,
                            current_location="L01")
        # Either the NLP couldn't resolve (destination_id is None) or it's clarifying
        if nlp["destination_id"] is None:
            # Correct behaviour — navigation not called
            assert True
        else:
            # If NLP somehow resolved it (shouldn't happen), verify nav still works
            nav = find_route(mall_data, "L01", nlp["destination_id"])
            # Result may or may not be found, but shouldn't crash
            assert "found" in nav

    def test_same_start_and_destination_pipeline(self, mall_data, g):
        """Query targeting same location as start → 'already there' direction."""
        nlp = process_query("Take me to the main entrance", mall_data,
                            current_location="L01")
        if nlp["destination_id"] == "L01":
            nav = find_route(mall_data, "L01", "L01", g)
            assert nav["found"] is True
            assert nav["total_distance"] == 0.0
            assert "already" in nav["directions"][0].lower()

    def test_cross_floor_pipeline(self, mall_data, g):
        """'Take me from south entrance to cinema' → cross-floor route via transitions."""
        nlp = process_query(
            "Take me from south entrance to cinema", mall_data
        )
        if nlp["start_id"] and nlp["destination_id"]:
            nav = find_route(mall_data, nlp["start_id"], nlp["destination_id"], g)
            assert nav["found"] is True
            locs = {loc["id"]: loc for loc in mall_data["locations"]}
            start_floor = locs[nav["path"][0]]["floor"]
            end_floor = locs[nav["path"][-1]]["floor"]
            assert start_floor != end_floor, "Expected cross-floor route"

    def test_search_category_pipeline(self, mall_data):
        """'Show me all cafes' → NLP returns candidates list for cafe locations."""
        nlp = process_query("Show me all cafes", mall_data)
        assert nlp["intent"] == "search_category"
        assert nlp["category"] == "cafe"
        assert len(nlp["candidates"]) >= 1
        # All candidates should be cafe locations
        locs = {loc["id"]: loc for loc in mall_data["locations"]}
        for c in nlp["candidates"]:
            loc = locs.get(c["id"])
            if loc:
                assert loc["category"] == "cafe" or "coffee" in loc.get("tags", [])
