import httpx
import asyncio
import math
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config.settings import settings
from app.core.state import RouteInfo

logger = logging.getLogger(__name__)

# ========================= INPUT SCHEMAS ========================= #

class LocationInput(BaseModel):
    """Input schema for single location queries."""
    location: str = Field(..., description="Location name (e.g., 'London', 'New York, USA')")

class RouteInput(BaseModel):
    """Input schema for route queries."""
    origin: str = Field(..., description="Starting location name")
    destination: str = Field(..., description="Destination location name")
    transport_mode: str = Field(
        default="driving",
        description="Transport mode: 'driving', 'walking', 'cycling', or 'public_transport'"
    )

class TravelOptionsInput(BaseModel):
    """Input schema for comprehensive travel options."""
    origin: str = Field(..., description="Starting location name")
    destination: str = Field(..., description="Destination location name")
    date: str = Field(..., description="Travel date in YYYY-MM-DD format")
    checkin: Optional[str] = Field(None, description="Hotel check-in date (YYYY-MM-DD)")
    checkout: Optional[str] = Field(None, description="Hotel check-out date (YYYY-MM-DD)")

class FlightInput(BaseModel):
    """Input schema for flight searches."""
    origin_code: str = Field(..., description="Origin airport code (e.g., 'DEL', 'BOM')")
    dest_code: str = Field(..., description="Destination airport code")
    date: str = Field(..., description="Departure date in YYYY-MM-DD format")

class TrainInput(BaseModel):
    """Input schema for train searches."""
    from_station: str = Field(..., description="Origin station code")
    to_station: str = Field(..., description="Destination station code")
    date: str = Field(..., description="Journey date in YYYY-MM-DD format")

class BusInput(BaseModel):
    """Input schema for bus searches."""
    origin: str = Field(..., description="Origin city name")
    destination: str = Field(..., description="Destination city name")
    date: str = Field(..., description="Journey date in YYYY-MM-DD format")

class HotelInput(BaseModel):
    """Input schema for hotel searches."""
    location: str = Field(..., description="Location to search for hotels")
    checkin: str = Field(..., description="Check-in date (YYYY-MM-DD)")
    checkout: str = Field(..., description="Check-out date (YYYY-MM-DD)")

# ========================= HELPER FUNCTIONS ========================= #

class MapsServiceHelpers:
    """Shared helper functions for maps tools."""
    
    # Transport mode mapping
    TRANSPORT_MODES = {
        "driving": "driving-car",
        "walking": "foot-walking",
        "cycling": "cycling-regular",
        "public_transport": "driving-car"  # fallback
    }
    
    # RapidAPI hosts
    SKYSCANNER_HOST = settings.skyscanner_host
    TRAINS_HOST = settings.trains_host
    TRIPGO_HOST = settings.tripgo_host
    HOTELS_HOST = settings.hotels_host

    # Well-known IATA airport codes
    AIRPORT_CODES = {
        "delhi": "DEL", "new delhi": "DEL", "mumbai": "BOM",
        "bangalore": "BLR", "bengaluru": "BLR", "chennai": "MAA",
        "kolkata": "CCU", "hyderabad": "HYD", "pune": "PNQ",
        "ahmedabad": "AMD", "goa": "GOI", "jaipur": "JAI",
        "lucknow": "LKO", "kochi": "COK", "varanasi": "VNS",
        "guwahati": "GAU", "chandigarh": "IXC", "patna": "PAT",
        "bhubaneswar": "BBI", "indore": "IDR", "nagpur": "NAG",
        "srinagar": "SXR", "amritsar": "ATQ", "udaipur": "UDR",
        "coimbatore": "CJB", "thiruvananthapuram": "TRV",
        "london": "LHR", "paris": "CDG", "new york": "JFK",
        "dubai": "DXB", "singapore": "SIN", "bangkok": "BKK",
        "tokyo": "NRT", "hong kong": "HKG", "sydney": "SYD",
        "agra": "AGR", "jodhpur": "JDH", "shimla": "SLV",
        "jammu": "IXJ",
    }

    # Well-known IRCTC station codes
    STATION_CODES = {
        "delhi": "NDLS", "new delhi": "NDLS", "mumbai": "CSMT",
        "mumbai central": "BCT", "bangalore": "SBC", "bengaluru": "SBC",
        "chennai": "MAS", "kolkata": "HWH", "hyderabad": "SC",
        "pune": "PUNE", "ahmedabad": "ADI", "jaipur": "JP",
        "lucknow": "LKO", "varanasi": "BSB", "agra": "AGC",
        "goa": "MAO", "chandigarh": "CDG", "patna": "PNBE",
        "bhubaneswar": "BBS", "indore": "INDB", "nagpur": "NGP",
        "jodhpur": "JU", "udaipur": "UDZ", "shimla": "SML",
        "amritsar": "ASR", "guwahati": "GHY", "kochi": "ERS",
        "thiruvananthapuram": "TVC", "coimbatore": "CBE",
        "jammu": "JAT",
    }

    @staticmethod
    def resolve_airport_code(city: str) -> Optional[str]:
        return MapsServiceHelpers.AIRPORT_CODES.get(city.strip().lower())

    @staticmethod
    def resolve_station_code(city: str) -> Optional[str]:
        return MapsServiceHelpers.STATION_CODES.get(city.strip().lower())
    
    @staticmethod
    def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points using Haversine formula (returns km)."""
        lat1, lon1 = math.radians(lat1), math.radians(lon1)
        lat2, lon2 = math.radians(lat2), math.radians(lon2)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return 6371 * c  # Earth radius in km
    
    @staticmethod
    def estimate_duration(distance_km: float, transport_mode: str) -> float:
        """Estimate duration in seconds based on distance and mode."""
        speeds = {
            "driving": 50,
            "walking": 5,
            "cycling": 15,
            "public_transport": 35
        }
        speed = speeds.get(transport_mode, 50)
        return (distance_km / speed) * 3600
    
    @staticmethod
    def format_distance(distance_m: float) -> str:
        """Format distance in meters to human-readable string."""
        if distance_m >= 1000:
            return f"{distance_m / 1000:.1f} km"
        return f"{distance_m:.0f} m"
    
    @staticmethod
    def format_duration(duration_s: float) -> str:
        """Format duration in seconds to human-readable string."""
        hours = int(duration_s // 3600)
        minutes = int((duration_s % 3600) // 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    
    @staticmethod
    def parse_route_data(route_data: Dict[str, Any], transport_mode: str) -> Dict[str, Any]:
        """Parse raw route data into structured format."""
        try:
            if not route_data.get("features"):
                raise ValueError("No route features in response")
            
            feature = route_data["features"][0]
            props = feature.get("properties", {})
            summary = props.get("summary", {})
            
            distance_m = summary.get("distance", 0)
            duration_s = summary.get("duration", 0)
            
            # Extract steps
            steps = []
            segments = props.get("segments", [])
            for segment in segments:
                for step in segment.get("steps", []):
                    instruction = step.get("instruction", "")
                    if instruction:
                        steps.append(instruction)
            
            if not steps:
                steps = ["Route calculated - follow navigation"]
            
            return {
                "distance": MapsServiceHelpers.format_distance(distance_m),
                "duration": MapsServiceHelpers.format_duration(duration_s),
                "distance_meters": distance_m,
                "duration_seconds": duration_s,
                "steps": steps[:10],  # Limit to 10 steps
                "transport_mode": transport_mode
            }
            
        except Exception as e:
            logger.error(f"Route parsing failed: {e}")
            return {
                "distance": "Unknown",
                "duration": "Unknown",
                "steps": ["Route details unavailable"],
                "transport_mode": transport_mode
            }

# ========================= LANGCHAIN TOOLS ========================= #

# In-memory geocoding cache to prevent duplicate external requests
_GEOCODE_CACHE: Dict[str, Dict[str, Any]] = {}

@tool
async def geocode_location(location: str) -> Dict[str, Any]:
    """Convert a location name to geographic coordinates using OpenRouteService.
    
    Args:
        location: Location name (e.g., 'London, UK' or 'New York')
    
    Returns:
        Dictionary with coordinates, name, region, country, and confidence
    """
    loc_key = location.strip().lower()
    if loc_key in _GEOCODE_CACHE:
        logger.info(f"Geocoding cache hit for '{location}'")
        return _GEOCODE_CACHE[loc_key]

    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": settings.openroute_api_key}
            params = {
                "text": location,
                "size": 1,
                "layers": "locality,region,country"
            }
            resp = await client.get(
                "https://api.openrouteservice.org/geocode/search",
                headers=headers,
                params=params,
                timeout=8
            )
            resp.raise_for_status()
            data = resp.json()
            
            if not data.get("features"):
                return {"error": f"Location not found: {location}"}
            
            f = data["features"][0]
            coords = f["geometry"]["coordinates"]
            props = f["properties"]
            
            result = {
                "location": location,
                "coordinates": [coords[1], coords[0]],  # [lat, lon]
                "latitude": coords[1],
                "longitude": coords[0],
                "name": props.get("name", location),
                "region": props.get("region", ""),
                "country": props.get("country", ""),
                "confidence": props.get("confidence", 0)
            }
            _GEOCODE_CACHE[loc_key] = result
            return result
    except Exception as e:
        logger.error(f"Geocoding failed for {location}: {e}")
        return {"error": str(e)}


@tool
async def get_route(origin: str, destination: str, transport_mode: str = "driving") -> Dict[str, Any]:
    """Get route information between two locations.
    
    Args:
        origin: Starting location name
        destination: Destination location name
        transport_mode: Transport mode - 'driving', 'walking', 'cycling', or 'public_transport'
    
    Returns:
        Route information including distance, duration, and turn-by-turn directions
    """
    try:
        # Geocode both locations
        origin_result = await geocode_location.ainvoke({"location": origin})
        dest_result = await geocode_location.ainvoke({"location": destination})
        
        if "error" in origin_result:
            return origin_result
        if "error" in dest_result:
            return dest_result
        
        origin_coords = origin_result["coordinates"]
        dest_coords = dest_result["coordinates"]
        
        # Get route from OpenRouteService
        profile = MapsServiceHelpers.TRANSPORT_MODES.get(transport_mode, "driving-car")
        coords = [
            [origin_coords[1], origin_coords[0]],  # [lon, lat]
            [dest_coords[1], dest_coords[0]]
        ]
        
        headers = {
            "Authorization": settings.openroute_api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "coordinates": coords,
            "instructions": True,
            "geometry": True
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.openrouteservice.org/v2/directions/{profile}/geojson",
                headers=headers,
                json=payload,
                timeout=15
            )
            resp.raise_for_status()
            route_data = resp.json()
        
        # Parse route data
        parsed = MapsServiceHelpers.parse_route_data(route_data, transport_mode)
        parsed["origin"] = origin_result["name"]
        parsed["destination"] = dest_result["name"]
        
        return parsed
        
    except Exception as e:
        logger.error(f"Route fetch failed: {e}, using fallback")
        # Fallback calculation
        try:
            origin_result = await geocode_location.ainvoke({"location": origin})
            dest_result = await geocode_location.ainvoke({"location": destination})
            
            if "error" not in origin_result and "error" not in dest_result:
                dist_km = MapsServiceHelpers.calculate_haversine_distance(
                    origin_result["latitude"], origin_result["longitude"],
                    dest_result["latitude"], dest_result["longitude"]
                )
                dur_s = MapsServiceHelpers.estimate_duration(dist_km, transport_mode)
                
                return {
                    "origin": origin,
                    "destination": destination,
                    "distance": MapsServiceHelpers.format_distance(dist_km * 1000),
                    "duration": MapsServiceHelpers.format_duration(dur_s),
                    "distance_meters": dist_km * 1000,
                    "duration_seconds": dur_s,
                    "steps": ["Direct route - detailed navigation unavailable"],
                    "transport_mode": transport_mode,
                    "fallback": True
                }
        except:
            pass
        
        return {"error": str(e)}


@tool
async def get_multiple_routes(origin: str, destination: str) -> Dict[str, Any]:
    """Get route options for all available transport modes (driving, walking, cycling).
    
    Args:
        origin: Starting location name
        destination: Destination location name
    
    Returns:
        Routes for driving, walking, and cycling modes
    """
    modes = ["driving", "walking", "cycling"]
    tasks = [
        get_route.ainvoke({"origin": origin, "destination": destination, "transport_mode": mode})
        for mode in modes
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    routes = {}
    for mode, result in zip(modes, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to get {mode} route: {result}")
            routes[mode] = {"error": str(result)}
        else:
            routes[mode] = result
    
    return {
        "origin": origin,
        "destination": destination,
        "routes": routes
    }


@tool
async def search_flights(origin: str, destination: str, date: str) -> Dict[str, Any]:
    """Search for flight options between cities.
    Automatically resolves city names to airport codes.
    
    Args:
        origin: Origin city name (e.g., 'Delhi', 'Mumbai')
        destination: Destination city name
        date: Departure date in YYYY-MM-DD format
    
    Returns:
        List of available flights with pricing and schedules
    """
    headers = {
        "X-RapidAPI-Key": settings.rapidapi_key,
        "X-RapidAPI-Host": MapsServiceHelpers.SKYSCANNER_HOST
    }

    async with httpx.AsyncClient() as client:
        async def resolve_airport(query_str: str) -> Optional[Dict[str, str]]:
            try:
                # Try prefix-less first (/flights/searchAirport)
                url = f"https://{MapsServiceHelpers.SKYSCANNER_HOST}/flights/searchAirport"
                r = await client.get(url, headers=headers, params={"query": query_str}, timeout=8)
                if r.status_code == 404:
                    # Fallback to /api/v1/flights/searchAirport
                    url = f"https://{MapsServiceHelpers.SKYSCANNER_HOST}/api/v1/flights/searchAirport"
                    r = await client.get(url, headers=headers, params={"query": query_str}, timeout=8)

                if r.status_code == 200:
                    data = r.json()
                    places = []
                    if isinstance(data, dict):
                        if "data" in data:
                            d = data["data"]
                            if isinstance(d, list):
                                places = d
                            elif isinstance(d, dict):
                                places = d.get("places", [])
                        elif "places" in data:
                            places = data["places"]
                    elif isinstance(data, list):
                        places = data
                    
                    if places:
                        return {
                            "skyId": places[0].get("skyId"),
                            "entityId": places[0].get("entityId")
                        }
            except Exception as ex:
                logger.warning(f"Failed to query Skyscanner autocomplete for {query_str}: {ex}")
            return None

        # 1. Resolve origin
        origin_info = await resolve_airport(origin)
        origin_sky_id = origin_info["skyId"] if origin_info else None
        origin_entity_id = origin_info["entityId"] if origin_info else ""

        # Fallback to hardcoded list if autocomplete failed
        if not origin_sky_id:
            fallback_code = MapsServiceHelpers.resolve_airport_code(origin)
            if fallback_code:
                origin_info = await resolve_airport(fallback_code)
                origin_sky_id = origin_info["skyId"] if origin_info else fallback_code
                origin_entity_id = origin_info["entityId"] if origin_info else ""

        # 2. Resolve destination
        dest_info = await resolve_airport(destination)
        dest_sky_id = dest_info["skyId"] if dest_info else None
        dest_entity_id = dest_info["entityId"] if dest_info else ""

        # Fallback to hardcoded list if autocomplete failed
        if not dest_sky_id:
            fallback_code = MapsServiceHelpers.resolve_airport_code(destination)
            if fallback_code:
                dest_info = await resolve_airport(fallback_code)
                dest_sky_id = dest_info["skyId"] if dest_info else fallback_code
                dest_entity_id = dest_info["entityId"] if dest_info else ""

        if not origin_sky_id or not dest_sky_id:
            return {
                "origin": origin,
                "destination": destination,
                "date": date,
                "flights": [],
                "count": 0,
                "note": f"Could not resolve airport codes for {origin} and/or {destination}"
            }

        try:
            params = {
                "originSkyId": origin_sky_id,
                "destinationSkyId": dest_sky_id,
                "date": date,
                "adults": "1",
                "currency": "INR"
            }
            if origin_entity_id:
                params["originEntityId"] = origin_entity_id
            if dest_entity_id:
                params["destinationEntityId"] = dest_entity_id

            # Try prefix-less first (/flights/searchFlights)
            url_search = f"https://{MapsServiceHelpers.SKYSCANNER_HOST}/flights/searchFlights"
            resp = await client.get(url_search, headers=headers, params=params, timeout=20)
            if resp.status_code == 404:
                # Fallback to /api/v1/flights/searchFlights
                url_search = f"https://{MapsServiceHelpers.SKYSCANNER_HOST}/api/v1/flights/searchFlights"
                resp = await client.get(url_search, headers=headers, params=params, timeout=20)

            resp.raise_for_status()
            data = resp.json()
            
            raw_flights = []
            if "data" in data and isinstance(data["data"], dict):
                raw_flights = data["data"].get("itineraries", [])
            elif isinstance(data, dict):
                raw_flights = data.get("itineraries", [])

            flights = []
            for f in raw_flights[:8]:
                legs = f.get("legs", [{}])
                leg = legs[0] if legs else {}
                
                # Robust Airline parsing
                carriers_data = leg.get("carriers", {})
                airline = "Unknown"
                if isinstance(carriers_data, dict):
                    marketing = carriers_data.get("marketing")
                    if isinstance(marketing, list) and marketing:
                        airline = marketing[0].get("name", "Unknown")
                    elif isinstance(carriers_data.get("marketing"), dict):
                        airline = carriers_data.get("marketing", {}).get("name", "Unknown")
                elif isinstance(carriers_data, list) and carriers_data:
                    airline = carriers_data[0].get("name", "Unknown")
                
                # Robust Price parsing
                price_data = f.get("price", {})
                price = None
                if isinstance(price_data, dict):
                    price = price_data.get("amount") if price_data.get("amount") is not None else price_data.get("raw")
                elif isinstance(price_data, (int, float)):
                    price = price_data

                # Robust Duration parsing
                duration_minutes = leg.get("durationMinutes") if leg.get("durationMinutes") is not None else leg.get("durationInMinutes")
                
                flights.append({
                    "airline": airline,
                    "price": price,
                    "currency": price_data.get("currency", "INR") if isinstance(price_data, dict) else "INR",
                    "departure_time": leg.get("departure", ""),
                    "arrival_time": leg.get("arrival", ""),
                    "duration_minutes": duration_minutes,
                    "stops": leg.get("stopCount", 0),
                    "origin_code": origin_sky_id,
                    "dest_code": dest_sky_id,
                })
            
            return {
                "origin": origin,
                "destination": destination,
                "origin_code": origin_sky_id,
                "dest_code": dest_sky_id,
                "date": date,
                "flights": flights,
                "count": len(flights)
            }
            
        except Exception as e:
            logger.error(f"Flight search failed: {e}")
            return {"error": str(e), "flights": [], "count": 0, "note": f"Flight search failed: {str(e)}"}


@tool
async def search_trains(origin: str, destination: str, date: str) -> Dict[str, Any]:
    """Search for train options between cities (Indian Railways).
    Automatically resolves city names to station codes.
    
    Args:
        origin: Origin city name (e.g., 'Delhi', 'Mumbai')
        destination: Destination city name
        date: Journey date in YYYY-MM-DD format
    
    Returns:
        List of available trains with schedules and pricing
    """
    from_code = MapsServiceHelpers.resolve_station_code(origin)
    to_code = MapsServiceHelpers.resolve_station_code(destination)

    if not from_code or not to_code:
        return {
            "origin": origin,
            "destination": destination,
            "date": date,
            "trains": [],
            "count": 0,
            "note": f"Could not resolve station codes for {origin} and/or {destination}"
        }

    try:
        url = f"https://{MapsServiceHelpers.TRAINS_HOST}/api/v3/trainBetweenStations"
        headers = {
            "X-RapidAPI-Key": settings.rapidapi_key,
            "X-RapidAPI-Host": MapsServiceHelpers.TRAINS_HOST
        }
        params = {
            "fromStationCode": from_code,
            "toStationCode": to_code,
            "dateOfJourney": date
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            trains_raw = resp.json().get("data", [])

            trains = [{
                "train_number": t.get("train_number", ""),
                "train_name": t.get("train_name", "Unknown"),
                "departure_time": t.get("from_std", t.get("departure_time", "")),
                "arrival_time": t.get("to_std", t.get("arrival_time", "")),
                "duration": t.get("duration", ""),
                "classes": t.get("class_type", []),
                "from_station": from_code,
                "to_station": to_code,
                "days_of_run": t.get("run_days", ""),
            } for t in trains_raw[:10]]
            
            return {
                "origin": origin,
                "destination": destination,
                "from_station": from_code,
                "to_station": to_code,
                "date": date,
                "trains": trains,
                "count": len(trains)
            }
            
    except Exception as e:
        logger.error(f"Train search failed: {e}")
        return {"error": str(e), "trains": [], "count": 0}


@tool
async def search_buses(origin: str, destination: str, date: str) -> Dict[str, Any]:
    """Search for bus and public transit options between cities using TripGo.
    
    Args:
        origin: Origin city name
        destination: Destination city name
        date: Journey date in YYYY-MM-DD format
    
    Returns:
        List of available buses/transit with schedules and pricing
    """
    try:
        # Geocode both locations
        origin_geo = await geocode_location.ainvoke({"location": origin})
        dest_geo = await geocode_location.ainvoke({"location": destination})

        if "error" in origin_geo or "error" in dest_geo:
            return {
                "origin": origin,
                "destination": destination,
                "date": date,
                "buses": [],
                "count": 0,
                "note": "Could not geocode locations for transit search"
            }

        url = f"https://{MapsServiceHelpers.TRIPGO_HOST}/routing.json"
        headers = {
            "X-RapidAPI-Key": settings.rapidapi_key,
            "X-RapidAPI-Host": MapsServiceHelpers.TRIPGO_HOST
        }
        params = {
            "from": f"({origin_geo['latitude']},{origin_geo['longitude']})",
            "to": f"({dest_geo['latitude']},{dest_geo['longitude']})",
            "modes": "pt_pub",
            "departAfter": f"{date}T08:00:00",
            "bestOnly": "false",
            "v": "12"
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params=params, timeout=15)
            if resp.status_code == 404:
                url_fallback = f"https://{MapsServiceHelpers.TRIPGO_HOST}/v1/routing.json"
                resp = await client.get(url_fallback, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            groups = data.get("groups", [])
            buses = []
            for group in groups[:6]:
                for trip in group.get("trips", [])[:2]:
                    segments = trip.get("segments", [])
                    sched_segs = [
                        s for s in segments
                        if s.get("type", "") == "scheduled"
                        or s.get("modeInfo", {}).get("alt", "").lower()
                        in ("bus", "coach", "public transport", "ferry")
                    ]
                    if sched_segs:
                        seg = sched_segs[0]
                        buses.append({
                            "operator_name": seg.get("serviceOperator",
                                                     seg.get("modeInfo", {}).get("alt", "Transit")),
                            "bus_type": seg.get("modeInfo", {}).get("alt", "Public Transit"),
                            "departure_time": seg.get("startTime", ""),
                            "arrival_time": seg.get("endTime", ""),
                            "duration_minutes": trip.get("durationMinutes",
                                                         seg.get("duration", 0) // 60
                                                         if seg.get("duration") else None),
                            "price": trip.get("moneyCost"),
                            "currency": trip.get("currencySymbol", "\u20b9"),
                            "service_number": seg.get("serviceNumber", ""),
                        })

            note = None
            if isinstance(data, dict) and "error" in data:
                err_msg = data["error"]
                if "outside covered area" in err_msg.lower():
                    note = "Transit coverage is limited for this region in TripGo. Local private & state buses (e.g., RedBus, MSRTC, KSRTC) run frequently on this route."
                else:
                    note = f"Transit search error: {err_msg}"

            if not buses and not note:
                note = "No bus/transit options found. Consider checking local operators or platforms like RedBus."

            return {
                "origin": origin,
                "destination": destination,
                "date": date,
                "buses": buses[:8],
                "count": len(buses[:8]),
                "note": note
            }

    except Exception as e:
        logger.error(f"Bus/transit search failed: {e}")
        return {"error": str(e), "buses": [], "count": 0, "note": f"Transit search failed: {str(e)}"}


@tool
async def search_hotels(location: str, checkin: str, checkout: str) -> Dict[str, Any]:
    """Search for hotels at a location.
    
    Args:
        location: Location to search for hotels
        checkin: Check-in date (YYYY-MM-DD)
        checkout: Check-out date (YYYY-MM-DD)
    
    Returns:
        List of available hotels with pricing and amenities
    """
    try:
        url = f"https://{MapsServiceHelpers.HOTELS_HOST}/v1/hotels/search"
        headers = {
            "X-RapidAPI-Key": settings.rapidapi_key,
            "X-RapidAPI-Host": MapsServiceHelpers.HOTELS_HOST
        }
        params = {
            "location": location,
            "checkin_date": checkin,
            "checkout_date": checkout,
            "currency": "INR"
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            
            return {
                "location": location,
                "checkin": checkin,
                "checkout": checkout,
                "hotels": data.get("result", []),
                "count": len(data.get("result", []))
            }
            
    except Exception as e:
        logger.error(f"Hotel search failed: {e}")
        return {"error": str(e)}


@tool
async def get_comprehensive_travel_options(
    origin: str,
    destination: str,
    date: str,
    checkin: Optional[str] = None,
    checkout: Optional[str] = None
) -> Dict[str, Any]:
    """Get comprehensive travel options including routes, flights, trains, buses, and hotels.
    
    Args:
        origin: Starting location name
        destination: Destination location name
        date: Travel date in YYYY-MM-DD format
        checkin: Hotel check-in date (optional, defaults to travel date)
        checkout: Hotel check-out date (optional, defaults to travel date)
    
    Returns:
        Comprehensive travel information including all transport modes and accommodation
    """
    try:
        # Set default checkin/checkout if not provided
        checkin = checkin or date
        checkout = checkout or date
        
        # Fetch all options in parallel — tools now auto-resolve codes
        tasks = [
            get_route.ainvoke({"origin": origin, "destination": destination, "transport_mode": "driving"}),
            search_flights.ainvoke({"origin": origin, "destination": destination, "date": date}),
            search_trains.ainvoke({"origin": origin, "destination": destination, "date": date}),
            search_buses.ainvoke({"origin": origin, "destination": destination, "date": date}),
            search_hotels.ainvoke({"location": destination, "checkin": checkin, "checkout": checkout})
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            "origin": origin,
            "destination": destination,
            "date": date,
            "driving_route": results[0] if not isinstance(results[0], Exception) else {"error": str(results[0])},
            "flights": results[1] if not isinstance(results[1], Exception) else {"error": str(results[1]), "flights": [], "count": 0},
            "trains": results[2] if not isinstance(results[2], Exception) else {"error": str(results[2]), "trains": [], "count": 0},
            "buses": results[3] if not isinstance(results[3], Exception) else {"error": str(results[3]), "buses": [], "count": 0},
            "hotels": results[4] if not isinstance(results[4], Exception) else {"error": str(results[4])}
        }
        
    except Exception as e:
        logger.error(f"Comprehensive travel options failed: {e}")
        return {"error": str(e)}


# ========================= TOOL LIST FOR AGENT ========================= #

MAPS_TOOLS = [
    geocode_location,
    get_route,
    get_multiple_routes,
    search_flights,
    search_trains,
    search_buses,
    search_hotels,
    get_comprehensive_travel_options
]