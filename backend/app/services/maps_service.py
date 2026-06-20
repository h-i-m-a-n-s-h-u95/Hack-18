import httpx
import asyncio
import math
import logging
from typing import List, Optional, Dict, Any
from app.config.settings import settings
from app.core.state import RouteInfo

logger = logging.getLogger(__name__)

class MapsService:
    """Service for routing, geocoding and travel option aggregation"""

    def __init__(self):
        # OpenRouteService setup
        self.api_key = settings.openroute_api_key
        self.base_url = "https://api.openrouteservice.org"

        # RapidAPI key for travel options
        self.rapidapi_key = settings.rapidapi_key

        # Transport mode mapping
        self.transport_modes = {
            "driving": "driving-car",
            "walking": "foot-walking",
            "cycling": "cycling-regular",
            "public_transport": "driving-car"  # fallback
        }

        # RapidAPI hosts
        self.skyscanner_host = settings.skyscanner_host
        self.trains_host = settings.trains_host
        self.tripgo_host = settings.tripgo_host
        self.hotels_host = settings.hotels_host

        # Well-known IATA airport codes (fallback when API unavailable)
        self._airport_codes = {
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
            "jammu": "IXJ",
        }

        # Well-known IRCTC station codes (fallback when API unavailable)
        self._station_codes = {
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

        # Geocoding cache to prevent redundant HTTP requests
        self._geocode_cache = {}

    # ------------------------------
    # Geocoding & Routing
    # ------------------------------
    async def geocode_location(self, location: str) -> Optional[Dict[str, Any]]:
        """Geocode a location string to coordinates.

        Tries OpenRouteService first, then falls back to Nominatim (OSM)
        if the ORS call fails (e.g. expired API key).
        """
        loc_key = location.strip().lower()
        if loc_key in self._geocode_cache:
            logger.info(f"Geocoding cache hit in MapsService for '{location}'")
            return self._geocode_cache[loc_key]

        # --- Primary: OpenRouteService ---
        try:
            async with httpx.AsyncClient() as client:
                headers = {"Authorization": self.api_key}
                params = {
                    "text": location, 
                    "size": 1, 
                    "layers": "locality,region,country"
                }
                r = await client.get(
                    f"{self.base_url}/geocode/search", 
                    headers=headers, 
                    params=params,
                    timeout=10
                )
                r.raise_for_status()
                data = r.json()
                
                if data.get("features"):
                    f = data["features"][0]
                    coords = f["geometry"]["coordinates"]
                    props = f["properties"]
                    
                    result = {
                        "coordinates": [coords[1], coords[0]],  # [lat, lon]
                        "name": props.get("name", location),
                        "region": props.get("region", ""),
                        "country": props.get("country", ""),
                        "confidence": props.get("confidence", 0)
                    }
                    self._geocode_cache[loc_key] = result
                    return result
        except Exception as e:
            logger.warning(f"ORS geocoding failed for '{location}': {e}")

        # --- Fallback: Nominatim (OpenStreetMap) ---
        try:
            logger.info(f"Trying Nominatim fallback for '{location}'")
            async with httpx.AsyncClient() as client:
                params = {
                    "q": location,
                    "format": "json",
                    "limit": 1,
                    "addressdetails": 1,
                }
                r = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params=params,
                    headers={"User-Agent": "TBuddy/2.0 (travel-planner)"},
                    timeout=10,
                )
                r.raise_for_status()
                results = r.json()

                if results:
                    hit = results[0]
                    lat = float(hit["lat"])
                    lon = float(hit["lon"])
                    addr = hit.get("address", {})
                    result = {
                        "coordinates": [lat, lon],
                        "name": hit.get("display_name", location).split(",")[0],
                        "region": addr.get("state", ""),
                        "country": addr.get("country", ""),
                        "confidence": 0.8,
                    }
                    self._geocode_cache[loc_key] = result
                    return result
        except Exception as e:
            logger.error(f"Nominatim fallback also failed for '{location}': {e}")

        return None

    async def get_route(
        self, 
        start_coords: List[float], 
        end_coords: List[float], 
        transport_mode: str = "driving"
    ) -> Optional[Dict[str, Any]]:
        """Get route between coordinates"""
        try:
            profile = self.transport_modes.get(transport_mode, "driving-car")
            coords = [
                [start_coords[1], start_coords[0]], 
                [end_coords[1], end_coords[0]]
            ]
            
            headers = {
                "Authorization": self.api_key, 
                "Content-Type": "application/json"
            }
            payload = {
                "coordinates": coords, 
                "instructions": True, 
                "geometry": True
            }
            
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{self.base_url}/v2/directions/{profile}/geojson",
                    headers=headers, 
                    json=payload, 
                    timeout=30
                )
                r.raise_for_status()
                return r.json()
                
        except Exception as e:
            logger.error(f"Route fetch failed: {e}")
            return await self._calculate_fallback_route(
                start_coords, end_coords, transport_mode
            )

    async def _calculate_fallback_route(
        self, 
        start_coords: List[float], 
        end_coords: List[float], 
        transport_mode: str
    ) -> Dict[str, Any]:
        """Calculate fallback route using haversine formula.

        Includes a straight-line geometry so the frontend can still draw
        a polyline on the Leaflet map.
        """
        try:
            lat1, lon1 = math.radians(start_coords[0]), math.radians(start_coords[1])
            lat2, lon2 = math.radians(end_coords[0]), math.radians(end_coords[1])
            
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            
            a = (math.sin(dlat/2)**2 + 
                 math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2)
            c = 2 * math.asin(math.sqrt(a))
            dist_km = 6371 * c
            
            # Estimate duration based on mode
            speeds = {
                "driving": 50, 
                "walking": 5, 
                "cycling": 15, 
                "public_transport": 35
            }
            speed = speeds.get(transport_mode, 50)
            dur_seconds = (dist_km / speed) * 3600

            # Build a straight-line geometry with intermediate points
            # so the frontend can draw a visible polyline.
            num_points = max(10, int(dist_km / 20))  # ~1 point per 20 km
            line_coords = []
            for i in range(num_points + 1):
                t = i / num_points
                lat = start_coords[1] + t * (end_coords[1] - start_coords[1])  # lon
                lng = start_coords[0] + t * (end_coords[0] - start_coords[0])  # lat
                # ORS GeoJSON uses [lon, lat]
                line_coords.append([lat, lng])
            
            return {
                "features": [{
                    "geometry": {
                        "type": "LineString",
                        "coordinates": line_coords,
                    },
                    "properties": {
                        "summary": {
                            "distance": dist_km * 1000,  # meters
                            "duration": dur_seconds
                        }
                    }
                }]
            }
        except Exception as e:
            logger.error(f"Fallback route calculation failed: {e}")
            # Minimal fallback with just start→end line
            return {
                "features": [{
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [start_coords[1], start_coords[0]],
                            [end_coords[1], end_coords[0]],
                        ],
                    },
                    "properties": {
                        "summary": {
                            "distance": 10000,
                            "duration": 1800
                        }
                    }
                }]
            }

    async def get_route_between_locations(
        self,
        origin: str,
        destination: str,
        transport_mode: str = "driving"
    ) -> Optional[RouteInfo]:
        """
        Get route between two location names (main method used by agent)
        Returns RouteInfo object
        """
        try:
            # Geocode both locations
            origin_geo = await self.geocode_location(origin)
            dest_geo = await self.geocode_location(destination)
            
            if not origin_geo or not dest_geo:
                logger.warning(f"Geocoding failed for {origin} or {destination}")
                return None
            
            # Get route
            route_data = await self.get_route(
                origin_geo["coordinates"],
                dest_geo["coordinates"],
                transport_mode
            )
            
            if not route_data:
                return None
            
            # Parse route data
            return self._parse_route_to_info(route_data, transport_mode)
            
        except Exception as e:
            logger.error(f"Route between locations failed: {e}")
            return None

    def _parse_route_to_info(
        self, 
        route_data: Dict[str, Any], 
        transport_mode: str
    ) -> RouteInfo:
        """Parse raw route data into RouteInfo object"""
        try:
            if not route_data.get("features"):
                raise ValueError("No route features in response")
            
            feature = route_data["features"][0]
            props = feature.get("properties", {})
            summary = props.get("summary", {})
            
            # Extract distance and duration
            distance_m = summary.get("distance", 0)
            duration_s = summary.get("duration", 0)
            
            # Format distance
            if distance_m >= 1000:
                distance_str = f"{distance_m / 1000:.1f} km"
            else:
                distance_str = f"{distance_m:.0f} m"
            
            # Format duration
            hours = int(duration_s // 3600)
            minutes = int((duration_s % 3600) // 60)
            if hours > 0:
                duration_str = f"{hours}h {minutes}m"
            else:
                duration_str = f"{minutes}m"
            
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
            
            return RouteInfo(
                distance=distance_str,
                duration=duration_str,
                steps=steps[:10],  # Limit to 10 steps
                traffic_info=None,
                transport_mode=transport_mode
            )
            
        except Exception as e:
            logger.error(f"Route parsing failed: {e}")
            return RouteInfo(
                distance="Unknown",
                duration="Unknown",
                steps=["Route details unavailable"],
                traffic_info=None,
                transport_mode=transport_mode
            )

    async def get_multiple_route_options(
        self,
        origin: str,
        destination: str
    ) -> Dict[str, Optional[RouteInfo]]:
        """Get routes for all transport modes"""
        modes = ["driving", "walking", "cycling"]
        tasks = [
            self.get_route_between_locations(origin, destination, mode)
            for mode in modes
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        routes = {}
        for mode, result in zip(modes, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to get {mode} route: {result}")
                routes[mode] = None
            else:
                routes[mode] = result
        
        return routes

    # ------------------------------
    # Code Resolution Helpers
    # ------------------------------
    def resolve_airport_code(self, city_name: str) -> Optional[str]:
        """Resolve city name to IATA airport code using local lookup."""
        key = city_name.strip().lower()
        return self._airport_codes.get(key)

    def resolve_station_code(self, city_name: str) -> Optional[str]:
        """Resolve city name to IRCTC station code using local lookup."""
        key = city_name.strip().lower()
        return self._station_codes.get(key)

    # ------------------------------
    # Travel Options (Flights, Trains, Buses, Hotels)
    # ------------------------------
    async def get_flight_options(
        self, 
        origin: str, 
        destination: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        """Fetch flight options via Skyscanner RapidAPI.
        Resolves city names to IATA codes automatically."""
        if " to " in date:
            date = date.split(" to ")[0].strip()
        if "T" in date:
            date = date.split("T")[0].strip()
        headers = {
            "X-RapidAPI-Key": self.rapidapi_key,
            "X-RapidAPI-Host": self.skyscanner_host
        }

        async with httpx.AsyncClient() as client:
            async def resolve_airport(query_str: str) -> Optional[Dict[str, str]]:
                try:
                    # Try prefix-less first (/flights/searchAirport)
                    url = f"https://{self.skyscanner_host}/flights/searchAirport"
                    r = await client.get(url, headers=headers, params={"query": query_str}, timeout=8)
                    if r.status_code == 404:
                        # Fallback to /api/v1/flights/searchAirport
                        url = f"https://{self.skyscanner_host}/api/v1/flights/searchAirport"
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
                fallback_code = self.resolve_airport_code(origin)
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
                fallback_code = self.resolve_airport_code(destination)
                if fallback_code:
                    dest_info = await resolve_airport(fallback_code)
                    dest_sky_id = dest_info["skyId"] if dest_info else fallback_code
                    dest_entity_id = dest_info["entityId"] if dest_info else ""

            if not origin_sky_id or not dest_sky_id:
                logger.warning(f"Cannot resolve Skyscanner IDs: {origin}={origin_sky_id}, {destination}={dest_sky_id}")
                return []

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
                url_search = f"https://{self.skyscanner_host}/flights/searchFlights"
                r = await client.get(url_search, headers=headers, params=params, timeout=20)
                if r.status_code == 404:
                    # Fallback to /api/v1/flights/searchFlights
                    url_search = f"https://{self.skyscanner_host}/api/v1/flights/searchFlights"
                    r = await client.get(url_search, headers=headers, params=params, timeout=20)

                r.raise_for_status()
                data = r.json()
                
                flights = []
                if "data" in data and isinstance(data["data"], dict):
                    flights = data["data"].get("itineraries", [])
                elif isinstance(data, dict):
                    flights = data.get("itineraries", [])

                # Normalize to a consistent format
                normalized_flights = []
                for f in flights[:8]:
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

                    normalized_flights.append({
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
                return normalized_flights
                
            except Exception as e:
                logger.error(f"Flight fetch failed: {e}")
                return []

    async def get_train_options(
        self, 
        origin: str, 
        destination: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        """Fetch train options via IRCTC RapidAPI.
        Resolves city names to station codes automatically."""
        if " to " in date:
            date = date.split(" to ")[0].strip()
        if "T" in date:
            date = date.split("T")[0].strip()
        from_code = self.resolve_station_code(origin)
        to_code = self.resolve_station_code(destination)

        if not from_code or not to_code:
            logger.warning(f"Cannot resolve station codes: {origin}={from_code}, {destination}={to_code}")
            return []

        try:
            url = f"https://{self.trains_host}/api/v3/trainBetweenStations"
            headers = {
                "X-RapidAPI-Key": self.rapidapi_key,
                "X-RapidAPI-Host": self.trains_host
            }
            params = {
                "fromStationCode": from_code,
                "toStationCode": to_code,
                "dateOfJourney": date
            }
            
            async with httpx.AsyncClient() as client:
                r = await client.get(url, headers=headers, params=params, timeout=15)
                r.raise_for_status()
                trains_raw = r.json().get("data", [])
                # Normalize to a consistent format
                return [{
                    "train_number": t.get("train_number", ""),
                    "train_name": t.get("train_name", "Unknown"),
                    "departure_time": t.get("from_std", t.get("departure_time", "")),
                    "arrival_time": t.get("to_std", t.get("arrival_time", "")),
                    "duration": t.get("duration", ""),
                    "classes": t.get("class_type", []),
                    "from_station": from_code,
                    "to_station": to_code,
                    "days_of_run": t.get("run_days", ""),
                } for t in trains_raw[:10]]  # Limit to 10 results
                
        except Exception as e:
            logger.error(f"Train fetch failed: {e}")
            return []

    async def get_bus_options(
        self, 
        origin: str, 
        destination: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        """Fetch bus/transit options via TripGo API.
        Uses TripGo for multi-modal transit results including buses."""
        if " to " in date:
            date = date.split(" to ")[0].strip()
        if "T" in date:
            date = date.split("T")[0].strip()
        try:
            # First geocode both locations to get coordinates
            origin_geo = await self.geocode_location(origin)
            dest_geo = await self.geocode_location(destination)

            if not origin_geo or not dest_geo:
                logger.warning(f"Cannot geocode for bus search: {origin} or {destination}")
                return []

            url = f"https://{self.tripgo_host}/routing.json"
            headers = {
                "X-RapidAPI-Key": self.rapidapi_key,
                "X-RapidAPI-Host": self.tripgo_host
            }
            params = {
                "from": f"({origin_geo['coordinates'][0]},{origin_geo['coordinates'][1]})",
                "to": f"({dest_geo['coordinates'][0]},{dest_geo['coordinates'][1]})",
                "modes": "pt_pub",  # public transport
                "departAfter": f"{date}T08:00:00",
                "bestOnly": "false",
                "v": "12"
            }

            async with httpx.AsyncClient() as client:
                r = await client.get(url, headers=headers, params=params, timeout=15)
                if r.status_code == 404:
                    url_fallback = f"https://{self.tripgo_host}/v1/routing.json"
                    r = await client.get(url_fallback, headers=headers, params=params, timeout=15)
                r.raise_for_status()
                data = r.json()

                # Parse TripGo response into bus-like results
                groups = data.get("groups", [])
                results = []
                for group in groups[:6]:
                    trips = group.get("trips", [])
                    for trip in trips[:2]:
                        segments = trip.get("segments", [])
                        bus_segments = [
                            s for s in segments
                            if s.get("modeInfo", {}).get("alt", "").lower() in
                            ("bus", "coach", "public transport", "ferry", "train")
                        ]
                        if not bus_segments:
                            bus_segments = [s for s in segments if s.get("type", "") == "scheduled"]

                        if bus_segments:
                            seg = bus_segments[0]
                            results.append({
                                "operator_name": seg.get("serviceOperator", seg.get("modeInfo", {}).get("alt", "Transit")),
                                "bus_type": seg.get("modeInfo", {}).get("alt", "Public Transit"),
                                "departure_time": seg.get("startTime", ""),
                                "arrival_time": seg.get("endTime", ""),
                                "duration_minutes": trip.get("durationMinutes", seg.get("duration", 0) // 60 if seg.get("duration") else None),
                                "price": trip.get("moneyCost"),
                                "currency": trip.get("currencySymbol", "₹"),
                                "service_number": seg.get("serviceNumber", ""),
                            })
                return results[:8]  # Limit to 8

        except Exception as e:
            logger.error(f"Bus/transit fetch failed (TripGo): {e}")
            return []

    async def get_hotels_near_location(
        self, 
        location: str, 
        checkin: str, 
        checkout: str
    ) -> List[Dict[str, Any]]:
        """Fetch hotel options via RapidAPI"""
        try:
            url = f"https://{self.hotels_host}/v1/hotels/search"
            headers = {
                "X-RapidAPI-Key": self.rapidapi_key,
                "X-RapidAPI-Host": self.hotels_host
            }
            params = {
                "location": location,
                "checkin_date": checkin,
                "checkout_date": checkout,
                "currency": "INR"
            }
            
            async with httpx.AsyncClient() as client:
                r = await client.get(url, headers=headers, params=params, timeout=15)
                r.raise_for_status()
                return r.json().get("result", [])
                
        except Exception as e:
            logger.error(f"Hotel fetch failed: {e}")
            return []

    async def get_travel_options(
        self,
        origin: str,
        destination: str,
        date: str,
        checkin: Optional[str] = None,
        checkout: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Aggregate all travel options in parallel.
        Automatically resolves airport/station codes from city names.
        Returns routes, flights, trains, buses, and hotels.
        """
        try:
            # Geocode locations first
            origin_geo = await self.geocode_location(origin)
            dest_geo = await self.geocode_location(destination)
            
            if not origin_geo or not dest_geo:
                logger.warning("Geocoding failed for travel options")
                return {}
            
            # Parallel fetch all options — code resolution happens inside each method
            tasks = [
                self.get_route(
                    origin_geo["coordinates"], 
                    dest_geo["coordinates"], 
                    "driving"
                ),
                self.get_flight_options(origin, destination, date),
                self.get_train_options(origin, destination, date),
                self.get_bus_options(origin, destination, date),
                self.get_hotels_near_location(
                    destination, 
                    checkin or date, 
                    checkout or date
                )
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Parse results gracefully
            driving_route = results[0] if not isinstance(results[0], Exception) else None
            flights = results[1] if not isinstance(results[1], Exception) else []
            trains = results[2] if not isinstance(results[2], Exception) else []
            buses = results[3] if not isinstance(results[3], Exception) else []
            hotels = results[4] if not isinstance(results[4], Exception) else []
            
            logger.info(
                f"Travel options fetched: {len(flights)} flights, "
                f"{len(trains)} trains, {len(buses)} buses"
            )
            
            return {
                "driving_route": self._parse_route_to_info(driving_route, "driving") if driving_route else None,
                "flights": flights,
                "trains": trains,
                "buses": buses,
                "hotels": hotels
            }
            
        except Exception as e:
            logger.error(f"Travel options aggregation failed: {e}")
            return {}