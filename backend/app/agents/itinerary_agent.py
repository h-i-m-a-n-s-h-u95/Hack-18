"""
Itinerary Agent — calls Groq directly for a fully personalized itinerary.
Resolves the API key from multiple possible attribute names set by BaseAgent.
"""

from typing import Dict, Any, List, Optional
import logging
import os

from app.agents.base_agent import BaseAgent, AgentType, StreamingUpdateType
from app.tools.itinerary_tools import (
    ITINERARY_TOOLS,
    expand_travel_dates,
    generate_llm_itinerary,
)
from app.messaging.redis_client import RedisClient
from app.services.itinerary_service import ItineraryService

logger = logging.getLogger(__name__)


class ItineraryAgent(BaseAgent):
    """Itinerary Agent — LLM-driven, personalized day planning."""

    def __init__(
        self,
        redis_client: RedisClient,
        groq_api_key: str = None,
        model_name: str = "llama-3.3-70b-versatile"
    ):
        super().__init__(
            name="Chronomancer",
            role="Day Planner & Activity Coordinator",
            expertise="Itinerary creation, activity scheduling, and travel timeline optimization",
            agent_type=AgentType.ITINERARY,
            redis_client=redis_client,
            tools=ITINERARY_TOOLS,
            groq_api_key=groq_api_key,
            model_name=model_name
        )
        self.itinerary_service = ItineraryService()

        # Store key explicitly — BaseAgent may use a different attribute name
        self._groq_api_key = groq_api_key

        logger.info(
            f"[ItineraryAgent] Init complete. "
            f"Key present: {bool(groq_api_key)}, "
            f"prefix: {groq_api_key[:8] if groq_api_key else 'NONE'}"
        )

    def _get_api_key(self) -> str:
        """
        Resolve Groq API key from multiple possible sources in priority order:
        1. self._groq_api_key (set in __init__ above)
        2. self.groq_api_key (if BaseAgent stores it)
        3. self.api_key (another common name)
        4. self.llm.groq_api_key (if BaseAgent wraps an LLM client)
        5. GROQ_API_KEY environment variable
        """
        # Try every common attribute name BaseAgent might use
        for attr in ("_groq_api_key", "groq_api_key", "api_key", "_api_key"):
            val = getattr(self, attr, None)
            if val and isinstance(val, str) and val.strip():
                logger.info(f"[ItineraryAgent] API key found via self.{attr}, prefix: {val[:8]}")
                return val

        # Try nested LLM client
        llm = getattr(self, "llm", None) or getattr(self, "_llm", None)
        if llm:
            for attr in ("groq_api_key", "api_key", "_api_key"):
                val = getattr(llm, attr, None)
                if val and isinstance(val, str) and val.strip():
                    logger.info(f"[ItineraryAgent] API key found via self.llm.{attr}")
                    return val

        # Fall back to environment
        env_key = os.environ.get("GROQ_API_KEY", "")
        if env_key:
            logger.info("[ItineraryAgent] API key found via GROQ_API_KEY env var")
            return env_key

        logger.error("[ItineraryAgent] No API key found in any location!")
        return ""

    def get_system_prompt(self) -> str:
        return f"""You are {self.name}, a {self.role}.
Expertise: {self.expertise}
Create detailed, personalized travel itineraries with local recommendations.
"""

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        payload = request.get("payload", {})
        session_id = request.get("session_id")

        destination = payload.get("destination")
        origin = payload.get("origin", "")
        travel_dates_raw = payload.get("travel_dates", [])
        travelers_count = payload.get("travelers_count", 1)
        budget_range = payload.get("budget_range", "moderate")
        user_preferences = payload.get("user_preferences")

        if not destination:
            raise ValueError("Missing required field: destination")
        if not travel_dates_raw:
            raise ValueError("Missing required field: travel_dates")

        travel_dates = expand_travel_dates(travel_dates_raw)
        total_days = len(travel_dates)

        logger.info(
            f"[ItineraryAgent] {destination}, "
            f"raw={travel_dates_raw} → expanded={travel_dates} ({total_days} days)"
        )

        self.log_action("Creating itinerary", f"{destination}, {total_days} days")

        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message=f"Planning your {total_days}-day trip to {destination}",
            progress_percent=20
        )

        # ── Extract weather ───────────────────────────────────────────────────
        weather_forecast_list = []
        wd = payload.get("weather_data")
        if wd:
            if isinstance(wd, list):
                weather_forecast_list = wd
            elif isinstance(wd, dict):
                weather_forecast_list = (
                    wd.get("weather_forecast") or
                    wd.get("forecast") or
                    []
                )

        # ── Extract events ────────────────────────────────────────────────────
        events_list = []
        ed = payload.get("events_data")
        if ed:
            if isinstance(ed, list):
                events_list = ed
            elif isinstance(ed, dict):
                events_list = ed.get("events") or []

        # ── Extract maps ──────────────────────────────────────────────────────
        maps_data = payload.get("maps_data") or payload.get("route_data")

        # ── Extract budget ────────────────────────────────────────────────────
        budget_data = payload.get("budget_data")
        budget_total = None
        if isinstance(budget_data, dict):
            budget_total = (
                budget_data.get("total") or
                budget_data.get("budget_breakdown", {}).get("total")
            )

        # ── User preferences ──────────────────────────────────────────────────
        prefs_str = None
        if user_preferences:
            if isinstance(user_preferences, dict):
                interests = user_preferences.get("interests", [])
                pace = user_preferences.get("pace", "moderate")
                prefs_str = f"Interests: {', '.join(interests)}. Pace: {pace}."
            elif isinstance(user_preferences, str):
                prefs_str = user_preferences

        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message="Generating personalized itinerary with local recommendations",
            progress_percent=50
        )

        # ── Resolve API key ───────────────────────────────────────────────────
        api_key = self._get_api_key()

        # ── Call Groq ─────────────────────────────────────────────────────────
        itinerary_days_raw, route_plan = await generate_llm_itinerary(
            destination=destination,
            origin=origin,
            travel_dates=travel_dates,
            travelers_count=travelers_count,
            budget_total=budget_total,
            budget_range=budget_range,
            user_preferences=prefs_str,
            weather_data=weather_forecast_list,
            events_data=events_list,
            maps_data=maps_data,
            budget_data=budget_data,
            groq_api_key=api_key,
        )

        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message="Finalizing your itinerary", progress_percent=85
        )

        # ── Normalize output ──────────────────────────────────────────────────
        itinerary_days_list = []
        for day_data in itinerary_days_raw:
            activities = []
            for act in day_data.get("activities", []):
                if isinstance(act, dict):
                    parts = [p for p in [
                        act.get("time", ""),
                        act.get("activity", act.get("name", "")),
                        act.get("duration", "")
                    ] if p]
                    s = " - ".join(parts)
                    if act.get("tips"):
                        s += f" ({act['tips']})"
                    activities.append(s)
                else:
                    activities.append(str(act))

            itinerary_days_list.append({
                "day": day_data.get("day", len(itinerary_days_list) + 1),
                "date": day_data.get(
                    "date",
                    travel_dates[len(itinerary_days_list)]
                    if len(itinerary_days_list) < total_days else ""
                ),
                "activities": activities,
                "notes": day_data.get("notes", ""),
                "estimated_cost": day_data.get("estimated_cost", 2000),
            })

        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message="Itinerary ready", progress_percent=100
        )

        self.log_action("Itinerary created", f"{len(itinerary_days_list)} days for {destination}")

        return {
            "itinerary_days": itinerary_days_list,
            "itinerary_narrative": (
                f"Your personalized {total_days}-day itinerary for {destination} "
                f"is ready. Tailored to your {budget_range or 'moderate'} budget and preferences."
            ),
            "route_optimization": {
                "applied": route_plan.get("available", False),
                "day_routes": route_plan.get("day_routes", []),
                "km_saved": route_plan.get("stats", {}).get("km_saved", 0)
            },
            "structured_data": {},
            "transport_details": {},
            "key_tips": [],
            "destination": destination,
            "total_days": total_days,
            "travelers_count": travelers_count,
        }