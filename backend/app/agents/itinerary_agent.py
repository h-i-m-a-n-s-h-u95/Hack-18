"""
Itinerary Agent — calls Groq directly for a fully personalized itinerary.
No hardcoded city data. No fragile JSON extraction from narrative text.
"""

from typing import Dict, Any, List, Optional
import logging
import json
import re
from datetime import datetime

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

    def get_system_prompt(self) -> str:
        return f"""You are {self.name}, a {self.role}.
Expertise: {self.expertise}

Your job is to create detailed, personalized travel itineraries.
You have access to weather, events, maps, and budget data from other agents.
Always create realistic, relaxed schedules with specific local recommendations.
"""

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle itinerary request.

        Payload fields used:
          destination, origin, travel_dates, travelers_count, budget_range,
          weather_data, events_data, maps_data, budget_data, user_preferences
        """
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

        # Always expand dates first
        travel_dates = expand_travel_dates(travel_dates_raw)
        total_days = len(travel_dates)

        logger.info(
            f"ItineraryAgent: {destination}, raw_dates={travel_dates_raw}, "
            f"expanded={travel_dates} ({total_days} days)"
        )

        self.log_action("Creating itinerary", f"{destination}, {total_days} days")

        # ── Progress: starting ────────────────────────────────────────────────
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message=f"Planning your {total_days}-day trip to {destination}",
            progress_percent=20
        )

        # ── Extract supporting data from other agents ─────────────────────────

        # Weather: stored as flat list in state["weather_data"]
        weather_forecast_list = []
        if payload.get("weather_data"):
            wd = payload["weather_data"]
            if isinstance(wd, list):
                weather_forecast_list = wd
            elif isinstance(wd, dict):
                weather_forecast_list = wd.get("weather_forecast", [])

        # Events
        events_list = []
        if payload.get("events_data"):
            ed = payload["events_data"]
            if isinstance(ed, list):
                events_list = ed
            elif isinstance(ed, dict):
                events_list = ed.get("events", [])

        # Maps
        maps_data = payload.get("maps_data") or payload.get("route_data")

        # Budget breakdown
        budget_data = payload.get("budget_data")
        budget_total = None
        if isinstance(budget_data, dict):
            budget_total = budget_data.get("total")

        # User preferences string
        prefs_str = None
        if user_preferences:
            if isinstance(user_preferences, dict):
                interests = user_preferences.get("interests", [])
                pace = user_preferences.get("pace", "moderate")
                prefs_str = f"Interests: {', '.join(interests)}. Pace: {pace}."
            elif isinstance(user_preferences, str):
                prefs_str = user_preferences

        # ── Progress: calling LLM ─────────────────────────────────────────────
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Generating personalized itinerary with local recommendations",
            progress_percent=50
        )

        # ── Core: call Groq directly ──────────────────────────────────────────
        itinerary_days_raw = await generate_llm_itinerary(
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
        )

        # ── Progress: formatting ──────────────────────────────────────────────
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Finalizing your itinerary",
            progress_percent=85
        )

        # ── Normalize output to expected shape ────────────────────────────────
        itinerary_days_list = []
        for day_data in itinerary_days_raw:
            # activities may be list of strings or list of dicts
            activities = []
            raw_activities = day_data.get("activities", [])
            for act in raw_activities:
                if isinstance(act, dict):
                    time = act.get("time", "")
                    name = act.get("activity", act.get("name", ""))
                    duration = act.get("duration", "")
                    tips = act.get("tips", "")
                    parts = [p for p in [time, name, duration] if p]
                    activity_str = " - ".join(parts)
                    if tips:
                        activity_str += f" ({tips})"
                    activities.append(activity_str)
                else:
                    activities.append(str(act))

            itinerary_days_list.append({
                "day": day_data.get("day", len(itinerary_days_list) + 1),
                "date": day_data.get("date", travel_dates[len(itinerary_days_list)] if len(itinerary_days_list) < total_days else ""),
                "activities": activities,
                "notes": day_data.get("notes", ""),
                "estimated_cost": day_data.get("estimated_cost", 2000),
            })

        # ── Progress: done ────────────────────────────────────────────────────
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Itinerary ready",
            progress_percent=100
        )

        self.log_action("Itinerary created", f"{len(itinerary_days_list)} days planned")

        # Build a brief narrative summary
        narrative = (
            f"Here is your personalized {total_days}-day itinerary for {destination}. "
            f"The plan is tailored to your preferences, local events, weather conditions, "
            f"and your {budget_range or 'moderate'} budget. Enjoy your trip!"
        )

        return {
            "itinerary_days": itinerary_days_list,
            "itinerary_narrative": narrative,
            "structured_data": {},
            "transport_details": {},
            "key_tips": [],
            "destination": destination,
            "total_days": total_days,
            "travelers_count": travelers_count,
        }