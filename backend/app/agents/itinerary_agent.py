"""
Itinerary Agent Implementation with LangChain Tools and Redis Pub/Sub

Follows the same structure as other agents:
- Extends BaseAgent
- Uses LangChain tools for itinerary planning
- Supports MCP protocol via Redis pub/sub
- Streaming updates
- Synthesizes data from all other agents
"""

from typing import Dict, Any, List, Optional
import logging
import json
import re
from datetime import datetime

from app.agents.base_agent import BaseAgent, AgentType, StreamingUpdateType
from app.tools.itinerary_tools import ITINERARY_TOOLS, create_daily_itinerary, get_destination_info, optimize_itinerary_by_weather
from app.messaging.redis_client import RedisClient
from app.services.itinerary_service import ItineraryService


class ItineraryAgent(BaseAgent):
    """
    Itinerary Agent - Day planning and activity coordination
    
    Uses LangChain tools and Google Gemini to synthesize all travel data into a coherent itinerary
    """
    
    def __init__(
        self,
        redis_client: RedisClient,
        gemini_api_key: str = None,
        model_name: str = "gemini-2.0-flash-exp"
    ):
        super().__init__(
            name="Chronomancer",
            role="Day Planner & Activity Coordinator",
            expertise="Itinerary creation, activity scheduling, and travel timeline optimization",
            agent_type=AgentType.ITINERARY,
            redis_client=redis_client,
            tools=ITINERARY_TOOLS,
            gemini_api_key=gemini_api_key,
            model_name=model_name
        )
        
        self.itinerary_service = ItineraryService()
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for the itinerary agent"""
        return f"""
You are {self.name}, a {self.role}. Your role is to:

1. Create detailed daily itineraries with optimal activity scheduling
2. Balance must-see attractions with local experiences
3. Consider weather conditions for activity planning
4. Optimize travel time and minimize backtracking
5. Include practical tips for each day
6. Suggest realistic timeframes for activities
7. Synthesize data from weather, events, maps, and budget agents

Expertise: {self.expertise}

You have access to itinerary tools that can:
- Get destination information (attractions, food, tips)
- Create daily itineraries
- Plan single day activities
- Get food recommendations
- Get travel tips
- Optimize itineraries by weather
- Estimate time per attraction

Always provide practical, realistic schedules that travelers can actually follow.
Consider factors like:
- Travel time between attractions
- Opening hours and peak times
- Meal times and rest periods
- Weather conditions
- Budget constraints
- Energy levels throughout the day

IMPORTANT: At the end of your response, provide a JSON block with structured itinerary data:
```json
{{
    "optimized_itinerary": [
        {{
            "day": 1,
            "date": "YYYY-MM-DD",
            "activities": [
                {{
                    "time": "HH:MM AM/PM",
                    "activity": "Activity name",
                    "duration": "X hours",
                    "cost": number,
                    "tips": "Practical tip"
                }}
            ],
            "total_cost": number,
            "weather_considerations": "Weather notes"
        }}
    ],
    "transport_details": {{
        "recommended_trains": ["Train name - departure time"],
        "booking_tips": ["Tip 1", "Tip 2"],
        "local_transport": "Recommendations"
    }},
    "key_tips": [
        "Important tip 1",
        "Important tip 2"
    ]
}}
```

Keep daily plans realistic - don't overschedule. Allow time for spontaneity and rest.
"""
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle itinerary request
        
        Expected request payload (complete travel state from orchestrator):
        {
            "destination": "Agra, India",
            "origin": "New Delhi, India",
            "travel_dates": ["2025-07-01", "2025-07-02"],
            "travelers_count": 2,
            "budget_range": "mid-range",
            "weather_data": {...},  # from weather agent (DICT with weather_forecast inside)
            "events_data": {...},   # from events agent
            "maps_data": {...},     # from maps agent
            "budget_data": {...}    # from budget agent
        }
        
        Returns:
        {
            "itinerary_days": [...],
            "itinerary_narrative": "...",
            "structured_data": {...},
            "transport_details": {...},
            "key_tips": [...]
        }
        """
        payload = request.get("payload", {})
        session_id = request.get("session_id")
        
        destination = payload.get("destination")
        travel_dates = payload.get("travel_dates", [])
        travelers_count = payload.get("travelers_count", 1)
        
        # Validate required fields
        if not destination:
            raise ValueError("Missing required field: destination")
        if not travel_dates:
            raise ValueError("Missing required field: travel_dates")
        
        self.log_action("Creating itinerary", f"{destination}, {len(travel_dates)} days")
        
        # Progress update: Getting destination info
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message=f"Gathering information about {destination}",
            progress_percent=20
        )
        
        # Get destination information using tool
        dest_info_result = await get_destination_info.ainvoke({
            "destination": destination
        })
        
        # Progress update: Creating initial itinerary
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Creating day-by-day itinerary",
            progress_percent=40,
            data={"destination_info_loaded": True}
        )
        
        # Extract budget total if available
        budget_total = None
        if payload.get("budget_data"):
            budget_data = payload["budget_data"]
            if isinstance(budget_data, dict):
                budget_breakdown = budget_data.get("budget_breakdown", {})
                if isinstance(budget_breakdown, dict):
                    budget_total = budget_breakdown.get("total")
        
        # ===== FIX: Extract weather_forecast list from weather_data dict =====
        weather_forecast_list = []
        if payload.get("weather_data"):
            weather_data = payload["weather_data"]
            if isinstance(weather_data, dict):
                # Extract the actual forecast list
                weather_forecast_list = weather_data.get("weather_forecast", [])
            elif isinstance(weather_data, list):
                # Already a list
                weather_forecast_list = weather_data
        
        # Create initial itinerary using tool
        itinerary_result = await create_daily_itinerary.ainvoke({
            "destination": destination,
            "travel_dates": travel_dates,
            "weather_data": weather_forecast_list,  # ← Pass the LIST, not the dict
            "budget_total": budget_total,
            "travelers_count": travelers_count
        })
        
        if "error" in itinerary_result:
            raise Exception(f"Itinerary creation failed: {itinerary_result['error']}")
        
        # Progress update: Optimizing by weather
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Optimizing schedule based on weather",
            progress_percent=60
        )
        
        # Optimize by weather if weather data available
        weather_optimization = None
        if weather_forecast_list:  # Use the extracted list
            weather_opt_result = await optimize_itinerary_by_weather.ainvoke({
                "destination": destination,
                "travel_dates": travel_dates,
                "weather_data": weather_forecast_list  # ← Pass the LIST here too
            })
            if "error" not in weather_opt_result:
                weather_optimization = weather_opt_result
        
        # Progress update: Synthesizing with LLM
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Generating personalized recommendations",
            progress_percent=80
        )
        
        # Generate comprehensive itinerary narrative using LLM
        itinerary_narrative = await self._generate_itinerary_synthesis(
            itinerary_result=itinerary_result,
            dest_info=dest_info_result,
            weather_optimization=weather_optimization,
            payload=payload,
            session_id=session_id
        )
        
        # Extract structured data from LLM response
        structured_data = self._extract_structured_itinerary_data(itinerary_narrative)
        
        # Format final itinerary days
        itinerary_days_list = []
        transport_details = {}
        key_tips = []
        
        if structured_data and 'optimized_itinerary' in structured_data:
            # Use LLM-optimized itinerary
            for day_data in structured_data['optimized_itinerary']:
                activities = []
                if isinstance(day_data.get('activities'), list):
                    for activity in day_data['activities']:
                        if isinstance(activity, dict):
                            activity_str = f"{activity.get('time', '')}: {activity.get('activity', '')} ({activity.get('duration', '')})"
                            if activity.get('tips'):
                                activity_str += f" - {activity['tips']}"
                            activities.append(activity_str)
                        else:
                            activities.append(str(activity))
                
                day_dict = {
                    "day": day_data.get('day', 1),
                    "date": day_data.get('date', ''),
                    "activities": activities,
                    "notes": day_data.get('weather_considerations', ''),
                    "estimated_cost": day_data.get('total_cost', 1500)
                }
                itinerary_days_list.append(day_dict)
            
            transport_details = structured_data.get('transport_details', {})
            key_tips = structured_data.get('key_tips', [])
        else:
            # Use basic itinerary from tool
            for day_data in itinerary_result.get("itinerary", []):
                itinerary_days_list.append({
                    "day": day_data.get("day", 1),
                    "date": day_data.get("date", ""),
                    "activities": day_data.get("activities", []),
                    "notes": day_data.get("notes", ""),
                    "estimated_cost": day_data.get("estimated_cost", 1500)
                })
        
        # Progress update: Finalizing
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Finalizing itinerary",
            progress_percent=95
        )
        
        self.log_action("Itinerary created", f"{len(itinerary_days_list)} days planned")
        
        return {
            "itinerary_days": itinerary_days_list,
            "itinerary_narrative": itinerary_narrative,
            "structured_data": structured_data or {},
            "transport_details": transport_details,
            "key_tips": key_tips,
            "destination": destination,
            "total_days": len(travel_dates),
            "travelers_count": travelers_count
        }  
    async def _generate_itinerary_synthesis(
        self,
        itinerary_result: Dict[str, Any],
        dest_info: Dict[str, Any],
        weather_optimization: Optional[Dict[str, Any]],
        payload: Dict[str, Any],
        session_id: str
    ) -> str:
        """Generate comprehensive itinerary synthesis using LLM"""
        
        # Format all available data for LLM
        synthesis_text = self._format_synthesis_data(
            itinerary_result,
            dest_info,
            weather_optimization,
            payload
        )
        
        user_input = f"""
Create a comprehensive, personalized travel itinerary:

DESTINATION: {payload.get('destination')}
ORIGIN: {payload.get('origin', 'Not specified')}
TRAVEL DATES: {', '.join(payload.get('travel_dates', []))} ({len(payload.get('travel_dates', []))} days)
TRAVELERS: {payload.get('travelers_count', 1)} people
BUDGET: {payload.get('budget_range', 'mid-range')}

{synthesis_text}

Please provide:
1. Optimized day-by-day schedule with specific times (be realistic about travel time)
2. Specific transport recommendations (train names, booking platforms like IRCTC/MakeMyTrip)
3. Activity duration estimates
4. Cost breakdown per activity
5. Weather-based activity suggestions
6. Integration of local events if available
7. Practical booking and timing tips
8. Best times to visit each attraction

Remember to:
- Allow time for meals and rest
- Consider opening hours and peak times
- Account for travel time between locations
- Don't overschedule - quality over quantity
- Include buffer time for unexpected delays

Include the structured JSON data at the end of your response.
Keep the narrative concise (5-6 sentences) before the JSON.
"""
        
        try:
            synthesis = await self.invoke_llm(
                system_prompt=self.get_system_prompt(),
                user_input=user_input,
                session_id=session_id,
                stream_progress=False  # Already sent progress updates
            )
            return synthesis
        except Exception as e:
            self.log_error("Failed to generate itinerary synthesis", str(e))
            return self._get_fallback_summary(itinerary_result)
    
    def _format_synthesis_data(
        self,
        itinerary_result: Dict[str, Any],
        dest_info: Dict[str, Any],
        weather_optimization: Optional[Dict[str, Any]],
        payload: Dict[str, Any]
    ) -> str:
        """Format all available data for LLM synthesis"""
        lines = []
        
        # Destination info
        lines.append("DESTINATION HIGHLIGHTS:")
        if dest_info and "must_visit" in dest_info:
            for attraction in dest_info["must_visit"]:
                lines.append(f"  • {attraction}")
        
        # Weather optimization
        if weather_optimization and "optimized_itinerary" in weather_optimization:
            lines.append("\nWEATHER CONSIDERATIONS:")
            for day in weather_optimization["optimized_itinerary"][:3]:  # First 3 days
                lines.append(f"  Day {day['day']}: {day['weather']['description']}, {day['weather']['temp_max']}°C")
                for rec in day.get("recommendations", [])[:2]:
                    lines.append(f"    - {rec}")
        
        # Budget info
        if payload.get("budget_data"):
            budget = payload["budget_data"]
            if isinstance(budget, dict):
                lines.append(f"\nBUDGET: ₹{budget.get('total', 0):,.0f} total")
                lines.append(f"  Daily average: ₹{budget.get('total', 0) / len(payload.get('travel_dates', [1])):,.0f}")
        
        # Events info
        if payload.get("events_data"):
            events = payload["events_data"]
            if isinstance(events, dict) and events.get("events"):
                lines.append(f"\nLOCAL EVENTS: {events.get('total_events', 0)} events found")
                for event in events["events"][:2]:  # Top 2 events
                    if isinstance(event, dict):
                        lines.append(f"  • {event.get('name', 'Event')} on {event.get('date', 'TBA')}")
        
        # Route info
        if payload.get("maps_data") or payload.get("route_data"):
            route = payload.get("maps_data") or payload.get("route_data")
            if isinstance(route, dict):
                primary_route = route.get("primary_route", route)
                if isinstance(primary_route, dict):
                    lines.append(f"\nTRAVEL: {primary_route.get('distance', 'N/A')} in {primary_route.get('duration', 'N/A')}")
                    lines.append(f"  Mode: {primary_route.get('transport_mode', 'driving')}")
        
        return "\n".join(lines)
    
    def _get_fallback_summary(self, itinerary_result: Dict[str, Any]) -> str:
        """Generate basic fallback summary if LLM fails"""
        total_days = itinerary_result.get("total_days", 1)
        destination = itinerary_result.get("destination", "your destination")
        
        return (
            f"Created a {total_days}-day itinerary for {destination}. "
            f"The plan includes daily activities covering must-visit attractions, "
            f"local experiences, and dining recommendations. Check the detailed "
            f"day-by-day breakdown for specific timings and tips."
        )
    
    def _extract_structured_itinerary_data(self, llm_response: str) -> Optional[Dict[str, Any]]:
        """Extract structured JSON data from LLM response"""
        try:
            # Look for JSON code blocks
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', llm_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                return json.loads(json_str)
            
            # Alternative: look for JSON-like structures
            json_match = re.search(r'\{[^{}]*"optimized_itinerary"[^{}]*\[.*?\][^{}]*\}', llm_response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
                
        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to parse structured itinerary data: {e}")
        except Exception as e:
            self.logger.error(f"Error extracting structured itinerary data: {e}")
        
        return None


# ==================== STANDALONE RUNNER ====================

async def run_itinerary_agent_standalone():
    """Run the itinerary agent as a standalone service"""
    from app.messaging.redis_client import get_redis_client, RedisChannels
    from app.config.settings import settings
    
    # Get Redis client
    redis_client = get_redis_client()
    await redis_client.connect()
    
    # Create itinerary agent
    itinerary_agent = ItineraryAgent(
        redis_client=redis_client,
        gemini_api_key=settings.google_api_key,
        model_name=settings.model_name
    )
    
    # Start the agent
    await itinerary_agent.start()
    
    print(f"✅ Itinerary Agent is running!")
    print(f"   Agent: {itinerary_agent.name}")
    print(f"   Type: {itinerary_agent.agent_type.value}")
    print(f"   Listening on: {RedisChannels.get_request_channel('itinerary')}")
    print(f"\nPress Ctrl+C to stop...")
    
    try:
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down Itinerary Agent...")
        await itinerary_agent.stop()
        await redis_client.disconnect()
        print("✅ Itinerary Agent stopped")


if __name__ == "__main__":
    import asyncio
    from app.messaging.redis_client import RedisChannels
    
    asyncio.run(run_itinerary_agent_standalone())