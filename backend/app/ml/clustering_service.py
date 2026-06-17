"""
app/ml/clustering_service.py

Groups attractions geographically into N clusters (N = number of trip days)
using K-Means. This ensures attractions assigned to the same day are
physically close, minimizing intra-day travel time.

The actual visit ORDER within each day's cluster is decided separately
by route_optimizer.py (TSP) — this module only handles grouping.
"""

from typing import List, Dict, Any, Optional
import logging
import math

logger = logging.getLogger(__name__)

try:
    from sklearn.cluster import KMeans
    import numpy as np
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("[Clustering] scikit-learn not installed — falling back to simple geographic split")


def cluster_attractions_by_day(
    attractions: List[Dict[str, Any]],
    num_days: int,
    max_per_day: int = 4,
) -> List[List[Dict[str, Any]]]:
    """
    Cluster attractions into `num_days` geographic groups using K-Means.

    Args:
        attractions: list of dicts with at least 'lat' and 'lng' keys
        num_days: number of clusters to create (= trip length)
        max_per_day: cap attractions per day for a relaxed pace —
                      if a cluster exceeds this, the lowest-priority
                      (furthest from cluster centroid) attractions are dropped

    Returns:
        List of length num_days, each element a list of attraction dicts
        assigned to that day. Order within each day-list is NOT optimized
        yet — that's route_optimizer.py's job.
    """
    if not attractions:
        return [[] for _ in range(num_days)]

    if num_days <= 0:
        num_days = 1

    # Not enough attractions to bother clustering — just split evenly
    if len(attractions) <= num_days:
        return _fallback_even_split(attractions, num_days)

    if not SKLEARN_AVAILABLE:
        return _fallback_geographic_split(attractions, num_days, max_per_day)

    coords = np.array([[a["lat"], a["lng"]] for a in attractions])

    # n_clusters cannot exceed n_samples
    n_clusters = min(num_days, len(attractions))

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(coords)
    centroids = kmeans.cluster_centers_

    # Group attractions by cluster label
    clusters: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(n_clusters)}
    for attraction, label in zip(attractions, labels):
        clusters[label].append(attraction)

    # Cap each cluster at max_per_day, keeping attractions closest to centroid
    for label, centroid in enumerate(centroids):
        if len(clusters[label]) > max_per_day:
            clusters[label].sort(
                key=lambda a: _euclidean(a["lat"], a["lng"], centroid[0], centroid[1])
            )
            overflow = clusters[label][max_per_day:]
            clusters[label] = clusters[label][:max_per_day]
            # Redistribute overflow to the nearest under-capacity cluster
            for item in overflow:
                _redistribute(item, clusters, centroids, max_per_day)

    # Order clusters by centroid proximity to form a sensible day-1, day-2... sequence
    # (e.g. don't have day 1 in the north and day 3 back in the north again)
    ordered_labels = _order_clusters_by_proximity(centroids)

    result = [clusters[label] for label in ordered_labels]

    # Pad with empty lists if n_clusters < num_days (shouldn't normally happen)
    while len(result) < num_days:
        result.append([])

    logger.info(
        f"[Clustering] {len(attractions)} attractions -> {num_days} days, "
        f"sizes: {[len(c) for c in result]}"
    )
    return result


def _euclidean(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return math.sqrt((lat1 - lat2) ** 2 + (lng1 - lng2) ** 2)


def _redistribute(
    item: Dict[str, Any],
    clusters: Dict[int, List[Dict[str, Any]]],
    centroids,
    max_per_day: int,
):
    """Find the nearest cluster with spare capacity and append the item there."""
    distances = [
        (label, _euclidean(item["lat"], item["lng"], c[0], c[1]))
        for label, c in enumerate(centroids)
        if len(clusters[label]) < max_per_day
    ]
    if distances:
        distances.sort(key=lambda x: x[1])
        best_label = distances[0][0]
        clusters[best_label].append(item)
    # If every cluster is full, the item is simply dropped — relaxed pace wins
    # over cramming. Could log this if needed for visibility.


def _order_clusters_by_proximity(centroids) -> List[int]:
    """
    Order cluster labels via a simple greedy nearest-neighbour chain over
    centroids, so consecutive days are geographically adjacent rather than
    jumping randomly across the city.
    """
    n = len(centroids)
    if n <= 1:
        return list(range(n))

    visited = [False] * n
    order = [0]
    visited[0] = True

    for _ in range(n - 1):
        last = order[-1]
        best_dist = float("inf")
        best_idx = None
        for i in range(n):
            if not visited[i]:
                d = _euclidean(centroids[last][0], centroids[last][1], centroids[i][0], centroids[i][1])
                if d < best_dist:
                    best_dist = d
                    best_idx = i
        order.append(best_idx)
        visited[best_idx] = True

    return order


def _fallback_even_split(
    attractions: List[Dict[str, Any]], num_days: int
) -> List[List[Dict[str, Any]]]:
    """When there are fewer attractions than days, just spread them out."""
    result = [[] for _ in range(num_days)]
    for i, a in enumerate(attractions):
        result[i % num_days].append(a)
    return result


def _fallback_geographic_split(
    attractions: List[Dict[str, Any]], num_days: int, max_per_day: int
) -> List[List[Dict[str, Any]]]:
    """
    Used only if scikit-learn isn't installed. Sorts attractions by
    latitude then longitude and chunks them — a crude but workable
    geographic grouping without true clustering.
    """
    sorted_attractions = sorted(attractions, key=lambda a: (a["lat"], a["lng"]))
    chunk_size = max(1, math.ceil(len(sorted_attractions) / num_days))

    result = []
    for i in range(num_days):
        chunk = sorted_attractions[i * chunk_size:(i + 1) * chunk_size]
        result.append(chunk[:max_per_day])

    logger.info("[Clustering] Used fallback split (install scikit-learn for true K-Means)")
    return result