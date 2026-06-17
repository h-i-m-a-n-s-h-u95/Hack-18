"""
app/ml/route_optimizer.py

Given a cluster of attractions assigned to a single day (from
clustering_service.py), find the optimal visit order using a
Travelling Salesperson Problem (TSP) solver from Google OR-Tools.

Falls back to a simple nearest-neighbour heuristic if OR-Tools
isn't installed, so the feature degrades gracefully rather than
crashing the itinerary pipeline.
"""

from typing import List, Dict, Any, Optional, Tuple
import logging
import math

logger = logging.getLogger(__name__)

try:
    from ortools.constraint_solver import routing_enums_pb2
    from ortools.constraint_solver import pywrapcp
    ORTOOLS_AVAILABLE = True
except ImportError:
    ORTOOLS_AVAILABLE = False
    logger.warning("[RouteOptimizer] ortools not installed — using nearest-neighbour fallback")


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Real-world distance in km — more accurate than Euclidean for TSP cost."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _build_distance_matrix(attractions: List[Dict[str, Any]]) -> List[List[float]]:
    """
    Distance matrix in metres (OR-Tools wants integers, so we scale km -> metres).
    Could be swapped for real road distances from MapsService.get_route_between_locations
    if you want road-accurate TSP instead of straight-line — see note at bottom of file.
    """
    n = len(attractions)
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                km = _haversine_km(
                    attractions[i]["lat"], attractions[i]["lng"],
                    attractions[j]["lat"], attractions[j]["lng"],
                )
                matrix[i][j] = int(km * 1000)  # metres, OR-Tools needs ints
    return matrix


def optimize_day_order(
    attractions: List[Dict[str, Any]],
    start_index: int = 0,
) -> List[Dict[str, Any]]:
    """
    Return attractions reordered to minimize total travel distance for one day.

    Args:
        attractions: attractions assigned to this single day (from clustering)
        start_index: index of the attraction to start from (e.g. hotel-nearest
                      one, or just 0 — defaults to first in the list)

    Returns:
        Same attractions, reordered for an efficient visiting sequence.
    """
    n = len(attractions)
    if n <= 2:
        return attractions  # nothing to optimize with 0-2 stops

    if not ORTOOLS_AVAILABLE:
        return _nearest_neighbour_fallback(attractions, start_index)

    distance_matrix = _build_distance_matrix(attractions)

    manager = pywrapcp.RoutingIndexManager(n, 1, start_index)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return distance_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.FromSeconds(2)  # small clusters, fast solve

    solution = routing.SolveWithParameters(search_parameters)

    if not solution:
        logger.warning("[RouteOptimizer] OR-Tools found no solution — using fallback order")
        return _nearest_neighbour_fallback(attractions, start_index)

    # Extract the route as a list of original attraction indices
    index = routing.Start(0)
    ordered_indices = []
    while not routing.IsEnd(index):
        ordered_indices.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))

    ordered_attractions = [attractions[i] for i in ordered_indices]

    total_km = _route_total_km(ordered_attractions)
    logger.info(
        f"[RouteOptimizer] Optimized {n} stops, total distance: {total_km:.1f} km "
        f"(order: {[a['name'] for a in ordered_attractions]})"
    )

    return ordered_attractions


def _nearest_neighbour_fallback(
    attractions: List[Dict[str, Any]], start_index: int = 0
) -> List[Dict[str, Any]]:
    """
    Simple greedy nearest-neighbour TSP approximation.
    Not optimal but far better than random/LLM-guessed order, and has
    zero external dependencies.
    """
    remaining = attractions.copy()
    current = remaining.pop(start_index if start_index < len(remaining) else 0)
    route = [current]

    while remaining:
        nearest = min(
            remaining,
            key=lambda a: _haversine_km(current["lat"], current["lng"], a["lat"], a["lng"]),
        )
        route.append(nearest)
        remaining.remove(nearest)
        current = nearest

    return route


def _route_total_km(ordered: List[Dict[str, Any]]) -> float:
    total = 0.0
    for i in range(len(ordered) - 1):
        total += _haversine_km(
            ordered[i]["lat"], ordered[i]["lng"],
            ordered[i + 1]["lat"], ordered[i + 1]["lng"],
        )
    return total


def optimize_full_itinerary(
    day_clusters: List[List[Dict[str, Any]]],
) -> Tuple[List[List[Dict[str, Any]]], Dict[str, Any]]:
    """
    Run TSP optimization on every day's cluster.

    Returns:
        (optimized_clusters, stats) where stats includes total distance
        saved vs. an unordered baseline — useful for showing the user
        "we saved you 12km of travel" in the UI.
    """
    optimized = []
    total_optimized_km = 0.0
    total_naive_km = 0.0

    for day_attractions in day_clusters:
        if not day_attractions:
            optimized.append([])
            continue

        naive_km = _route_total_km(day_attractions)
        ordered = optimize_day_order(day_attractions)
        opt_km = _route_total_km(ordered)

        optimized.append(ordered)
        total_naive_km += naive_km
        total_optimized_km += opt_km

    stats = {
        "total_optimized_km": round(total_optimized_km, 1),
        "total_naive_km":     round(total_naive_km, 1),
        "km_saved":           round(max(0, total_naive_km - total_optimized_km), 1),
        "ortools_used":       ORTOOLS_AVAILABLE,
    }

    return optimized, stats


# ─── NOTE on upgrading to real road distances ─────────────────────────────────
# _build_distance_matrix currently uses haversine (straight-line) distance.
# For higher accuracy, especially across rivers/highways, replace it with
# real driving distances from your existing MapsService:
#
#   from app.services.maps_service import MapsService
#   maps_service = MapsService()
#   route = await maps_service.get_route_between_locations(origin, dest, "driving")
#   km = route.distance_meters / 1000
#
# This requires making _build_distance_matrix async and batching N*(N-1)
# OpenRouteService calls per day — fine for clusters of <=4 stops (max 12 calls)
# but adds real network latency, so it's a tradeoff: haversine is instant and
# good enough for clustering geography, road-distance is more accurate for
# the final ordering decision.