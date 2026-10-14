"""
tests/test_navigation.py

Tests for navigation.py:
  - build_graph: validation, node count, edge count, warnings
  - find_route: exact paths, distances, directions, edge cases
  - find_nearest: category search, reachability
"""

import pytest
import networkx as nx
from navigation import build_graph, find_route, find_nearest


# ---------------------------------------------------------------------------
# build_graph tests
# ---------------------------------------------------------------------------

class TestBuildGraph:
    def test_node_count(self, mall_data, graph):
        """Graph should have exactly one node per location record."""
        expected = len(mall_data["locations"])
        assert graph.number_of_nodes() == expected, (
            f"Expected {expected} nodes, got {graph.number_of_nodes()}"
        )

    def test_edge_count(self, mall_data, graph):
        """Graph should have exactly one edge per bidirectional connection."""
        expected = len(mall_data["connections"])
        assert graph.number_of_edges() == expected, (
            f"Expected {expected} edges, got {graph.number_of_edges()}"
        )

    def test_node_attributes(self, graph):
        """Each node should carry at minimum 'name', 'floor', and 'category'."""
        for node_id, data in graph.nodes(data=True):
            assert "name" in data, f"Node {node_id} missing 'name'"
            assert "floor" in data, f"Node {node_id} missing 'floor'"
            assert "category" in data, f"Node {node_id} missing 'category'"

    def test_edge_attributes(self, graph):
        """Each edge should carry 'distance' (>=0) and 'type'."""
        for u, v, data in graph.edges(data=True):
            assert "distance" in data, f"Edge {u}-{v} missing 'distance'"
            assert "type" in data, f"Edge {u}-{v} missing 'type'"
            assert data["distance"] >= 0, f"Edge {u}-{v} has negative distance"

    def test_all_nodes_reachable_from_main_entrance(self, graph):
        """All nodes should be reachable from Main Entrance (L01) — graph is connected."""
        # Verify graph is connected
        assert nx.is_connected(graph), "Mall graph is not fully connected — some nodes are unreachable."

    def test_invalid_connection_missing_node_raises(self, mall_data):
        """build_graph should raise ValueError if a connection references a non-existent node."""
        bad_data = {
            "mall": mall_data["mall"],
            "locations": mall_data["locations"][:5],  # only first 5 locations
            "connections": [
                {"from": "L01", "to": "LXXX", "distance": 10.0,
                 "type": "corridor", "bidirectional": True}
            ],
        }
        with pytest.raises(ValueError, match="LXXX"):
            build_graph(bad_data)

    def test_invalid_negative_distance_raises(self, mall_data):
        """build_graph should raise ValueError for negative edge distance."""
        bad_data = {
            "mall": mall_data["mall"],
            "locations": mall_data["locations"],
            "connections": [
                {"from": "L01", "to": "L03", "distance": -5.0,
                 "type": "corridor", "bidirectional": True}
            ],
        }
        with pytest.raises(ValueError, match="[Nn]egative"):
            build_graph(bad_data)


# ---------------------------------------------------------------------------
# find_route tests
# ---------------------------------------------------------------------------

class TestFindRoute:
    def test_valid_route_found(self, mall_data, graph):
        """Route from Main Entrance (L01) to Food Court (L15) should be found."""
        result = find_route(mall_data, "L01", "L15", graph)
        assert result["found"] is True
        assert len(result["path"]) >= 2
        assert result["path"][0] == "L01"
        assert result["path"][-1] == "L15"

    def test_route_starts_and_ends_correctly(self, mall_data, graph):
        """Route path must start with start_id and end with destination_id."""
        result = find_route(mall_data, "L02", "L29", graph)
        assert result["found"] is True
        assert result["path"][0] == "L02"
        assert result["path"][-1] == "L29"

    def test_route_total_distance_positive(self, mall_data, graph):
        """Total distance for a non-trivial route should be > 0."""
        result = find_route(mall_data, "L01", "L15", graph)
        assert result["found"] is True
        assert result["total_distance"] > 0

    def test_route_distance_equals_sum_of_edges(self, mall_data, graph):
        """total_distance should equal the sum of edge weights along the path."""
        result = find_route(mall_data, "L01", "L15", graph)
        assert result["found"] is True
        path = result["path"]
        manual_dist = sum(
            graph[path[i]][path[i + 1]]["distance"]
            for i in range(len(path) - 1)
        )
        assert abs(result["total_distance"] - manual_dist) < 0.01, (
            f"Reported distance {result['total_distance']} != "
            f"sum of edges {manual_dist}"
        )

    def test_same_start_and_destination(self, mall_data, graph):
        """Route from a node to itself should be trivially found with distance 0."""
        result = find_route(mall_data, "L01", "L01", graph)
        assert result["found"] is True
        assert result["path"] == ["L01"]
        assert result["total_distance"] == 0.0
        assert len(result["directions"]) == 1
        assert "already" in result["directions"][0].lower()

    def test_unknown_start_id(self, mall_data, graph):
        """Unknown start_id should return found=False with descriptive error."""
        result = find_route(mall_data, "LXXX", "L15", graph)
        assert result["found"] is False
        assert result["error"] is not None
        assert "LXXX" in result["error"]

    def test_unknown_destination_id(self, mall_data, graph):
        """Unknown destination_id should return found=False with descriptive error."""
        result = find_route(mall_data, "L01", "LYYY", graph)
        assert result["found"] is False
        assert result["error"] is not None
        assert "LYYY" in result["error"]

    def test_directions_length(self, mall_data, graph):
        """Number of direction steps should equal len(path) - 1 for multi-step routes."""
        result = find_route(mall_data, "L01", "L15", graph)
        assert result["found"] is True
        path = result["path"]
        if len(path) > 1:
            assert len(result["directions"]) == len(path) - 1, (
                f"Expected {len(path)-1} directions, got {len(result['directions'])}"
            )

    def test_cross_floor_route_uses_transition(self, mall_data, graph):
        """A cross-floor route must pass through a stairs/escalator/elevator node."""
        result = find_route(mall_data, "L01", "L15", graph)  # Ground → First
        assert result["found"] is True
        locs = {loc["id"]: loc for loc in mall_data["locations"]}
        transition_categories = {"stairs", "escalator", "elevator"}
        has_transition = any(
            locs[node_id]["category"] in transition_categories
            for node_id in result["path"]
        )
        assert has_transition, (
            "Cross-floor route from Ground to First Floor did not include a "
            "stairs/escalator/elevator node."
        )

    def test_cross_floor_direction_mentions_floor(self, mall_data, graph):
        """Direction text for a cross-floor step should mention the floor name."""
        result = find_route(mall_data, "L01", "L15", graph)
        assert result["found"] is True
        # At least one direction should mention a floor-change word
        floor_words = {"escalator", "stairs", "elevator", "floor"}
        found_floor_mention = any(
            any(w in step.lower() for w in floor_words)
            for step in result["directions"]
        )
        assert found_floor_mention, (
            "No direction step mentions a floor-change method."
        )

    def test_second_floor_destination(self, mall_data, graph):
        """Route to Cinema (L29, Second Floor) from Main Entrance should be found."""
        result = find_route(mall_data, "L01", "L29", graph)
        assert result["found"] is True
        assert result["path"][-1] == "L29"
        locs = {loc["id"]: loc for loc in mall_data["locations"]}
        assert locs[result["path"][-1]]["floor"] == 2

    def test_unreachable_destination(self, mall_data, graph):
        """Adding an isolated node and routing to it should return found=False."""
        import copy
        import networkx as nx

        # Manually add an isolated node to a copy of the graph
        g2 = graph.copy()
        g2.add_node("L_ISOLATED", name="Isolated Room", floor=0, category="corridor",
                    coordinates={"x": 0, "y": 0}, aliases=[], tags=[])
        data2 = copy.deepcopy(mall_data)
        data2["locations"].append({
            "id": "L_ISOLATED", "name": "Isolated Room", "category": "corridor",
            "floor": 0, "aliases": [], "coordinates": {"x": 0, "y": 0}, "tags": []
        })

        result = find_route(data2, "L01", "L_ISOLATED", g2)
        assert result["found"] is False
        assert result["error"] is not None

    def test_route_error_is_none_when_found(self, mall_data, graph):
        """When a route is found, error field should be None."""
        result = find_route(mall_data, "L01", "L15", graph)
        assert result["found"] is True
        assert result["error"] is None


# ---------------------------------------------------------------------------
# find_nearest tests
# ---------------------------------------------------------------------------

class TestFindNearest:
    def test_nearest_washroom_from_main_entrance(self, mall_data, graph):
        """find_nearest('washroom') from Main Entrance should return a reachable washroom."""
        result = find_nearest(mall_data, "L01", "washroom", graph)
        assert result["found"] is True
        assert result["destination_id"] is not None
        locs = {loc["id"]: loc for loc in mall_data["locations"]}
        assert locs[result["destination_id"]]["category"] == "washroom"

    def test_nearest_returns_shortest(self, mall_data, graph):
        """find_nearest should return the CLOSEST washroom, not an arbitrary one."""
        result = find_nearest(mall_data, "L01", "washroom", graph)
        assert result["found"] is True
        # Manually check it's the minimum distance among all washrooms
        washrooms = [l for l in mall_data["locations"] if l["category"] == "washroom"]
        for w in washrooms:
            r = find_route(mall_data, "L01", w["id"], graph)
            if r["found"] and w["id"] != result["destination_id"]:
                assert r["total_distance"] >= result["total_distance"], (
                    f"find_nearest returned {result['destination_id']} (dist={result['total_distance']}) "
                    f"but {w['id']} (dist={r['total_distance']}) is closer."
                )

    def test_nearest_cafe_from_south_entrance(self, mall_data, graph):
        """find_nearest('cafe') from South Entrance (L02) should find a cafe."""
        result = find_nearest(mall_data, "L02", "cafe", graph)
        assert result["found"] is True
        locs = {loc["id"]: loc for loc in mall_data["locations"]}
        dest = locs[result["destination_id"]]
        assert dest["category"] == "cafe"

    def test_nearest_nonexistent_category(self, mall_data, graph):
        """find_nearest for a category with no locations should return found=False."""
        result = find_nearest(mall_data, "L01", "nonexistent_category_xyz", graph)
        assert result["found"] is False
        assert result["destination_id"] is None
        assert result["error"] is not None

    def test_nearest_destination_name_populated(self, mall_data, graph):
        """find_nearest result should include destination_name when found."""
        result = find_nearest(mall_data, "L01", "washroom", graph)
        assert result["found"] is True
        assert result["destination_name"] is not None
        assert len(result["destination_name"]) > 0

    def test_nearest_path_ends_at_destination(self, mall_data, graph):
        """The last node in the returned path should be the destination_id."""
        result = find_nearest(mall_data, "L01", "cinema", graph)
        assert result["found"] is True
        assert result["path"][-1] == result["destination_id"]
