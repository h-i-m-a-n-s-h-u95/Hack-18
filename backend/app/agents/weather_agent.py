from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from app.agents.base_agent import BaseAgent, AgentType, StreamingUpdateType
from app.tools.weather_tools import WEATHER_TOOLS, get_weather_for_specific_dates
from app.messaging.redis_client import RedisClient
from app.services.weather_service import WeatherService


class WeatherAgent(BaseAgent):
    def __init__(self, redis_client: RedisClient, groq_api_key: str = None, model_name: str = "llama-3.3-70b-versatile"):
        super().__init__(
            name="Sky Gazer", role="Weather Forecaster",
            expertise="Weather analysis, climate patterns, and travel weather recommendations",
            agent_type=AgentType.WEATHER, redis_client=redis_client,
            tools=WEATHER_TOOLS, groq_api_key=groq_api_key, model_name=model_name
        )
        self.weather_service = WeatherService()

    def get_system_prompt(self) -> str:
        return f"""You are {self.name}, a {self.role}.
Expertise: {self.expertise}

Provide practical weather analysis for travelers. Focus on:
- Temperature expectations and daily ranges
- Rain/precipitation likelihood  
- Clothing recommendations
- Best times for outdoor activities
- Any weather advisories

Be concise and actionable.
"""

    @staticmethod
    def _normalize_weather_item(w: Any) -> Dict[str, Any]:
        """
        Normalize a weather item to always use temperature_max/temperature_min keys.
        The tool returns temp_max/temp_min but WeatherInfo and the frontend expect
        temperature_max/temperature_min.
        """
        if hasattr(w, "dict"):
            w = w.dict()
        if not isinstance(w, dict):
            return w

        normalized = dict(w)

        # Remap temp_max -> temperature_max if needed
        if "temperature_max" not in normalized or normalized["temperature_max"] is None:
            if "temp_max" in normalized and normalized["temp_max"] is not None:
                normalized["temperature_max"] = normalized["temp_max"]

        # Remap temp_min -> temperature_min if needed
        if "temperature_min" not in normalized or normalized["temperature_min"] is None:
            if "temp_min" in normalized and normalized["temp_min"] is not None:
                normalized["temperature_min"] = normalized["temp_min"]

        # Remap precipitation_probability -> precipitation_chance if needed
        if "precipitation_chance" not in normalized or normalized.get("precipitation_chance") is None:
            for alt in ("precipitation_probability", "precipitation_probability_max", "pop"):
                if normalized.get(alt) is not None:
                    val = normalized[alt]
                    # pop from OW is 0-1, convert to percent
                    normalized["precipitation_chance"] = int(val * 100) if val <= 1.0 else int(val)
                    break

        # Ensure description is never the error message
        desc = normalized.get("description", "")
        if not desc or "forecast not available" in str(desc).lower() or "n/a" in str(desc).lower():
            # Try to derive from temp
            tmax = normalized.get("temperature_max") or normalized.get("temp_max")
            rain = normalized.get("precipitation_chance", 0)
            month = None
            try:
                month = int(str(normalized.get("date", "")).split("-")[1])
            except Exception:
                pass
            if rain and rain > 60:
                normalized["description"] = "Rainy"
            elif month and month in (6, 7, 8, 9):
                normalized["description"] = "Monsoon season"
            elif tmax and tmax > 38:
                normalized["description"] = "Hot and sunny"
            elif tmax and tmax < 15:
                normalized["description"] = "Cool and pleasant"
            else:
                normalized["description"] = "Partly cloudy"

        return normalized

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        payload = request.get("payload", {})
        session_id = request.get("session_id")

        destination = payload.get("destination")
        travel_dates = payload.get("travel_dates", [])

        if not destination:
            raise ValueError("Missing required field: destination")
        if not travel_dates:
            raise ValueError("Missing required field: travel_dates")

        self.log_action("Fetching weather", f"{destination}, {len(travel_dates)} days")

        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message=f"Fetching weather forecast for {destination}", progress_percent=30
        )

        # Try tool first
        weather_result = await get_weather_for_specific_dates.ainvoke({
            "location": destination, "dates": travel_dates
        })

        if "error" in weather_result:
            # Fall back to service directly
            self.log_error("Tool failed, calling service directly", weather_result["error"])
            try:
                weather_objects = await self.weather_service.get_weather_for_dates(destination, travel_dates)
                weather_data = [self._normalize_weather_item(w) for w in weather_objects]
            except Exception as e:
                raise Exception(f"Weather data fetch failed: {e}")
        else:
            raw_data = weather_result.get("weather_data", [])
            weather_data = [self._normalize_weather_item(w) for w in raw_data]

        if not weather_data:
            raise Exception(f"No weather data available for {destination}")

        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message="Analysing weather patterns", progress_percent=60,
            data={"forecast_retrieved": len(weather_data)}
        )

        weather_summary = await self._generate_weather_analysis(
            weather_data=weather_data, destination=destination,
            travel_dates=travel_dates, session_id=session_id
        )

        # Stats using normalized keys
        tmaxes = [w["temperature_max"] for w in weather_data if w.get("temperature_max") is not None]
        tmins  = [w["temperature_min"] for w in weather_data if w.get("temperature_min") is not None]
        avg_temp_max = round(sum(tmaxes) / len(tmaxes), 1) if tmaxes else 30.0
        avg_temp_min = round(sum(tmins)  / len(tmins),  1) if tmins  else 20.0

        conditions = list({w.get("description", "") for w in weather_data if w.get("description")})
        conditions_summary = ", ".join(conditions) if conditions else "Variable conditions"

        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message="Finalizing weather report", progress_percent=90
        )

        self.log_action("Weather analysis complete", f"{len(weather_data)} days processed")

        return {
            "weather_forecast": weather_data,   # normalized — temperature_max/min keys
            "weather_summary": weather_summary,
            "destination": destination,
            "forecast_count": len(weather_data),
            "temperature_range": {"min": avg_temp_min, "max": avg_temp_max, "unit": "°C"},
            "conditions_summary": conditions_summary,
            "date_range": {
                "start": travel_dates[0] if travel_dates else None,
                "end": travel_dates[-1] if travel_dates else None,
            },
            "has_air_quality": any("air_quality" in w or "air_pollution" in w for w in weather_data),
        }

    async def _generate_weather_analysis(
        self, weather_data: List[Dict[str, Any]], destination: str,
        travel_dates: List[str], session_id: str
    ) -> str:
        lines = []
        for w in weather_data:
            tmax = w.get("temperature_max") or w.get("temp_max", "?")
            tmin = w.get("temperature_min") or w.get("temp_min", "?")
            desc = w.get("description", "N/A")
            rain = w.get("precipitation_chance", w.get("precipitation_probability", ""))
            line = f"• {w.get('date','?')}: {tmin}–{tmax}°C, {desc}"
            if rain != "":
                line += f", {rain}% rain chance"
            lines.append(line)

        user_input = f"""
Destination: {destination}
Travel Dates: {', '.join(travel_dates)}

Weather Forecast:
{chr(10).join(lines)}

Provide a brief practical weather summary (3-4 sentences):
- Overall conditions for the trip
- Any rain/heat concerns
- Key packing recommendation
"""
        try:
            return await self.invoke_llm(
                system_prompt=self.get_system_prompt(), user_input=user_input,
                session_id=session_id, stream_progress=False
            )
        except Exception as e:
            self.log_error("LLM weather analysis failed", str(e))
            return self._get_fallback_summary(weather_data)

    def _get_fallback_summary(self, weather_data: List[Dict[str, Any]]) -> str:
        if not weather_data:
            return "No weather data available."
        tmaxes = [w.get("temperature_max") or w.get("temp_max") for w in weather_data if w.get("temperature_max") or w.get("temp_max")]
        tmins  = [w.get("temperature_min") or w.get("temp_min") for w in weather_data if w.get("temperature_min") or w.get("temp_min")]
        if tmaxes and tmins:
            return (f"Weather forecast for {len(weather_data)} days: "
                    f"{min(tmins):.0f}–{max(tmaxes):.0f}°C. "
                    f"Pack accordingly and check daily forecasts for updates.")
        return f"Weather forecast retrieved for {len(weather_data)} days."


async def run_weather_agent_standalone():
    from app.messaging.redis_client import get_redis_client, RedisChannels
    from app.config.settings import settings
    import asyncio
    redis_client = get_redis_client()
    await redis_client.connect()
    agent = WeatherAgent(redis_client=redis_client, groq_api_key=settings.groq_api_key, model_name=settings.model_name)
    await agent.start()
    print(f"✅ Weather Agent running — listening on {RedisChannels.get_request_channel('weather')}")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await agent.stop()
        await redis_client.disconnect()

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_weather_agent_standalone())