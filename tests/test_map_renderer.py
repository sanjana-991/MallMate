"""
tests/test_map_renderer.py

Tests for map_renderer.py:
  - Output is a valid SVG-containing HTML string
  - Floor label is present
  - Route nodes referenced in SVG when a route is provided
  - Start and destination markers appear in the output
  - Cross-floor transition labels appear for cross-floor routes
"""

import pytest
from map_renderer import render_map


class TestRenderMap:
    def test_output_contains_svg(self, mall_data):
        """render_map should return a string containing an SVG element."""
        html = render_map(mall_data, floor=0)
        assert "<svg" in html
        assert "</svg>" in html

    def test_output_is_string(self, mall_data):
        """render_map must return a str, not bytes or None."""
        result = render_map(mall_data, floor=0)
        assert isinstance(result, str)

    def test_floor_label_ground(self, mall_data):
        """Output for floor 0 should mention 'Ground Floor'."""
        html = render_map(mall_data, floor=0)
        assert "Ground Floor" in html

    def test_floor_label_first(self, mall_data):
        """Output for floor 1 should mention 'First Floor'."""
        html = render_map(mall_data, floor=1)
        assert "First Floor" in html

    def test_floor_label_second(self, mall_data):
        """Output for floor 2 should mention 'Second Floor'."""
        html = render_map(mall_data, floor=2)
        assert "Second Floor" in html

    def test_disclaimer_present(self, mall_data):
        """SVG should include the fictional mall disclaimer."""
        html = render_map(mall_data, floor=0)
        assert "Sample map" in html or "not a real" in html

    def test_start_marker_in_svg(self, mall_data):
        """When start_id is given, start marker text 'S' should appear in SVG."""
        html = render_map(mall_data, floor=0, start_id="L01")
        assert ">S<" in html

    def test_destination_marker_in_svg(self, mall_data):
        """When destination_id is given, destination marker text 'D' should appear."""
        html = render_map(mall_data, floor=0, destination_id="L03")
        assert ">D<" in html

    def test_no_markers_without_args(self, mall_data):
        """Without start_id or destination_id, start/dest marker colours should not appear."""
        html = render_map(mall_data, floor=0)
        # The start marker emits fill="#00C853" only when start_id is given
        assert "#00C853" not in html, "Start marker colour found without start_id"
        # The destination marker emits fill="#D50000" only when destination_id is given
        assert "#D50000" not in html, "Destination marker colour found without destination_id"

    def test_route_highlight_color_in_svg(self, mall_data):
        """When a route is provided, the route highlight colour (#FF6B35) should appear."""
        route = ["L01", "L03", "L12", "L13"]  # All on Ground Floor
        html = render_map(mall_data, floor=0, route_path=route,
                          start_id="L01", destination_id="L13")
        assert "#FF6B35" in html or "FF6B35" in html

    def test_no_route_color_without_route(self, mall_data):
        """Without a route, the orange route colour should NOT appear in the SVG."""
        html = render_map(mall_data, floor=0)
        assert "FF6B35" not in html

    def test_cross_floor_label_in_svg(self, mall_data):
        """Cross-floor route should produce an arrow label (↑ or ↓) in the SVG."""
        # Route from Ground escalator to First escalator spans floors
        route = ["L13", "L07", "L24", "L27"]
        html = render_map(mall_data, floor=0,
                          route_path=route, start_id="L13", destination_id="L24")
        assert "↑" in html or "↓" in html

    def test_second_floor_renders(self, mall_data):
        """Second floor should render without errors and include Second Floor nodes."""
        html = render_map(mall_data, floor=2)
        assert "Cinema" in html
        assert "Bowling" in html

    def test_legend_in_output(self, mall_data):
        """Output should contain the legend with Start and Destination labels."""
        html = render_map(mall_data, floor=0, start_id="L01", destination_id="L05")
        assert "Start" in html
        assert "Destination" in html
