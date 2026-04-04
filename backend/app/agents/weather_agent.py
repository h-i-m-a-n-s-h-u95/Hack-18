from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from app.agents.base_agent import BaseAgent, AgentType, StreamingUpdateType
from app.tools.weather_tools import WEATHER_TOOLS, get_weather_for_specific_dates
from app.messaging.redis_client import RedisClient
from app.services.weather_service import WeatherService


class WeatherAgent(BaseAgent):
    """
    Weather Agent - Fetches and analyzes weather data for travel destinations
    
    Uses LangChain tools and Google Gemini for intelligent weather analysis
    """
    
    def __init__(
        self,
        redis_client: RedisClient,
        gemini_api_key: str = None,
        model_name: str = "gemini-2.0-flash-exp"
    ):
        super().__init__(
            name="Sky Gazer",
            role="Weather Forecaster",
            expertise="Weather analysis, climate patterns, and travel weather recommendations",
            agent_type=AgentType.WEATHER,
            redis_client=redis_client,
            tools=WEATHER_TOOLS,
            gemini_api_key=gemini_api_key,
            model_name=model_name
        )
        
        self.weather_service = WeatherService()
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for the weather agent"""
        return f"""
You are {self.name}, a {self.role}. Your role is to:

1. Analyze weather data for travel destinations
2. Provide weather-based travel recommendations
3. Suggest appropriate clothing and gear based on conditions
4. Warn about potential weather-related travel issues
5. Recommend optimal times for outdoor activities
6. Advise travelers about air quality and pollution levels

Expertise: {self.expertise}

You have access to weather tools that can:
- Get location coordinates
- Fetch current weather
- Get 5-day forecasts (OpenWeather)
- Get 16-day extended forecasts (Open-Meteo)
- Get air quality data
- Get weather for specific dates

Always provide practical, actionable weather advice that helps travelers prepare.
Be concise but informative. Focus on how weather will impact the travel experience.

When analyzing weather data, include:
- General weather overview for the trip
- Temperature range and conditions
- Any weather concerns or highlights (rain, extreme temps, etc.)
- Clothing and packing recommendations
- Activity suggestions based on weather
- Air quality information if available
"""
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle weather request
        
        Expected request payload:
        {
            "destination": "Paris, France",
            "travel_dates": ["2025-10-15", "2025-10-16", "2025-10-17"],
            "session_id": "session_123",
            "request_id": "req_456"
        }
        
        Returns:
        {
            "weather_forecast": [...],
            "weather_summary": "...",
            "temperature_range": {"min": 15, "max": 25},
            "conditions_summary": "...",
            "recommendations": {...}
        }
        """
        payload = request.get("payload", {})
        session_id = request.get("session_id")
        
        destination = payload.get("destination")
        travel_dates = payload.get("travel_dates", [])
        
        # Validate required fields
        if not destination:
            raise ValueError("Missing required field: destination")
        if not travel_dates:
            raise ValueError("Missing required field: travel_dates")
        
        self.log_action("Fetching weather", f"{destination}, {len(travel_dates)} days")
        
        # Progress update: Fetching data
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message=f"Fetching weather forecast for {destination}",
            progress_percent=30
        )
        
        # Fetch weather data using the tool
        weather_result = await get_weather_for_specific_dates.ainvoke({
            "location": destination,
            "dates": travel_dates
        })
        
        if "error" in weather_result:
            raise Exception(f"Weather data fetch failed: {weather_result['error']}")
        
        weather_data = weather_result.get("weather_data", [])
        
        if not weather_data:
            raise Exception(f"No weather data available for {destination}")
        
        # Progress update: Analyzing
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Analyzing weather patterns and generating recommendations",
            progress_percent=60,
            data={"forecast_retrieved": len(weather_data)}
        )
        
        # Generate intelligent weather analysis using LLM
        weather_summary = await self._generate_weather_analysis(
            weather_data=weather_data,
            destination=destination,
            travel_dates=travel_dates,
            session_id=session_id
        )
        
        # Calculate statistics
        temps = [w for w in weather_data if "temp_max" in w and "temp_min" in w]
        
        if temps:
            avg_temp_min = sum(w["temp_min"] for w in temps) / len(temps)
            avg_temp_max = sum(w["temp_max"] for w in temps) / len(temps)
        else:
            avg_temp_min, avg_temp_max = 20.0, 25.0
        
        # Extract conditions summary
        conditions = [w.get("description", "N/A") for w in weather_data if "description" in w]
        conditions_summary = ", ".join(set(conditions)) if conditions else "Variable conditions"
        
        # Progress update: Finalizing
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Finalizing weather report",
            progress_percent=90
        )
        
        self.log_action("Weather analysis complete", f"{len(weather_data)} days processed")
        
        return {
            "weather_forecast": weather_data,
            "weather_summary": weather_summary,
            "destination": destination,
            "forecast_count": len(weather_data),
            "temperature_range": {
                "min": round(avg_temp_min, 1),
                "max": round(avg_temp_max, 1),
                "unit": "°C"
            },
            "conditions_summary": conditions_summary,
            "date_range": {
                "start": travel_dates[0] if travel_dates else None,
                "end": travel_dates[-1] if travel_dates else None
            },
            "has_air_quality": any("air_quality" in w for w in weather_data)
        }
    
    async def _generate_weather_analysis(
        self,
        weather_data: List[Dict[str, Any]],
        destination: str,
        travel_dates: List[str],
        session_id: str
    ) -> str:
        """Generate intelligent weather analysis using LLM"""
        
        # Format weather data for LLM
        weather_text = self._format_weather_for_llm(weather_data)
        
        user_input = f"""
Destination: {destination}
Travel Dates: {', '.join(travel_dates)}
Number of Days: {len(travel_dates)}

Weather Forecast Data:
{weather_text}

Please provide a comprehensive weather analysis including:
1. Overall weather summary for the trip
2. Temperature expectations and trends
3. Precipitation and weather concerns
4. Clothing and packing recommendations
5. Best times for outdoor activities
6. Any weather-related travel advisories
7. Air quality insights (if available)

Keep the analysis practical and actionable for travelers.
"""
        
        try:
            analysis = await self.invoke_llm(
                system_prompt=self.get_system_prompt(),
                user_input=user_input,
                session_id=session_id,
                stream_progress=False  # Already sent progress updates
            )
            return analysis
        except Exception as e:
            self.log_error("Failed to generate weather analysis", str(e))
            return self._get_fallback_summary(weather_data)
    
    def _format_weather_for_llm(self, weather_data: List[Dict[str, Any]]) -> str:
        """Format weather data for LLM consumption"""
        formatted_lines = []
        
        for w in weather_data:
            date = w.get("date", "Unknown")
            temp_max = w.get("temp_max", "N/A")
            temp_min = w.get("temp_min", "N/A")
            desc = w.get("description", "N/A")
            precip = w.get("precipitation", "N/A")
            precip_prob = w.get("precipitation_probability", "N/A")
            
            line = f"• {date}: {temp_min}°C - {temp_max}°C, {desc}"
            
            if precip != "N/A":
                line += f", Precipitation: {precip}mm"
            if precip_prob != "N/A":
                line += f" ({precip_prob}% chance)"
            
            # Add air quality if available
            air_quality = w.get("air_quality")
            if air_quality:
                aqi = air_quality.get("aqi", "N/A")
                line += f", AQI: {aqi}"
            
            formatted_lines.append(line)
        
        return "\n".join(formatted_lines)
    
    def _get_fallback_summary(self, weather_data: List[Dict[str, Any]]) -> str:
        """Generate a basic fallback summary if LLM fails"""
        if not weather_data:
            return "No weather data available."
        
        temps = [w for w in weather_data if "temp_max" in w and "temp_min" in w]
        if temps:
            avg_max = sum(w["temp_max"] for w in temps) / len(temps)
            avg_min = sum(w["temp_min"] for w in temps) / len(temps)
            return (
                f"Weather forecast retrieved for {len(weather_data)} days. "
                f"Average temperatures: {avg_min:.1f}°C - {avg_max:.1f}°C. "
                f"Please check detailed forecast for daily conditions."
            )
        
        return f"Weather forecast retrieved for {len(weather_data)} days."


# ==================== STANDALONE RUNNER ====================

async def run_weather_agent_standalone():
    """Run the weather agent as a standalone service"""
    from app.messaging.redis_client import get_redis_client
    from app.config.settings import settings
    
    # Get Redis client
    redis_client = get_redis_client()
    await redis_client.connect()
    
    # Create weather agent
    weather_agent = WeatherAgent(
        redis_client=redis_client,
        gemini_api_key=settings.google_api_key,
        model_name=settings.model_name
    )
    
    # Start the agent
    await weather_agent.start()
    
    print(f"✅ Weather Agent is running!")
    print(f"   Agent: {weather_agent.name}")
    print(f"   Type: {weather_agent.agent_type.value}")
    print(f"   Listening on: {RedisChannels.get_request_channel('weather')}")
    print(f"\nPress Ctrl+C to stop...")
    
    try:
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down Weather Agent...")
        await weather_agent.stop()
        await redis_client.disconnect()
        print("✅ Weather Agent stopped")


if __name__ == "__main__":
    import asyncio
    from app.messaging.redis_client import RedisChannels
    
    asyncio.run(run_weather_agent_standalone())