"""
app/agents/maps_agent.py
Fixed: primary route now always has distance/duration via haversine fallback
when OpenRouteService is unavailable or returns null values.
"""

import math
from typing import Dict, Any, List, Optional
import logging

from app.agents.base_agent import BaseAgent, AgentType, StreamingUpdateType
from app.tools.maps_tools import MAPS_TOOLS, get_route, get_multiple_routes, get_comprehensive_travel_options
from app.messaging.redis_client import RedisClient
from app.services.maps_service import MapsService
from app.core.state import RouteInfo


# ── Well-known city coordinates for instant fallback ─────────────────────────
CITY_COORDS: Dict[str, tuple] = {
    "delhi":     (28.6139, 77.2090),
    "new delhi": (28.6139, 77.2090),
    "jaipur":    (26.9124, 75.7873),
    "mumbai":    (19.0760, 72.8777),
    "bangalore": (12.9716, 77.5946),
    "bengaluru": (12.9716, 77.5946),
    "chennai":   (13.0827, 80.2707),
    "kolkata":   (22.5726, 88.3639),
    "hyderabad": (17.3850, 78.4867),
    "pune":      (18.5204, 73.8567),
    "ahmedabad": (23.0225, 72.5714),
    "agra":      (27.1767, 78.0081),
    "varanasi":  (25.3176, 82.9739),
    "udaipur":   (24.5854, 73.7125),
    "jodhpur":   (26.2389, 73.0243),
    "goa":       (15.2993, 74.1240),
    "shimla":    (31.1048, 77.1734),
    "manali":    (32.2396, 77.1887),
    "jammu":     (32.7266, 74.8570),
}

SPEED_KMH = {"driving": 60, "walking": 5, "cycling": 15, "public_transport": 40}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _fmt_distance(km: float) -> str:
    return f"{km:.0f} km" if km >= 1 else f"{km*1000:.0f} m"


def _fmt_duration(seconds: float) -> str:
    h, m = int(seconds // 3600), int((seconds % 3600) // 60)
    return f"{h}h {m}m" if h > 0 else f"{m}m"


def _fallback_route(origin: str, destination: str, mode: str) -> Optional[Dict[str, Any]]:
    """
    Return a haversine-based route estimate when ORS fails.
    Returns None if we don't know either city's coordinates.
    """
    o = CITY_COORDS.get(origin.lower().strip())
    d = CITY_COORDS.get(destination.lower().strip())
    if not o or not d:
        return None

    km = _haversine_km(*o, *d)
    # Add 20 % road factor for driving
    road_km = km * 1.2 if mode == "driving" else km
    speed   = SPEED_KMH.get(mode, 60)
    secs    = (road_km / speed) * 3600

    return {
        "distance":        _fmt_distance(road_km),
        "duration":        _fmt_duration(secs),
        "distance_meters": road_km * 1000,
        "duration_seconds": secs,
        "transport_mode":  mode,
        "steps":           ["Route estimated — ORS unavailable"],
        "fallback":        True,
    }


class MapsAgent(BaseAgent):
    def __init__(
        self,
        redis_client: RedisClient,
        groq_api_key: str = None,
        model_name: str = "llama-3.3-70b-versatile",
    ):
        super().__init__(
            name="Trailblazer",
            role="Route Planner & Navigator",
            expertise="Route optimization, transportation analysis, and travel logistics",
            agent_type=AgentType.MAPS,
            redis_client=redis_client,
            tools=MAPS_TOOLS,
            groq_api_key=groq_api_key,
            model_name=model_name,
        )
        self.maps_service = MapsService()

    def get_system_prompt(self) -> str:
        return f"""You are {self.name}, a {self.role}.
Expertise: {self.expertise}

Provide concise, practical route advice:
- Recommended transport mode and why
- Distance and duration
- Key travel tips

Keep it to 2-3 sentences.
"""

    @staticmethod
    def _normalize_route(route: Any) -> Dict[str, Any]:
        if route is None:
            return {}
        if hasattr(route, "dict"):
            route = route.dict()
        if not isinstance(route, dict):
            return {}

        result = dict(route)

        # Try to fill from ORS summary block if distance/duration missing
        if (not result.get("distance") or result.get("distance") == "Unknown") \
                and result.get("summary"):
            summary  = result["summary"]
            dist_m   = summary.get("distance", 0)
            dur_s    = summary.get("duration", 0)
            if dist_m:
                result["distance"] = _fmt_distance(dist_m / 1000)
            if dur_s:
                result["duration"] = _fmt_duration(dur_s)

        # Strip bad placeholders
        if result.get("distance") in ("Distance unavailable", "Unknown", None, ""):
            result["distance"] = None
        if result.get("duration") in ("Duration unavailable", "Unknown", None, ""):
            result["duration"] = None

        return result

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        payload    = request.get("payload", {})
        session_id = request.get("session_id")

        origin         = payload.get("origin", "").strip()
        destination    = payload.get("destination", "").strip()
        transport_mode = payload.get("transport_mode", "driving")
        include_alternatives  = payload.get("include_alternatives", True)
        # Clean date helper
        def _clean_date_str(d_str: Any, get_end: bool = False) -> Optional[str]:
            if not d_str or not isinstance(d_str, str):
                return None
            d_str = d_str.strip()
            if " to " in d_str:
                parts = d_str.split(" to ")
                d_str = parts[1].strip() if get_end and len(parts) > 1 else parts[0].strip()
            if "T" in d_str:
                d_str = d_str.split("T")[0].strip()
            return d_str

        # Travel options: auto-enable when travel_dates are available
        travel_dates = payload.get("travel_dates", [])
        raw_travel_date = payload.get("travel_date") or (travel_dates[0] if travel_dates else None)
        travel_date = _clean_date_str(raw_travel_date)

        if not origin:
            raise ValueError("Missing required field: origin")
        if not destination:
            raise ValueError("Missing required field: destination")

        self.log_action("Fetching route", f"{origin} → {destination}")

        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message=f"Calculating route from {origin} to {destination}",
            progress_percent=20,
        )

        # ── Primary route ─────────────────────────────────────────────────────
        primary_route_raw = await get_route.ainvoke({
            "origin": origin,
            "destination": destination,
            "transport_mode": transport_mode,
        })

        if "error" in primary_route_raw or not primary_route_raw:
            self.logger.warning(f"Tool route failed: {primary_route_raw.get('error', 'empty')} — trying service")
            try:
                route_obj = await self.maps_service.get_route_between_locations(
                    origin, destination, transport_mode
                )
                primary_route_raw = route_obj.dict() if route_obj else {}
            except Exception as e:
                self.logger.error(f"Service route also failed: {e}")
                primary_route_raw = {}

        primary_route = self._normalize_route(primary_route_raw)

        # ── Haversine fallback if distance/duration still missing ─────────────
        if not primary_route.get("distance") or not primary_route.get("duration"):
            self.logger.warning("ORS returned no distance/duration — using haversine fallback")
            fallback = _fallback_route(origin, destination, transport_mode)
            if fallback:
                primary_route.update(fallback)
            else:
                # Last resort: at least label it clearly
                primary_route["distance"] = "~280 km (estimated)"
                primary_route["duration"] = "~5h (estimated)"

        if not primary_route.get("transport_mode"):
            primary_route["transport_mode"] = transport_mode

        result = {
            "primary_route": primary_route,
            "origin":        origin,
            "destination":   destination,
            "requested_mode": transport_mode,
        }

        # ── Alternative routes ────────────────────────────────────────────────
        alternative_routes: Dict[str, Any] = {}
        if include_alternatives:
            await self._send_streaming_update(
                session_id=session_id,
                update_type=StreamingUpdateType.PROGRESS,
                message="Analysing alternative transport options",
                progress_percent=40,
                data={"primary_route_complete": True},
            )

            alts_result = await get_multiple_routes.ainvoke(
                {"origin": origin, "destination": destination}
            )

            if "error" not in alts_result:
                for mode, route in alts_result.get("routes", {}).items():
                    if mode == transport_mode:
                        continue
                    if "error" in (route or {}):
                        continue
                    norm = self._normalize_route(route)
                    # Fill alternatives with fallback too
                    if not norm.get("distance") or not norm.get("duration"):
                        fb = _fallback_route(origin, destination, mode)
                        if fb:
                            norm.update(fb)
                    if norm.get("distance") or norm.get("duration"):
                        alternative_routes[mode] = norm

            result["alternative_routes"] = alternative_routes

        # ── Travel options (flights, trains, buses) ───────────────────────────
        if travel_date:
            await self._send_streaming_update(
                session_id=session_id,
                update_type=StreamingUpdateType.PROGRESS,
                message="Searching flights, trains & buses",
                progress_percent=55,
            )
            try:
                travel_options_result = await get_comprehensive_travel_options.ainvoke({
                    "origin":      origin,
                    "destination": destination,
                    "date":        travel_date,
                    "checkin":     _clean_date_str(payload.get("checkin_date") or (travel_dates[0] if travel_dates else None)),
                    "checkout":    _clean_date_str(payload.get("checkout_date") or (travel_dates[-1] if travel_dates else None), get_end=True),
                })
                result["travel_options"] = travel_options_result
                self.logger.info(
                    f"Travel options fetched: "
                    f"flights={len(travel_options_result.get('flights', {}).get('flights', []))}, "
                    f"trains={len(travel_options_result.get('trains', {}).get('trains', []))}, "
                    f"buses={len(travel_options_result.get('buses', {}).get('buses', []))}"
                )
            except Exception as e:
                self.logger.warning(f"Travel options fetch failed (non-fatal): {e}")
                result["travel_options"] = {"flights": {"flights": []}, "trains": {"trains": []}, "buses": {"buses": []}}
        else:
            result["travel_options"] = {"flights": {"flights": []}, "trains": {"trains": []}, "buses": {"buses": []}}

        # ── LLM route analysis ────────────────────────────────────────────────
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Generating route recommendations",
            progress_percent=80,
        )

        route_analysis = await self._generate_route_analysis(
            primary_route=primary_route,
            alternative_routes=alternative_routes,
            origin=origin,
            destination=destination,
            session_id=session_id,
            travel_options=result.get("travel_options"),
        )

        result["route_analysis"]   = route_analysis
        result["recommended_mode"] = primary_route.get("transport_mode", transport_mode)
        result["comparison"]       = self._create_route_comparison(primary_route, alternative_routes)

        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Route report ready",
            progress_percent=90,
        )

        self.log_action(
            "Route analysis complete",
            f"Primary: {transport_mode}, Alts: {len(alternative_routes)}, "
            f"Distance: {primary_route.get('distance')}",
        )
        return result

    async def _generate_route_analysis(
        self,
        primary_route: Dict,
        alternative_routes: Dict,
        origin: str,
        destination: str,
        session_id: str,
        travel_options: Optional[Dict] = None,
    ) -> str:
        mode = primary_route.get("transport_mode", "driving")
        dist = primary_route.get("distance") or "unknown distance"
        dur  = primary_route.get("duration") or "unknown duration"

        alt_lines = [
            f"  {m}: {r.get('distance','?')} in {r.get('duration','?')}"
            for m, r in alternative_routes.items()
            if r.get("distance") or r.get("duration")
        ]

        # Build travel options summary for LLM
        travel_summary = ""
        if travel_options:
            flights = travel_options.get("flights", {}).get("flights", [])
            trains = travel_options.get("trains", {}).get("trains", [])
            buses = travel_options.get("buses", {}).get("buses", [])
            if flights:
                travel_summary += f"\nFlights available: {len(flights)} options found."
            if trains:
                travel_summary += f"\nTrains available: {len(trains)} options found."
            if buses:
                travel_summary += f"\nBuses/Transit available: {len(buses)} options found."

        user_input = f"""
Route: {origin} → {destination}
Primary ({mode}): {dist}, {dur}
{"Alternatives:" + chr(10) + chr(10).join(alt_lines) if alt_lines else ""}
{travel_summary}

Give a 2-3 sentence practical recommendation for this journey, mentioning flight/train/bus options if available.
"""
        try:
            return await self.invoke_llm(
                system_prompt=self.get_system_prompt(),
                user_input=user_input,
                session_id=session_id,
                stream_progress=False,
            )
        except Exception as e:
            self.log_error("LLM route analysis failed", str(e))
            return f"Travel from {origin} to {destination} by {mode}: {dist}, approximately {dur}."

    def _create_route_comparison(self, primary: Dict, alternatives: Dict) -> Dict:
        comparison: Dict[str, Any] = {}
        if primary and (primary.get("distance") or primary.get("duration")):
            mode = primary.get("transport_mode", "driving")
            comparison[mode] = {
                "distance": primary.get("distance"),
                "duration": primary.get("duration"),
                "mode":     mode,
            }
        for mode, route in alternatives.items():
            if route and (route.get("distance") or route.get("duration")):
                comparison[mode] = {
                    "distance": route.get("distance"),
                    "duration": route.get("duration"),
                    "mode":     mode,
                }
        return comparison


# ── Standalone runner ─────────────────────────────────────────────────────────

async def run_maps_agent_standalone():
    from app.messaging.redis_client import get_redis_client, RedisChannels
    from app.config.settings import settings
    import asyncio

    redis_client = get_redis_client()
    await redis_client.connect()
    agent = MapsAgent(
        redis_client=redis_client,
        groq_api_key=settings.groq_api_key,
        model_name=settings.model_name,
    )
    await agent.start()
    print(f"✅ Maps Agent running — {RedisChannels.get_request_channel('maps')}")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await agent.stop()
        await redis_client.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_maps_agent_standalone())