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
        self.skyscanner_host = "skyscanner44.p.rapidapi.com"
        self.trains_host = "indian-railway-irctc.p.rapidapi.com"
        self.buses_host = "redbus2.p.rapidapi.com"
        self.hotels_host = "booking-com.p.rapidapi.com"

    # ------------------------------
    # Geocoding & Routing
    # ------------------------------
    async def geocode_location(self, location: str) -> Optional[Dict[str, Any]]:
        """Geocode a location string to coordinates"""
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
                
                if not data.get("features"):
                    return None
                    
                f = data["features"][0]
                coords = f["geometry"]["coordinates"]
                props = f["properties"]
                
                return {
                    "coordinates": [coords[1], coords[0]],  # [lat, lon]
                    "name": props.get("name", location),
                    "region": props.get("region", ""),
                    "country": props.get("country", ""),
                    "confidence": props.get("confidence", 0)
                }
        except Exception as e:
            logger.error(f"Geocoding failed for {location}: {e}")
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
        """Calculate fallback route using haversine formula"""
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
            
            return {
                "features": [{
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
            return {
                "features": [{
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
    # Travel Options (Flights, Trains, Buses, Hotels)
    # ------------------------------
    async def get_flight_options(
        self, 
        origin_code: str, 
        dest_code: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        """Fetch flight options via RapidAPI"""
        try:
            url = f"https://{self.skyscanner_host}/search"
            headers = {
                "X-RapidAPI-Key": self.rapidapi_key,
                "X-RapidAPI-Host": self.skyscanner_host
            }
            params = {
                "origin": origin_code,
                "destination": dest_code,
                "departureDate": date,
                "currency": "INR"
            }
            
            async with httpx.AsyncClient() as client:
                r = await client.get(url, headers=headers, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
                return data.get("itineraries", [])
                
        except Exception as e:
            logger.error(f"Flight fetch failed: {e}")
            return []

    async def get_train_options(
        self, 
        from_station: str, 
        to_station: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        """Fetch train options via RapidAPI"""
        try:
            url = f"https://{self.trains_host}/trainBetweenStations"
            headers = {
                "X-RapidAPI-Key": self.rapidapi_key,
                "X-RapidAPI-Host": self.trains_host
            }
            params = {
                "fromStationCode": from_station,
                "toStationCode": to_station,
                "dateOfJourney": date
            }
            
            async with httpx.AsyncClient() as client:
                r = await client.get(url, headers=headers, params=params, timeout=30)
                r.raise_for_status()
                return r.json().get("data", [])
                
        except Exception as e:
            logger.error(f"Train fetch failed: {e}")
            return []

    async def get_bus_options(
        self, 
        origin: str, 
        destination: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        """Fetch bus options via RapidAPI"""
        try:
            url = f"https://{self.buses_host}/searchBuses"
            headers = {
                "X-RapidAPI-Key": self.rapidapi_key,
                "X-RapidAPI-Host": self.buses_host
            }
            params = {
                "fromCity": origin,
                "toCity": destination,
                "doj": date
            }
            
            async with httpx.AsyncClient() as client:
                r = await client.get(url, headers=headers, params=params, timeout=30)
                r.raise_for_status()
                return r.json().get("buses", [])
                
        except Exception as e:
            logger.error(f"Bus fetch failed: {e}")
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
                r = await client.get(url, headers=headers, params=params, timeout=30)
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
        Aggregate all travel options in parallel
        Returns routes, flights, trains, buses, and hotels
        """
        try:
            # Geocode locations first
            origin_geo = await self.geocode_location(origin)
            dest_geo = await self.geocode_location(destination)
            
            if not origin_geo or not dest_geo:
                logger.warning("Geocoding failed for travel options")
                return {}
            
            # Parallel fetch all options
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
            
            # Parse results
            driving_route = results[0] if not isinstance(results[0], Exception) else None
            flights = results[1] if not isinstance(results[1], Exception) else []
            trains = results[2] if not isinstance(results[2], Exception) else []
            buses = results[3] if not isinstance(results[3], Exception) else []
            hotels = results[4] if not isinstance(results[4], Exception) else []
            
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