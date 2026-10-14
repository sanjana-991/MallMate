"""
navigation.py — Mall graph construction and shortest-path routing.

Responsibilities:
  - Build a weighted NetworkX graph from mall_data.json.
  - Find shortest routes between any two location IDs (Dijkstra).
  - Generate human-readable step-by-step directions.
  - Find the nearest reachable location of a given category.

Public API
----------
build_graph(mall_data)           -> nx.Graph
find_route(mall_data, start_id, destination_id, graph=None) -> dict
find_nearest(mall_data, start_id, category, graph=None)     -> dict
"""

import json
from pathlib import Path
import networkx as nx

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_FLOOR_NAMES = {0: "Ground Floor", 1: "First Floor", 2: "Second Floor"}


def _floor_name(floor: int) -> str:
    return _FLOOR_NAMES.get(floor, f"Floor {floor}")


def _loc_lookup(mall_data: dict) -> dict:
    """Return {id: location_dict} for every location in mall_data."""
    return {loc["id"]: loc for loc in mall_data["locations"]}


def _generate_directions(path: list, graph: nx.Graph, locs: dict) -> list:
    """
    Convert an ordered path of location IDs into human-readable instructions.

    Each step describes how to move from one node to the next, including
    floor-change transitions.
    """
    if len(path) == 1:
        name = locs[path[0]]["name"]
        return [f"You are already at {name}."]

    directions = []
    for i in range(len(path) - 1):
        cur_id = path[i]
        nxt_id = path[i + 1]
        edge = graph[cur_id][nxt_id]
        edge_type = edge.get("type", "corridor")

        cur = locs[cur_id]
        nxt = locs[nxt_id]
        cur_floor = cur["floor"]
        nxt_floor = nxt["floor"]

        if edge_type == "escalator":
            verb = "up" if nxt_floor > cur_floor else "down"
            directions.append(
                f"Take the escalator {verb} from {cur['name']} "
                f"to {nxt['name']} ({_floor_name(nxt_floor)})."
            )
        elif edge_type == "stairs":
            verb = "up" if nxt_floor > cur_floor else "down"
            directions.append(
                f"Take the stairs {verb} from {cur['name']} "
                f"to {nxt['name']} ({_floor_name(nxt_floor)})."
            )
        elif edge_type == "elevator":
            directions.append(
                f"Take the elevator from {cur['name']} "
                f"to {nxt['name']} ({_floor_name(nxt_floor)})."
            )
        else:
            # Same-floor corridor step
            if cur_floor == nxt_floor:
                directions.append(f"Walk from {cur['name']} to {nxt['name']}.")
            else:
                # Shouldn't happen for corridors, but handle gracefully
                directions.append(
                    f"Proceed from {cur['name']} to {nxt['name']} "
                    f"({_floor_name(nxt_floor)})."
                )

    return directions


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def build_graph(mall_data: dict) -> nx.Graph:
    """
    Build a weighted undirected NetworkX graph from mall_data.

    Validates that:
      - Every node ID referenced in connections exists in locations.
      - All edge distances are non-negative.

    Warns (does not raise) if any location has no connections (isolated node).

    Returns
    -------
    nx.Graph with:
      node attributes : all fields from the location record
      edge attributes : distance (float), type (str)
    """
    location_ids = {loc["id"] for loc in mall_data["locations"]}
    G = nx.Graph()

    # Add nodes
    for loc in mall_data["locations"]:
        G.add_node(loc["id"], **loc)

    # Validate and add edges
    for conn in mall_data["connections"]:
        src = conn["from"]
        dst = conn["to"]

        if src not in location_ids:
            raise ValueError(
                f"Connection references unknown location ID: '{src}'. "
                f"Check mall_data.json connections."
            )
        if dst not in location_ids:
            raise ValueError(
                f"Connection references unknown location ID: '{dst}'. "
                f"Check mall_data.json connections."
            )
        dist = conn["distance"]
        if dist < 0:
            raise ValueError(
                f"Negative distance {dist} on connection {src} -> {dst}. "
                f"All distances must be non-negative."
            )

        G.add_edge(src, dst, distance=dist, type=conn.get("type", "corridor"))
        # nx.Graph is undirected; bidirectional is implicit.
        # Directed support can be added later with nx.DiGraph if needed.

    # Warn about isolated nodes
    for node in list(G.nodes()):
        if G.degree(node) == 0:
            name = G.nodes[node].get("name", node)
            print(f"[navigation] WARNING: '{name}' ({node}) has no connections.")

    return G


def find_route(
    mall_data: dict,
    start_id: str,
    destination_id: str,
    graph: nx.Graph | None = None,
) -> dict:
    """
    Calculate the shortest path between two location IDs using Dijkstra's algorithm.

    Parameters
    ----------
    mall_data      : Parsed mall_data.json dict.
    start_id       : Starting location ID (must exist in mall_data).
    destination_id : Target location ID (must exist in mall_data).
    graph          : Pre-built graph. Built internally if None.

    Returns
    -------
    {
        "found"          : bool,
        "path"           : list[str],   # Ordered location IDs, start→end
        "total_distance" : float,       # Sum of edge weights (0.0 when same node)
        "directions"     : list[str],   # Human-readable steps
        "error"          : str | None   # Populated when found=False
    }
    """
    if graph is None:
        graph = build_graph(mall_data)

    locs = _loc_lookup(mall_data)

    if start_id not in locs:
        return {
            "found": False, "path": [], "total_distance": 0.0,
            "directions": [],
            "error": f"Unknown start location ID: '{start_id}'.",
        }
    if destination_id not in locs:
        return {
            "found": False, "path": [], "total_distance": 0.0,
            "directions": [],
            "error": f"Unknown destination ID: '{destination_id}'.",
        }

    # Trivial case: already there
    if start_id == destination_id:
        name = locs[start_id]["name"]
        return {
            "found": True,
            "path": [start_id],
            "total_distance": 0.0,
            "directions": [f"You are already at {name}."],
            "error": None,
        }

    try:
        path = nx.dijkstra_path(graph, start_id, destination_id, weight="distance")
        total_dist = nx.dijkstra_path_length(
            graph, start_id, destination_id, weight="distance"
        )
    except nx.NetworkXNoPath:
        s_name = locs[start_id]["name"]
        d_name = locs[destination_id]["name"]
        return {
            "found": False, "path": [], "total_distance": 0.0,
            "directions": [],
            "error": (
                f"No route found between '{s_name}' and '{d_name}'. "
                f"The destinations may not be connected in the mall graph."
            ),
        }
    except nx.NodeNotFound as exc:
        return {
            "found": False, "path": [], "total_distance": 0.0,
            "directions": [],
            "error": str(exc),
        }

    directions = _generate_directions(path, graph, locs)

    return {
        "found": True,
        "path": path,
        "total_distance": round(total_dist, 1),
        "directions": directions,
        "error": None,
    }


def find_nearest(
    mall_data: dict,
    start_id: str,
    category: str,
    graph: nx.Graph | None = None,
) -> dict:
    """
    Find the closest reachable location in the given category from start_id.

    Iterates over all locations with the matching category (or tag) and
    returns the find_route() result for the one with the lowest total_distance.

    Parameters
    ----------
    mall_data  : Parsed mall_data.json dict.
    start_id   : Starting location ID.
    category   : Category string or tag keyword to search for.
    graph      : Pre-built graph. Built internally if None.

    Returns
    -------
    find_route() dict extended with:
      "destination_id"   : str | None
      "destination_name" : str | None
    """
    if graph is None:
        graph = build_graph(mall_data)

    locs = _loc_lookup(mall_data)

    # Collect all candidates matching the category or any tag
    candidates = [
        loc for loc in mall_data["locations"]
        if loc["category"] == category or category in loc.get("tags", [])
    ]

    if not candidates:
        return {
            "found": False, "path": [], "total_distance": 0.0,
            "directions": [],
            "error": f"No locations found with category or tag: '{category}'.",
            "destination_id": None, "destination_name": None,
        }

    best: dict | None = None
    best_dist = float("inf")

    for candidate in candidates:
        cid = candidate["id"]
        if cid == start_id:
            continue  # Skip the start itself
        result = find_route(mall_data, start_id, cid, graph)
        if result["found"] and result["total_distance"] < best_dist:
            best_dist = result["total_distance"]
            best = result
            best["destination_id"] = cid
            best["destination_name"] = candidate["name"]

    if best is None:
        start_name = locs.get(start_id, {}).get("name", start_id)
        return {
            "found": False, "path": [], "total_distance": 0.0,
            "directions": [],
            "error": (
                f"No reachable '{category}' location found from '{start_name}'. "
                f"The category may not be connected in the graph."
            ),
            "destination_id": None, "destination_name": None,
        }

    return best


def load_mall_data(path: str | Path = "mall_data.json") -> dict:
    """Convenience loader. Returns parsed JSON from the given path."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
