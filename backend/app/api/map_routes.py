"""
app/api/map_routes.py

Dedicated map data API — returns geocoded coordinates + GeoJSON-ready
polyline data from an existing session's route_data, so the frontend
Leaflet component can render the full route without extra work.

Mount in main.py:
    from app.api.map_routes import router as map_router
    app.include_router(map_router, prefix="/api/v1/map", tags=["map"])
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.maps_service import MapsService

logger = logging.getLogger(__name__)
router = APIRouter()
maps_service = MapsService()


# ── Request / Response schemas ────────────────────────────────────────────────

class MapDataRequest(BaseModel):
    origin: str
    destination: str
    transport_mode: str = "driving"
    waypoints: Optional[List[str]] = None          # e.g. place names from itinerary


class Coordinate(BaseModel):
    lat: float
    lng: float
    label: Optional[str] = None


class RoutePolyline(BaseModel):
    coordinates: List[Coordinate]          # decoded polyline points
    distance: Optional[str] = None
    duration: Optional[str] = None
    transport_mode: str


class MapDataResponse(BaseModel):
    success: bool
    origin_coords: Optional[Coordinate] = None
    destination_coords: Optional[Coordinate] = None
    waypoint_coords: List[Coordinate] = []
    primary_route: Optional[RoutePolyline] = None
    alternative_routes: Dict[str, RoutePolyline] = {}
    error: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_geometry_coords(geojson: Dict[str, Any]) -> List[Coordinate]:
    """
    Pull [lng, lat] pairs from an ORS GeoJSON FeatureCollection or Feature
    and return them as Coordinate(lat, lng) objects.
    """
    coords: List[Coordinate] = []

    features = geojson.get("features", [])
    if not features:
        return coords

    geometry = features[0].get("geometry", {})
    raw = geometry.get("coordinates", [])

    for point in raw:
        if len(point) >= 2:
            coords.append(Coordinate(lat=point[1], lng=point[0]))

    return coords


def _route_info_to_polyline(
    route_geojson: Optional[Dict[str, Any]],
    route_info_dict: Optional[Dict[str, Any]],
    transport_mode: str,
) -> Optional[RoutePolyline]:
    """
    Build a RoutePolyline from raw ORS GeoJSON + the already-parsed RouteInfo dict.
    Falls back to just origin→destination straight line if geometry is absent.
    """
    if route_geojson is None and route_info_dict is None:
        return None

    coords = _extract_geometry_coords(route_geojson or {})

    distance = None
    duration = None
    if route_info_dict:
        distance = route_info_dict.get("distance")
        duration = route_info_dict.get("duration")

    return RoutePolyline(
        coordinates=coords,
        distance=distance,
        duration=duration,
        transport_mode=transport_mode,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/data", response_model=MapDataResponse)
async def get_map_data(request: MapDataRequest) -> MapDataResponse:
    """
    Geocode origin + destination (+ optional waypoints), fetch the full ORS
    route with geometry, and return everything the Leaflet component needs.

    Called by the frontend after /plan returns maps data, or standalone.
    """
    try:
        # ── 1. Geocode in parallel ────────────────────────────────────────────
        geocode_tasks = [
            maps_service.geocode_location(request.origin),
            maps_service.geocode_location(request.destination),
        ]
        if request.waypoints:
            for wp in request.waypoints:
                geocode_tasks.append(maps_service.geocode_location(wp))

        geo_results = await asyncio.gather(*geocode_tasks, return_exceptions=True)

        origin_geo = geo_results[0] if not isinstance(geo_results[0], Exception) else None
        dest_geo   = geo_results[1] if not isinstance(geo_results[1], Exception) else None

        if not origin_geo or not dest_geo:
            return MapDataResponse(
                success=False,
                error=f"Could not geocode '{request.origin}' or '{request.destination}'",
            )

        origin_coord = Coordinate(
            lat=origin_geo["coordinates"][0],
            lng=origin_geo["coordinates"][1],
            label=origin_geo.get("name", request.origin),
        )
        dest_coord = Coordinate(
            lat=dest_geo["coordinates"][0],
            lng=dest_geo["coordinates"][1],
            label=dest_geo.get("name", request.destination),
        )

        # Waypoint coords (best-effort — skip failures)
        waypoint_coords: List[Coordinate] = []
        if request.waypoints:
            for i, wp in enumerate(request.waypoints):
                geo = geo_results[2 + i]
                if not isinstance(geo, Exception) and geo:
                    waypoint_coords.append(
                        Coordinate(
                            lat=geo["coordinates"][0],
                            lng=geo["coordinates"][1],
                            label=geo.get("name", wp),
                        )
                    )

        # ── 2. Primary route with geometry ────────────────────────────────────
        primary_geojson = await maps_service.get_route(
            start_coords=origin_geo["coordinates"],
            end_coords=dest_geo["coordinates"],
            transport_mode=request.transport_mode,
        )

        # Also get the parsed RouteInfo for distance/duration strings
        primary_info = await maps_service.get_route_between_locations(
            request.origin, request.destination, request.transport_mode
        )
        primary_info_dict = primary_info.dict() if primary_info else None

        primary_polyline = _route_info_to_polyline(
            primary_geojson, primary_info_dict, request.transport_mode
        )

        # ── 3. Alternative routes (driving + cycling + walking) ───────────────
        alt_modes = [m for m in ["driving", "cycling", "walking"] if m != request.transport_mode]
        alt_tasks = [
            maps_service.get_route(
                origin_geo["coordinates"], dest_geo["coordinates"], mode
            )
            for mode in alt_modes
        ]
        alt_info_tasks = [
            maps_service.get_route_between_locations(
                request.origin, request.destination, mode
            )
            for mode in alt_modes
        ]

        alt_geojsons, alt_infos = await asyncio.gather(
            asyncio.gather(*alt_tasks, return_exceptions=True),
            asyncio.gather(*alt_info_tasks, return_exceptions=True),
        )

        alternative_routes: Dict[str, RoutePolyline] = {}
        for i, mode in enumerate(alt_modes):
            geo = alt_geojsons[i]
            info = alt_infos[i]
            if isinstance(geo, Exception):
                geo = None
            if isinstance(info, Exception):
                info = None
            poly = _route_info_to_polyline(
                geo,
                info.dict() if info else None,
                mode,
            )
            if poly and poly.coordinates:
                alternative_routes[mode] = poly

        return MapDataResponse(
            success=True,
            origin_coords=origin_coord,
            destination_coords=dest_coord,
            waypoint_coords=waypoint_coords,
            primary_route=primary_polyline,
            alternative_routes=alternative_routes,
        )

    except Exception as exc:
        logger.exception("map_data endpoint failed")
        return MapDataResponse(success=False, error=str(exc))


@router.get("/geocode/{location}", summary="Geocode a single location")
async def geocode_location(location: str):
    """Quick geocode endpoint for the frontend to resolve place names to coords."""
    try:
        result = await maps_service.geocode_location(location)
        if not result:
            raise HTTPException(status_code=404, detail=f"Could not geocode '{location}'")
        return {
            "success": True,
            "location": location,
            "lat": result["coordinates"][0],
            "lng": result["coordinates"][1],
            "name": result.get("name"),
            "region": result.get("region"),
            "country": result.get("country"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))