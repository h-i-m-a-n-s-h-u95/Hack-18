from typing import Dict, Any, List, Optional
import logging

from app.agents.base_agent import BaseAgent, AgentType, StreamingUpdateType
from app.tools.maps_tools import MAPS_TOOLS, get_route, get_multiple_routes, get_comprehensive_travel_options
from app.messaging.redis_client import RedisClient
from app.services.maps_service import MapsService
from app.core.state import RouteInfo


class MapsAgent(BaseAgent):
    def __init__(self, redis_client: RedisClient, groq_api_key: str = None, model_name: str = "llama-3.3-70b-versatile"):
        super().__init__(
            name="Trailblazer", role="Route Planner & Navigator",
            expertise="Route optimization, transportation analysis, and travel logistics",
            agent_type=AgentType.MAPS, redis_client=redis_client,
            tools=MAPS_TOOLS, groq_api_key=groq_api_key, model_name=model_name
        )
        self.maps_service = MapsService()

    def get_system_prompt(self) -> str:
        return f"""You are {self.name}, a {self.role}.
Expertise: {self.expertise}

Provide concise, practical route advice. Include:
- Recommended transport mode and why
- Distance and duration
- Key travel tips for this route
Keep it to 2-3 sentences.
"""

    @staticmethod
    def _normalize_route(route: Any) -> Dict[str, Any]:
        """
        Normalize a route object to always have string distance/duration fields.
        Handles: RouteInfo pydantic, plain dict, or dict with nested summary.
        """
        if route is None:
            return {}

        # Pydantic model -> dict
        if hasattr(route, "dict"):
            route = route.dict()
        if not isinstance(route, dict):
            return {}

        result = dict(route)

        # If distance/duration are missing but summary exists (ORS raw response)
        if (not result.get("distance") or result.get("distance") == "Unknown") and result.get("summary"):
            summary = result["summary"]
            dist_m = summary.get("distance", 0)
            dur_s  = summary.get("duration", 0)
            if dist_m:
                result["distance"] = f"{dist_m/1000:.1f} km" if dist_m >= 1000 else f"{int(dist_m)} m"
            if dur_s:
                h, m = int(dur_s // 3600), int((dur_s % 3600) // 60)
                result["duration"] = f"{h}h {m}m" if h > 0 else f"{m}m"

        # Remove "unavailable" placeholders so frontend shows nothing rather than bad text
        if result.get("distance") in ("Distance unavailable", "Unknown", None, ""):
            result["distance"] = None
        if result.get("duration") in ("Duration unavailable", "Unknown", None, ""):
            result["duration"] = None

        return result

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        payload = request.get("payload", {})
        session_id = request.get("session_id")

        origin = payload.get("origin")
        destination = payload.get("destination")
        transport_mode = payload.get("transport_mode", "driving")
        include_alternatives = payload.get("include_alternatives", True)
        include_travel_options = payload.get("include_travel_options", False)

        if not origin:
            raise ValueError("Missing required field: origin")
        if not destination:
            raise ValueError("Missing required field: destination")

        self.log_action("Fetching route", f"{origin} → {destination}")

        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message=f"Calculating route from {origin} to {destination}", progress_percent=20
        )

        # ── Primary route via tool ────────────────────────────────────────────
        primary_route_raw = await get_route.ainvoke({
            "origin": origin, "destination": destination, "transport_mode": transport_mode
        })

        if "error" in primary_route_raw:
            self.logger.warning(f"Tool route failed, trying service directly: {primary_route_raw['error']}")
            try:
                route_obj = await self.maps_service.get_route_between_locations(origin, destination, transport_mode)
                primary_route_raw = route_obj.dict() if route_obj else {}
            except Exception as e:
                self.logger.error(f"Service route also failed: {e}")
                primary_route_raw = {}

        primary_route = self._normalize_route(primary_route_raw)
        if not primary_route.get("transport_mode"):
            primary_route["transport_mode"] = transport_mode

        result = {
            "primary_route": primary_route,
            "origin": origin,
            "destination": destination,
            "requested_mode": transport_mode,
        }

        # ── Alternative routes ────────────────────────────────────────────────
        alternative_routes = {}
        if include_alternatives:
            await self._send_streaming_update(
                session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
                message="Analysing alternative transport options", progress_percent=40,
                data={"primary_route_complete": True}
            )

            alts_result = await get_multiple_routes.ainvoke({"origin": origin, "destination": destination})

            if "error" not in alts_result:
                for mode, route in alts_result.get("routes", {}).items():
                    if mode != transport_mode and "error" not in (route or {}):
                        alternative_routes[mode] = self._normalize_route(route)

            result["alternative_routes"] = alternative_routes

        # ── Optional travel options (flights/trains/hotels) ───────────────────
        if include_travel_options:
            await self._send_streaming_update(
                session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
                message="Fetching travel options (flights, trains, hotels)", progress_percent=60
            )
            travel_date = payload.get("travel_date")
            if travel_date:
                travel_options_result = await get_comprehensive_travel_options.ainvoke({
                    "origin": origin, "destination": destination, "date": travel_date,
                    "checkin": payload.get("checkin_date"), "checkout": payload.get("checkout_date")
                })
                result["travel_options"] = travel_options_result

        # ── LLM route analysis ────────────────────────────────────────────────
        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message="Generating route recommendations", progress_percent=80
        )

        route_analysis = await self._generate_route_analysis(
            primary_route=primary_route, alternative_routes=alternative_routes,
            origin=origin, destination=destination, session_id=session_id
        )

        result["route_analysis"] = route_analysis
        result["recommended_mode"] = primary_route.get("transport_mode", transport_mode)
        result["comparison"] = self._create_route_comparison(primary_route, alternative_routes)

        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message="Route report ready", progress_percent=90
        )

        self.log_action("Route analysis complete", f"Primary: {transport_mode}, Alts: {len(alternative_routes)}")
        return result

    async def _generate_route_analysis(
        self, primary_route: Dict, alternative_routes: Dict, origin: str, destination: str, session_id: str
    ) -> str:
        mode = primary_route.get("transport_mode", "driving")
        dist = primary_route.get("distance") or "unknown distance"
        dur  = primary_route.get("duration") or "unknown duration"

        alt_lines = []
        for m, r in alternative_routes.items():
            if r.get("distance") or r.get("duration"):
                alt_lines.append(f"  {m}: {r.get('distance','?')} in {r.get('duration','?')}")

        user_input = f"""
Route: {origin} → {destination}
Primary ({mode}): {dist}, {dur}
{"Alternatives:" + chr(10) + chr(10).join(alt_lines) if alt_lines else ""}

Give a 2-3 sentence practical recommendation for this journey.
"""
        try:
            return await self.invoke_llm(
                system_prompt=self.get_system_prompt(), user_input=user_input,
                session_id=session_id, stream_progress=False
            )
        except Exception as e:
            self.log_error("LLM route analysis failed", str(e))
            return f"Travel from {origin} to {destination} by {mode}: {dist}, approximately {dur}."

    def _create_route_comparison(self, primary: Dict, alternatives: Dict) -> Dict:
        comparison = {}
        if primary and (primary.get("distance") or primary.get("duration")):
            mode = primary.get("transport_mode", "driving")
            comparison[mode] = {"distance": primary.get("distance"), "duration": primary.get("duration"), "mode": mode}
        for mode, route in alternatives.items():
            if route and (route.get("distance") or route.get("duration")):
                comparison[mode] = {"distance": route.get("distance"), "duration": route.get("duration"), "mode": mode}
        return comparison


async def run_maps_agent_standalone():
    from app.messaging.redis_client import get_redis_client, RedisChannels
    from app.config.settings import settings
    import asyncio
    redis_client = get_redis_client()
    await redis_client.connect()
    agent = MapsAgent(redis_client=redis_client, groq_api_key=settings.groq_api_key, model_name=settings.model_name)
    await agent.start()
    print(f"✅ Maps Agent running — listening on {RedisChannels.get_request_channel('maps')}")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await agent.stop()
        await redis_client.disconnect()

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_maps_agent_standalone())