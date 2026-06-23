"""
app/mcp_server.py — FastMCP server exposing all TBuddy travel tools via MCP protocol.

Run standalone:  python -m app.mcp_server
Transport:       SSE (HTTP) on port 9000
"""

import asyncio
import logging
import sys
from typing import Dict, List, Optional, Any
from datetime import date, timedelta

from fastmcp import FastMCP

# ─── Logging (stderr only — stdout is reserved for SSE/JSON-RPC) ─────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MCP] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_server")

# ─── Initialize FastMCP server ───────────────────────────────────────────────
mcp = FastMCP(
    name="tbuddy-travel-tools",
    instructions=(
        "TBuddy Travel Planning MCP Server. Provides tools for weather forecasting, "
        "route planning, flight/train/bus search, budget estimation, event discovery, "
        "and itinerary generation for travel in India and worldwide."
    ),
)

# =============================================================================
#  WEATHER TOOLS
# =============================================================================

@mcp.tool()
async def weather_get_coordinates(location: str) -> Dict[str, Any]:
    """Get latitude and longitude for a location (city name).

    Args:
        location: City name or location string
    """
    from app.tools.weather_tools import get_location_coordinates
    return await get_location_coordinates.ainvoke({"location": location})


@mcp.tool()
async def weather_current(lat: float, lon: float) -> Dict[str, Any]:
    """Get current weather at geographic coordinates.

    Args:
        lat: Latitude
        lon: Longitude
    """
    from app.tools.weather_tools import get_current_weather
    return await get_current_weather.ainvoke({"lat": lat, "lon": lon})


@mcp.tool()
async def weather_5day_forecast(lat: float, lon: float) -> Dict[str, Any]:
    """Get 5-day weather forecast at coordinates.

    Args:
        lat: Latitude
        lon: Longitude
    """
    from app.tools.weather_tools import get_5day_forecast
    return await get_5day_forecast.ainvoke({"lat": lat, "lon": lon})


@mcp.tool()
async def weather_extended_forecast(lat: float, lon: float) -> Dict[str, Any]:
    """Get 16-day extended weather forecast at coordinates via Open-Meteo.

    Args:
        lat: Latitude
        lon: Longitude
    """
    from app.tools.weather_tools import get_extended_forecast
    return await get_extended_forecast.ainvoke({"lat": lat, "lon": lon})


@mcp.tool()
async def weather_air_quality(lat: float, lon: float) -> Dict[str, Any]:
    """Get air quality forecast at coordinates.

    Args:
        lat: Latitude
        lon: Longitude
    """
    from app.tools.weather_tools import get_air_quality
    return await get_air_quality.ainvoke({"lat": lat, "lon": lon})


@mcp.tool()
async def weather_for_dates(location: str, dates: List[str]) -> Dict[str, Any]:
    """Get weather forecast for specific travel dates at a location.
    Automatically selects best data source based on how far out the dates are.

    Args:
        location: City name or location string
        dates: List of dates in YYYY-MM-DD format (also accepts range strings like '2026-07-15 to 2026-07-18')
    """
    from app.tools.weather_tools import get_weather_for_specific_dates
    return await get_weather_for_specific_dates.ainvoke({"location": location, "dates": dates})


# =============================================================================
#  MAPS & TRANSPORT TOOLS
# =============================================================================

@mcp.tool()
async def maps_geocode(location: str) -> Dict[str, Any]:
    """Convert a location name to geographic coordinates using OpenRouteService.

    Args:
        location: Location name (e.g., 'London, UK' or 'New York')
    """
    from app.tools.maps_tools import geocode_location
    return await geocode_location.ainvoke({"location": location})


@mcp.tool()
async def maps_get_route(origin: str, destination: str, transport_mode: str = "driving") -> Dict[str, Any]:
    """Get route information between two locations.

    Args:
        origin: Starting location name
        destination: Destination location name
        transport_mode: Transport mode - 'driving', 'walking', 'cycling', or 'public_transport'
    """
    from app.tools.maps_tools import get_route
    return await get_route.ainvoke({"origin": origin, "destination": destination, "transport_mode": transport_mode})


@mcp.tool()
async def maps_multiple_routes(origin: str, destination: str) -> Dict[str, Any]:
    """Get route options for all transport modes (driving, walking, cycling).

    Args:
        origin: Starting location name
        destination: Destination location name
    """
    from app.tools.maps_tools import get_multiple_routes
    return await get_multiple_routes.ainvoke({"origin": origin, "destination": destination})


@mcp.tool()
async def maps_search_flights(origin: str, destination: str, date: str) -> Dict[str, Any]:
    """Search for flight options between cities. Auto-resolves city names to airport codes.

    Args:
        origin: Origin city name (e.g., 'Delhi', 'Mumbai')
        destination: Destination city name
        date: Departure date in YYYY-MM-DD format
    """
    from app.tools.maps_tools import search_flights
    return await search_flights.ainvoke({"origin": origin, "destination": destination, "date": date})


@mcp.tool()
async def maps_search_trains(origin: str, destination: str, date: str) -> Dict[str, Any]:
    """Search for train options between cities (Indian Railways). Auto-resolves station codes.

    Args:
        origin: Origin city name (e.g., 'Delhi', 'Mumbai')
        destination: Destination city name
        date: Journey date in YYYY-MM-DD format
    """
    from app.tools.maps_tools import search_trains
    return await search_trains.ainvoke({"origin": origin, "destination": destination, "date": date})


@mcp.tool()
async def maps_search_buses(origin: str, destination: str, date: str) -> Dict[str, Any]:
    """Search for bus and public transit options between cities via TripGo.

    Args:
        origin: Origin city name
        destination: Destination city name
        date: Journey date in YYYY-MM-DD format
    """
    from app.tools.maps_tools import search_buses
    return await search_buses.ainvoke({"origin": origin, "destination": destination, "date": date})


@mcp.tool()
async def maps_search_hotels(location: str, checkin: str, checkout: str) -> Dict[str, Any]:
    """Search for hotels at a location.

    Args:
        location: Location to search for hotels
        checkin: Check-in date (YYYY-MM-DD)
        checkout: Check-out date (YYYY-MM-DD)
    """
    from app.tools.maps_tools import search_hotels
    return await search_hotels.ainvoke({"location": location, "checkin": checkin, "checkout": checkout})


@mcp.tool()
async def maps_comprehensive_travel(
    origin: str,
    destination: str,
    date: str,
    checkin: Optional[str] = None,
    checkout: Optional[str] = None,
) -> Dict[str, Any]:
    """Get comprehensive travel options including routes, flights, trains, buses, and hotels.

    Args:
        origin: Starting location name
        destination: Destination location name
        date: Travel date in YYYY-MM-DD format
        checkin: Hotel check-in date (optional, defaults to travel date)
        checkout: Hotel check-out date (optional, defaults to travel date)
    """
    from app.tools.maps_tools import get_comprehensive_travel_options
    return await get_comprehensive_travel_options.ainvoke({
        "origin": origin, "destination": destination,
        "date": date, "checkin": checkin, "checkout": checkout,
    })


# =============================================================================
#  BUDGET TOOLS
# =============================================================================

@mcp.tool()
def budget_transportation_cost(
    distance_km: float,
    transport_mode: str,
    travelers_count: int,
    budget_category: str = "mid-range",
) -> Dict[str, Any]:
    """Calculate transportation costs for a trip.

    Args:
        distance_km: Distance in kilometers
        transport_mode: Transport mode (driving, car, train, bus, taxi)
        travelers_count: Number of travelers
        budget_category: Budget category - budget, mid-range, or luxury
    """
    from app.tools.budget_tools import calculate_transportation_cost
    return calculate_transportation_cost.invoke({
        "distance_km": distance_km, "transport_mode": transport_mode,
        "travelers_count": travelers_count, "budget_category": budget_category,
    })


@mcp.tool()
def budget_accommodation_cost(
    travel_dates: List[str],
    travelers_count: int,
    budget_category: str = "mid-range",
) -> Dict[str, Any]:
    """Calculate accommodation costs for a trip.

    Args:
        travel_dates: List of travel dates in YYYY-MM-DD format
        travelers_count: Number of travelers
        budget_category: Budget category - budget, mid-range, or luxury
    """
    from app.tools.budget_tools import calculate_accommodation_cost
    return calculate_accommodation_cost.invoke({
        "travel_dates": travel_dates, "travelers_count": travelers_count,
        "budget_category": budget_category,
    })


@mcp.tool()
def budget_food_cost(
    travel_dates: List[str],
    travelers_count: int,
    budget_category: str = "mid-range",
) -> Dict[str, Any]:
    """Calculate food costs for a trip.

    Args:
        travel_dates: List of travel dates in YYYY-MM-DD format
        travelers_count: Number of travelers
        budget_category: Budget category - budget, mid-range, or luxury
    """
    from app.tools.budget_tools import calculate_food_cost
    return calculate_food_cost.invoke({
        "travel_dates": travel_dates, "travelers_count": travelers_count,
        "budget_category": budget_category,
    })


@mcp.tool()
def budget_activities_cost(
    travel_dates: List[str],
    travelers_count: int,
    budget_category: str = "mid-range",
) -> Dict[str, Any]:
    """Calculate activities and sightseeing costs for a trip.

    Args:
        travel_dates: List of travel dates in YYYY-MM-DD format
        travelers_count: Number of travelers
        budget_category: Budget category - budget, mid-range, or luxury
    """
    from app.tools.budget_tools import calculate_activities_cost
    return calculate_activities_cost.invoke({
        "travel_dates": travel_dates, "travelers_count": travelers_count,
        "budget_category": budget_category,
    })


@mcp.tool()
def budget_complete(
    transport_mode: str,
    travel_dates: List[str],
    travelers_count: int,
    distance_km: Optional[float] = None,
    budget_category: str = "mid-range",
) -> Dict[str, Any]:
    """Calculate complete trip budget including all categories (transport, stay, food, activities).

    Args:
        transport_mode: Transport mode (driving, train, bus, taxi)
        travel_dates: List of travel dates in YYYY-MM-DD format
        travelers_count: Number of travelers
        distance_km: Distance in kilometers (optional, uses default 200 km if not provided)
        budget_category: Budget category - budget, mid-range, or luxury
    """
    from app.tools.budget_tools import calculate_complete_budget
    return calculate_complete_budget.invoke({
        "distance_km": distance_km, "transport_mode": transport_mode,
        "travel_dates": travel_dates, "travelers_count": travelers_count,
        "budget_category": budget_category,
    })


@mcp.tool()
def budget_compare_categories(
    transport_mode: str,
    travel_dates: List[str],
    travelers_count: int,
    distance_km: Optional[float] = None,
) -> Dict[str, Any]:
    """Compare trip costs across budget categories (budget, mid-range, luxury).

    Args:
        transport_mode: Transport mode
        travel_dates: List of travel dates
        travelers_count: Number of travelers
        distance_km: Distance in kilometers (optional)
    """
    from app.tools.budget_tools import compare_budget_categories
    return compare_budget_categories.invoke({
        "distance_km": distance_km, "transport_mode": transport_mode,
        "travel_dates": travel_dates, "travelers_count": travelers_count,
    })


@mcp.tool()
def budget_categories_info() -> Dict[str, Any]:
    """Get information about available budget categories and their per-night/per-day costs."""
    from app.tools.budget_tools import get_budget_categories
    return get_budget_categories.invoke({})


@mcp.tool()
def budget_cost_breakdown_info() -> Dict[str, Any]:
    """Get detailed information about all cost parameters used in budget calculations."""
    from app.tools.budget_tools import get_cost_breakdown_info
    return get_cost_breakdown_info.invoke({})


# =============================================================================
#  EVENTS TOOLS
# =============================================================================

@mcp.tool()
async def events_search(
    location: str,
    start_date: str,
    end_date: str,
    categories: Optional[List[str]] = None,
    size: int = 20,
) -> Dict[str, Any]:
    """Search for events in a location within a date range.

    Args:
        location: Location/city to search for events
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        categories: Optional list of categories to filter
        size: Max events to return (default 20)
    """
    from app.tools.events_tools import search_events
    return await search_events.ainvoke({
        "location": location, "start_date": start_date,
        "end_date": end_date, "categories": categories, "size": size,
    })


@mcp.tool()
async def events_for_dates(
    location: str,
    dates: List[str],
    categories: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Get events for specific dates at a location.

    Args:
        location: Location/city
        dates: List of specific dates in YYYY-MM-DD format
        categories: Optional list of categories
    """
    from app.tools.events_tools import get_events_for_dates
    return await get_events_for_dates.ainvoke({
        "location": location, "dates": dates, "categories": categories,
    })


@mcp.tool()
async def events_popular(
    location: str,
    days_ahead: int = 30,
    limit: int = 10,
) -> Dict[str, Any]:
    """Get popular upcoming events in a location.

    Args:
        location: Location/city
        days_ahead: Number of days ahead to search (default 30)
        limit: Max events to return (default 10)
    """
    from app.tools.events_tools import get_popular_events
    return await get_popular_events.ainvoke({
        "location": location, "days_ahead": days_ahead, "limit": limit,
    })


@mcp.tool()
async def events_by_category(
    location: str,
    category: str,
    start_date: str,
    end_date: str,
    limit: int = 20,
) -> Dict[str, Any]:
    """Search for events in a specific category.

    Args:
        location: Location/city
        category: Event category (e.g., music, sports, arts)
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        limit: Max events to return (default 20)
    """
    from app.tools.events_tools import search_events_by_category
    return await search_events_by_category.ainvoke({
        "location": location, "category": category,
        "start_date": start_date, "end_date": end_date, "limit": limit,
    })


@mcp.tool()
async def events_search_query(
    query: str,
    location: str = "",
    date_filter: str = "any",
    is_virtual: bool = False,
    limit: int = 20,
) -> Dict[str, Any]:
    """Search events using a custom query string.

    Args:
        query: Free-text search query
        location: Optional location/city filter
        date_filter: Date filter (any, today, tomorrow, week, weekend, etc.)
        is_virtual: Whether to search for virtual events
        limit: Max events to return (default 20)
    """
    from app.tools.events_tools import search_events_with_query
    return await search_events_with_query.ainvoke({
        "query": query, "location": location,
        "date_filter": date_filter, "is_virtual": is_virtual, "limit": limit,
    })


@mcp.tool()
async def events_details(event_id: str) -> Dict[str, Any]:
    """Get detailed information about a specific event.

    Args:
        event_id: The event ID
    """
    from app.tools.events_tools import get_event_details
    return await get_event_details.ainvoke({"event_id": event_id})


@mcp.tool()
def events_categories() -> Dict[str, Any]:
    """Get list of available event categories."""
    from app.tools.events_tools import get_event_categories
    return get_event_categories.invoke({})


@mcp.tool()
def events_date_filters() -> Dict[str, Any]:
    """Get list of available date filter options."""
    from app.tools.events_tools import get_date_filters
    return get_date_filters.invoke({})


# =============================================================================
#  ITINERARY TOOLS
# =============================================================================

@mcp.tool()
def itinerary_destination_info(destination: str) -> Dict[str, Any]:
    """Get information about a destination.

    Args:
        destination: Destination city or location name
    """
    from app.tools.itinerary_tools import get_destination_info
    return get_destination_info.invoke({"destination": destination})


@mcp.tool()
def itinerary_create_daily(
    destination: str,
    travel_dates: List[str],
    weather_data: Optional[List[Dict[str, Any]]] = None,
    budget_total: Optional[float] = None,
    travelers_count: int = 1,
) -> Dict[str, Any]:
    """Create a complete day-by-day itinerary for a trip using LLM.

    Args:
        destination: Destination city or location
        travel_dates: List of travel dates in YYYY-MM-DD format
        weather_data: Optional weather data for each day
        budget_total: Optional total budget in INR
        travelers_count: Number of travelers
    """
    from app.tools.itinerary_tools import create_daily_itinerary
    return create_daily_itinerary.invoke({
        "destination": destination, "travel_dates": travel_dates,
        "weather_data": weather_data, "budget_total": budget_total,
        "travelers_count": travelers_count,
    })


@mcp.tool()
def itinerary_optimize_by_weather(
    destination: str,
    travel_dates: List[str],
    weather_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Optimize itinerary based on weather forecasts — suggests indoor/outdoor activities.

    Args:
        destination: Destination city or location
        travel_dates: List of travel dates
        weather_data: Weather data for each day
    """
    from app.tools.itinerary_tools import optimize_itinerary_by_weather
    return optimize_itinerary_by_weather.invoke({
        "destination": destination, "travel_dates": travel_dates,
        "weather_data": weather_data,
    })


@mcp.tool()
def itinerary_food_recommendations(destination: str) -> Dict[str, Any]:
    """Get food recommendations for a destination.

    Args:
        destination: Destination city or location
    """
    from app.tools.itinerary_tools import get_food_recommendations
    return get_food_recommendations.invoke({"destination": destination})


@mcp.tool()
def itinerary_travel_tips(destination: str) -> Dict[str, Any]:
    """Get travel tips for a destination.

    Args:
        destination: Destination city or location
    """
    from app.tools.itinerary_tools import get_travel_tips
    return get_travel_tips.invoke({"destination": destination})


@mcp.tool()
def itinerary_plan_single_day(
    destination: str,
    day_number: int,
    total_days: int,
    weather_temp_max: Optional[float] = None,
    precipitation_chance: Optional[float] = None,
) -> Dict[str, Any]:
    """Plan activities for a single day.

    Args:
        destination: Destination city
        day_number: Day number (1-based)
        total_days: Total trip days
        weather_temp_max: Max temperature (optional)
        precipitation_chance: Rain chance 0-100 (optional)
    """
    from app.tools.itinerary_tools import plan_single_day_activities
    return plan_single_day_activities.invoke({
        "destination": destination, "day_number": day_number,
        "total_days": total_days, "weather_temp_max": weather_temp_max,
        "precipitation_chance": precipitation_chance,
    })


@mcp.tool()
def itinerary_available_destinations() -> Dict[str, Any]:
    """Get supported destinations info."""
    from app.tools.itinerary_tools import get_available_destinations
    return get_available_destinations.invoke({})


@mcp.tool()
def itinerary_time_per_attraction(
    destination: str,
    attraction_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Estimate time needed for attractions at a destination.

    Args:
        destination: Destination city
        attraction_count: Number of attractions (optional)
    """
    from app.tools.itinerary_tools import estimate_time_per_attraction
    return estimate_time_per_attraction.invoke({
        "destination": destination, "attraction_count": attraction_count,
    })


# =============================================================================
#  ENTRY POINT
# =============================================================================

def main():
    """Run the MCP server with SSE transport on port 9000."""
    logger.info("🚀 Starting TBuddy MCP Server on http://0.0.0.0:9000/mcp")
    mcp.run(transport="sse", host="0.0.0.0", port=9000)


if __name__ == "__main__":
    main()
