from typing import List, Optional
from fastapi import APIRouter, HTTPException
from datetime import datetime
import time
import asyncio
import logging

from app.models.requests import TravelPlanRequest, WeatherRequest
from app.models.response import (
    TravelPlanResponse,
    WeatherResponse,
    HealthResponse,
    ErrorResponse,
)
from app.agents.weather_agent import WeatherAgent
from app.agents.maps_agent import MapsAgent
from app.agents.budget_agent import BudgetAgent
from app.agents.itinerary_agent import ItineraryAgent
from app.agents.event_agent import EventsAgent
from app.core.state import EventInfo, create_initial_state
from app.services.maps_service import MapsService

logger = logging.getLogger(__name__)

# ── Router ────────────────────────────────────────────────────────────────────
router = APIRouter()

# ── Agent singletons ──────────────────────────────────────────────────────────
weather_agent   = WeatherAgent()
maps_agent      = MapsAgent()
budget_agent    = BudgetAgent()
itinerary_agent = ItineraryAgent()
event_agent     = EventsAgent()

# ── Maps service (used to build polyline for map_data) ────────────────────────
_maps_svc = MapsService()


# ═════════════════════════════════════════════════════════════════════════════
# MAP DATA HELPER
# ═════════════════════════════════════════════════════════════════════════════

async def _build_map_data(state: dict) -> Optional[dict]:
    """
    Geocode origin + destination from the finished state, fetch the full ORS
    route geometry (polyline), and return a map_data dict the Leaflet component
    can consume directly — no second frontend fetch required.

    Runs *after* the main agents so it never blocks the critical path.
    Returns None silently on any failure.
    """
    route_data  = state.get("route_data") or {}
    origin      = state.get("origin", "").strip()
    destination = state.get("destination", "").strip()

    if not origin or not destination:
        return None

    try:
        origin_geo, dest_geo = await asyncio.gather(
            _maps_svc.geocode_location(origin),
            _maps_svc.geocode_location(destination),
            return_exceptions=True,
        )

        if isinstance(origin_geo, Exception) or not origin_geo:
            origin_geo = None
        if isinstance(dest_geo, Exception) or not dest_geo:
            dest_geo = None

        # ── Determine best transport mode ─────────────────────────────────
        transport_mode = (
            route_data.get("recommended_mode")
            or (route_data.get("primary_route") or {}).get("transport_mode", "driving")
        )

        # ── Fetch route geometry (polyline) ───────────────────────────────
        primary_geojson = None
        if origin_geo and dest_geo:
            primary_geojson = await _maps_svc.get_route(
                start_coords=origin_geo["coordinates"],
                end_coords=dest_geo["coordinates"],
                transport_mode=transport_mode,
            )

        # ── Helper: geo dict → coord dict ─────────────────────────────────
        def _coord(geo, fallback_label: str) -> Optional[dict]:
            if not geo:
                return None
            return {
                "lat":   geo["coordinates"][0],
                "lng":   geo["coordinates"][1],
                "label": geo.get("name", fallback_label),
            }

        # ── Helper: ORS GeoJSON → list of {lat, lng} ──────────────────────
        def _polyline(geojson: Optional[dict]) -> List[dict]:
            if not geojson:
                return []
            features = geojson.get("features", [])
            if not features:
                return []
            raw = features[0].get("geometry", {}).get("coordinates", [])
            return [{"lat": p[1], "lng": p[0]} for p in raw if len(p) >= 2]

        primary_route = route_data.get("primary_route") or {}

        return {
            "origin":             origin,
            "destination":        destination,
            "origin_coords":      _coord(origin_geo, origin),
            "destination_coords": _coord(dest_geo, destination),
            "polyline":           _polyline(primary_geojson),
            "primary_route": {
                "distance":       primary_route.get("distance"),
                "duration":       primary_route.get("duration"),
                "transport_mode": primary_route.get("transport_mode", transport_mode),
            },
            "alternative_routes": route_data.get("alternative_routes") or {},
            "route_analysis":     route_data.get("route_analysis"),
            "recommended_mode":   route_data.get("recommended_mode"),
        }

    except Exception as exc:
        logger.warning(f"_build_map_data failed (non-fatal): {exc}")
        return None


# ═════════════════════════════════════════════════════════════════════════════
# SUMMARY HELPERS
# ═════════════════════════════════════════════════════════════════════════════

async def _generate_complete_trip_summary(state: dict) -> str:
    """Generate a comprehensive trip summary with all agent data."""
    messages       = state.get("messages", [])
    weather_data   = state.get("weather_data", [])
    route_data     = state.get("route_data")
    budget_data    = state.get("budget_data")
    events_data    = state.get("events_data", [])
    itinerary_data = state.get("itinerary_data", [])

    summary_parts = [
        f"Trip from {state['origin']} to {state['destination']}",
        f"Travel dates: {', '.join(state['travel_dates'])}",
        f"Travelers: {state['travelers_count']}",
    ]

    if weather_data:
        avg_max = sum(w.temperature_max for w in weather_data) / len(weather_data)
        avg_min = sum(w.temperature_min for w in weather_data) / len(weather_data)
        summary_parts.append(f"Weather: {avg_min:.1f}°C - {avg_max:.1f}°C")

    if route_data:
        summary_parts.append(
            f"Route: {route_data.distance} in {route_data.duration} by {route_data.transport_mode}"
        )

    if budget_data:
        summary_parts.append(f"Total Budget: ₹{budget_data.total:,.0f}")

    if itinerary_data:
        total_activities = sum(len(day.activities) for day in itinerary_data)
        summary_parts.append(
            f"Itinerary: {len(itinerary_data)} days, {total_activities} activities"
        )

    if events_data:
        categories  = set(e.category for e in events_data)
        venues      = set(e.venue for e in events_data)
        free_events = sum(1 for e in events_data if hasattr(e, "is_free") and e.is_free())

        event_summary = (
            f"Events: {len(events_data)} events across {len(categories)} categories "
            f"at {len(venues)} venues"
        )
        if free_events:
            event_summary += f" ({free_events} free)"
        summary_parts.append(event_summary)

        category_counts: dict = {}
        for e in events_data:
            category_counts[e.category] = category_counts.get(e.category, 0) + 1
        top = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:2]
        if top:
            summary_parts.append(
                "Top events: " + ", ".join(f"{cnt} {cat}" for cat, cnt in top)
            )

    if messages:
        summary_parts.extend(messages)

    return " | ".join(summary_parts)


async def _generate_event_recommendations(events_data: List[EventInfo]) -> str:
    """Generate specific event recommendations based on OpenWeb Ninja data."""
    if not events_data:
        return "No events available for your travel dates"

    recommendations: List[str] = []

    unique_venues: dict = {}
    for e in events_data:
        if e.venue not in unique_venues:
            unique_venues[e.venue] = e

    free_events        = [e for e in events_data if hasattr(e, "is_free") and e.is_free()]
    cultural_events    = [e for e in events_data if e.category in ("arts", "theatre", "film")]
    entertainment_events = [e for e in events_data if e.category in ("music", "comedy")]

    if free_events:
        recommendations.append(
            f"Free events: {len(free_events)} available including {free_events[0].name}"
        )
    if cultural_events:
        recommendations.append(
            f"Cultural highlights: {cultural_events[0].name} at {cultural_events[0].venue}"
        )
    if entertainment_events:
        recommendations.append(f"Entertainment: {entertainment_events[0].name}")

    popular_venues: dict = {}
    for e in events_data:
        popular_venues[e.venue] = popular_venues.get(e.venue, 0) + 1

    top_venue = max(popular_venues.items(), key=lambda x: x[1]) if popular_venues else None
    if top_venue and top_venue[1] > 1:
        recommendations.append(f"Popular venue: {top_venue[0]} ({top_venue[1]} events)")

    return (
        " | ".join(recommendations)
        if recommendations
        else "Various events available across different categories"
    )


# ═════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version="1.0.0",
    )


@router.post("/weather", response_model=WeatherResponse)
async def get_weather(request: WeatherRequest):
    """Get weather information for a location and dates."""
    try:
        logger.info(f"Weather request for {request.location}")
        weather_data = await weather_agent.weather_service.get_weather_for_dates(
            location=request.location,
            dates=request.dates,
        )
        return WeatherResponse(success=True, data=weather_data)
    except Exception as e:
        logger.error(f"Weather request failed: {e}")
        return WeatherResponse(success=False, error=f"Failed to get weather data: {e}")


@router.post("/route")
async def get_route(
    origin: str,
    destination: str,
    transport_mode: str = "driving",
):
    """Get route information between two locations."""
    try:
        logger.info(f"Route request: {origin} to {destination} by {transport_mode}")
        route_data = await maps_agent.maps_service.get_route_between_locations(
            origin=origin,
            destination=destination,
            transport_mode=transport_mode,
        )
        if route_data:
            return {
                "success": True,
                "data": {
                    "distance":       route_data.distance,
                    "duration":       route_data.duration,
                    "transport_mode": route_data.transport_mode,
                    "steps":          route_data.steps[:5],
                    "traffic_info":   route_data.traffic_info,
                },
            }
        return {"success": False, "error": "Failed to calculate route"}
    except Exception as e:
        logger.error(f"Route request failed: {e}")
        return {"success": False, "error": f"Failed to get route data: {e}"}


@router.get("/route/compare/{origin}/{destination}")
async def compare_routes(origin: str, destination: str):
    """Compare different transportation modes for a journey."""
    try:
        logger.info(f"Route comparison: {origin} to {destination}")
        comparison = await maps_agent.compare_transport_modes(origin, destination)
        return {"success": True, "origin": origin, "destination": destination, "routes": comparison}
    except Exception as e:
        logger.error(f"Route comparison failed: {e}")
        return {"success": False, "error": f"Failed to compare routes: {e}"}


@router.post("/budget")
async def get_budget_estimate(
    origin: str,
    destination: str,
    travel_dates: str,
    travelers: int = 1,
    budget_category: str = "mid-range",
):
    """Get budget estimate for a trip."""
    try:
        logger.info(f"Budget request: {origin} to {destination}, {travelers} travelers")
        dates_list = travel_dates.split(",")

        state = create_initial_state(
            destination=destination,
            origin=origin,
            travel_dates=dates_list,
            travelers_count=travelers,
            budget_range=budget_category,
        )

        route_info = await maps_agent.maps_service.get_route_between_locations(origin, destination)
        state["route_data"] = route_info
        state = await budget_agent.process(state)

        budget_data = state.get("budget_data")
        if budget_data:
            return {
                "success": True,
                "budget": {
                    "total":          budget_data.total,
                    "transportation": budget_data.transportation,
                    "accommodation":  budget_data.accommodation,
                    "food":           budget_data.food,
                    "activities":     budget_data.activities,
                    "currency":       budget_data.currency,
                    "breakdown":      budget_agent.format_budget_summary(budget_data),
                },
            }
        return {"success": False, "error": "Budget calculation failed"}
    except Exception as e:
        logger.error(f"Budget request failed: {e}")
        return {"success": False, "error": f"Failed to calculate budget: {e}"}


@router.post("/itinerary")
async def create_itinerary(
    destination: str,
    travel_dates: str,
    travelers: int = 1,
):
    """Create a detailed itinerary."""
    try:
        logger.info(f"Itinerary request: {destination}, {travelers} travelers")
        dates_list = travel_dates.split(",")

        state = create_initial_state(
            destination=destination,
            origin="",
            travel_dates=dates_list,
            travelers_count=travelers,
        )
        state = await weather_agent.process(state)
        state = await itinerary_agent.process(state)

        itinerary_data = state.get("itinerary_data")
        if itinerary_data:
            return {
                "success": True,
                "itinerary": [
                    {
                        "day":            day.day,
                        "date":           day.date,
                        "activities":     day.activities,
                        "notes":          day.notes,
                        "estimated_cost": day.estimated_cost,
                    }
                    for day in itinerary_data
                ],
                "summary": itinerary_agent.format_itinerary_summary(itinerary_data),
            }
        return {"success": False, "error": "Itinerary creation failed"}
    except Exception as e:
        logger.error(f"Itinerary request failed: {e}")
        return {"success": False, "error": f"Failed to create itinerary: {e}"}


@router.post("/plan", response_model=TravelPlanResponse)
async def create_travel_plan(request: TravelPlanRequest):
    """
    Create a comprehensive travel plan with all agents.

    Now includes a `map_data` field in the response that contains geocoded
    coordinates and a decoded polyline ready for the Leaflet map component.
    """
    start_time = time.time()

    try:
        logger.info(f"Complete travel plan: {request.origin} → {request.destination}")

        # ── Create initial state ──────────────────────────────────────────
        state = create_initial_state(
            destination=request.destination,
            origin=request.origin,
            travel_dates=request.travel_dates,
            travelers_count=request.travelers_count,
            budget_range=request.budget_range,
        )

        # ── Run all agents sequentially ───────────────────────────────────
        state = await weather_agent.process(state)
        state = await maps_agent.process(state)
        state = await budget_agent.process(state)
        state = await itinerary_agent.process(state)
        state = await event_agent.process(state)

        # ── Events ────────────────────────────────────────────────────────
        event_recommendations   = None
        event_categories_found  = None

        if state.get("events_data"):
            event_recommendations  = await _generate_event_recommendations(state["events_data"])
            event_categories_found = list(set(e.category for e in state["events_data"]))

        # ── Build map data (geocode + polyline) ───────────────────────────
        # Runs concurrently with summary generation to save time.
        processing_time = time.time() - start_time

        map_data, trip_summary = await asyncio.gather(
            _build_map_data(state),
            _generate_complete_trip_summary(state),
        )

        logger.info(
            f"Travel plan ready in {processing_time:.1f}s | "
            f"map_data={'ok' if map_data else 'none'} | "
            f"polyline_pts={len(map_data.get('polyline', [])) if map_data else 0}"
        )

        return TravelPlanResponse(
            success=True,
            message="Complete travel plan created successfully",
            trip_summary=trip_summary,
            weather=state.get("weather_data"),
            route=state.get("route_data"),
            map_data=map_data,                      # ← NEW: Leaflet-ready map data
            budget=state.get("budget_data"),
            itinerary=state.get("itinerary_data"),
            errors=state.get("errors", []),
            processing_time=processing_time,
            event_recommendations=event_recommendations,
            event_categories_found=event_categories_found,
        )

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"Complete travel plan failed: {e}")
        return TravelPlanResponse(
            success=False,
            message=f"Travel planning failed: {e}",
            errors=[str(e)],
            processing_time=processing_time,
        )


# ═════════════════════════════════════════════════════════════════════════════
# TEST / DEBUG ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/test-weather/{location}")
async def test_weather_service(location: str, dates: str = None):
    """Test endpoint for weather service."""
    try:
        if not dates:
            from datetime import date, timedelta
            test_dates = [
                (date.today() + timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range(3)
            ]
        else:
            test_dates = dates.split(",")

        weather_data = await weather_agent.weather_service.get_weather_for_dates(
            location=location,
            dates=test_dates,
        )
        return {
            "success": True,
            "location": location,
            "dates": test_dates,
            "weather_data": [w.dict() for w in weather_data],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "location": location}


@router.get("/test-route/{origin}/{destination}")
async def test_route_service(origin: str, destination: str, mode: str = "driving"):
    """Test endpoint for route service."""
    try:
        route_data = await maps_agent.maps_service.get_route_between_locations(
            origin=origin,
            destination=destination,
            transport_mode=mode,
        )
        if route_data:
            return {
                "success": True,
                "origin": origin,
                "destination": destination,
                "transport_mode": mode,
                "route_data": route_data.dict(),
            }
        return {
            "success": False,
            "error": "Route calculation failed",
            "origin": origin,
            "destination": destination,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "origin": origin, "destination": destination}


@router.get("/test-map/{origin}/{destination}")
async def test_map_data(origin: str, destination: str, mode: str = "driving"):
    """
    Test endpoint — returns the same map_data dict that /plan now includes.
    Useful for verifying geocoding + polyline extraction without running all agents.
    """
    try:
        state = {
            "origin":      origin,
            "destination": destination,
            "route_data": {
                "recommended_mode": mode,
                "primary_route": {"transport_mode": mode},
                "alternative_routes": {},
                "route_analysis": None,
            },
        }
        map_data = await _build_map_data(state)
        if map_data:
            return {
                "success": True,
                "map_data": map_data,
                "polyline_points": len(map_data.get("polyline", [])),
            }
        return {"success": False, "error": "map_data build returned None"}
    except Exception as e:
        return {"success": False, "error": str(e)}