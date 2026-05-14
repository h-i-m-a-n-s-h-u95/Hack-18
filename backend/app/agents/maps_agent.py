"""
Maps Agent Implementation with LangChain Tools and Redis Pub/Sub

Follows the same structure as WeatherAgent:
- Extends BaseAgent
- Uses LangChain tools for map operations
- Supports MCP protocol via Redis pub/sub
- Streaming updates
"""

from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from app.agents.base_agent import BaseAgent, AgentType, StreamingUpdateType
from app.tools.maps_tools import MAPS_TOOLS, get_route, get_multiple_routes, get_comprehensive_travel_options
from app.messaging.redis_client import RedisClient
from app.services.maps_service import MapsService
from app.core.state import RouteInfo


class MapsAgent(BaseAgent):
    """
    Maps Agent - Route planning and transportation analysis
    
    Uses LangChain tools and Google Gemini for intelligent route analysis
    """
    
    def __init__(
        self,
        redis_client: RedisClient,
        groq_api_key: str = None,
        model_name: str = "llama-3.3-70b-versatile"
    ):
        super().__init__(
            name="Trailblazer",
            role="Route Planner & Navigator",
            expertise="Route optimization, transportation analysis, and travel logistics",
            agent_type=AgentType.MAPS,
            redis_client=redis_client,
            tools=MAPS_TOOLS,
            groq_api_key=groq_api_key,
            model_name=model_name
        )
        
        self.maps_service = MapsService()
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for the maps agent"""
        return f"""
You are {self.name}, a {self.role}. Your role is to:

1. Analyze route options between origin and destination
2. Compare different transportation modes (driving, walking, cycling)
3. Provide practical travel recommendations based on distance and duration
4. Suggest optimal transportation methods considering time, cost, and convenience
5. Identify potential travel challenges or considerations
6. Analyze flights, trains, buses, and hotel options when requested

Expertise: {self.expertise}

You have access to maps tools that can:
- Geocode locations to coordinates
- Get routes between locations (driving, walking, cycling)
- Compare multiple transport modes
- Search flights, trains, and buses
- Find hotels at destinations
- Get comprehensive travel options

Always provide practical, actionable route advice that helps travelers make informed decisions.
Be concise but informative. Focus on how route choices will impact the travel experience.

When analyzing routes, include:
- Recommended transportation mode and reasoning
- Journey overview with distance and duration
- Alternative options if relevant
- Any notable considerations or tips

Keep responses brief - 2-3 sentences for summaries unless more detail is requested.
"""
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle maps request
        
        Expected request payload:
        {
            "origin": "New Delhi, India",
            "destination": "Agra, India",
            "transport_mode": "driving",  # optional, default: "driving"
            "include_alternatives": true,  # optional, default: true
            "include_travel_options": false,  # optional, default: false
            "travel_date": "2025-07-01",  # required if include_travel_options=true
            "checkin_date": "2025-07-01",  # optional
            "checkout_date": "2025-07-05"  # optional
        }
        
        Returns:
        {
            "primary_route": {...},
            "alternative_routes": {...},
            "route_analysis": "...",
            "recommended_mode": "driving",
            "comparison": {...},
            "travel_options": {...}  # if requested
        }
        """
        payload = request.get("payload", {})
        session_id = request.get("session_id")
        
        origin = payload.get("origin")
        destination = payload.get("destination")
        transport_mode = payload.get("transport_mode", "driving")
        include_alternatives = payload.get("include_alternatives", True)
        include_travel_options = payload.get("include_travel_options", False)
        
        # Validate required fields
        if not origin:
            raise ValueError("Missing required field: origin")
        if not destination:
            raise ValueError("Missing required field: destination")
        
        self.log_action("Fetching route", f"{origin} → {destination} ({transport_mode})")
        
        # Progress update: Fetching primary route
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message=f"Calculating route from {origin} to {destination}",
            progress_percent=20
        )
        
        # Fetch primary route using the tool
        primary_route_result = await get_route.ainvoke({
            "origin": origin,
            "destination": destination,
            "transport_mode": transport_mode
        })
        
        if "error" in primary_route_result:
            self.logger.warning(f"Primary route fetch failed: {primary_route_result['error']}")
            primary_route_result = self._create_fallback_route(origin, destination, transport_mode)
        
        result = {
            "primary_route": primary_route_result,
            "origin": origin,
            "destination": destination,
            "requested_mode": transport_mode
        }
        
        # Get alternative routes if requested
        alternative_routes = {}
        if include_alternatives:
            await self._send_streaming_update(
                session_id=session_id,
                update_type=StreamingUpdateType.PROGRESS,
                message="Analyzing alternative transportation options",
                progress_percent=40,
                data={"primary_route_complete": True}
            )
            
            # Fetch alternatives using tool
            alternatives_result = await get_multiple_routes.ainvoke({
                "origin": origin,
                "destination": destination
            })
            
            if "error" not in alternatives_result:
                alternative_routes = alternatives_result.get("routes", {})
                # Remove the primary mode from alternatives
                alternative_routes = {
                    k: v for k, v in alternative_routes.items()
                    if k != transport_mode and "error" not in v
                }
            
            result["alternative_routes"] = alternative_routes
        
        # Get comprehensive travel options if requested
        if include_travel_options:
            await self._send_streaming_update(
                session_id=session_id,
                update_type=StreamingUpdateType.PROGRESS,
                message="Fetching travel options (flights, trains, buses, hotels)",
                progress_percent=60
            )
            
            travel_date = payload.get("travel_date")
            checkin = payload.get("checkin_date")
            checkout = payload.get("checkout_date")
            
            if not travel_date:
                self.log_error("Travel options requested but no travel_date provided", "Skipping")
            else:
                travel_options_result = await get_comprehensive_travel_options.ainvoke({
                    "origin": origin,
                    "destination": destination,
                    "date": travel_date,
                    "checkin": checkin,
                    "checkout": checkout
                })
                
                result["travel_options"] = travel_options_result
        
        # Progress update: Generating analysis
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Generating route recommendations",
            progress_percent=80
        )
        
        # Generate intelligent route analysis using LLM
        route_analysis = await self._generate_route_analysis(
            primary_route=primary_route_result,
            alternative_routes=alternative_routes,
            origin=origin,
            destination=destination,
            session_id=session_id
        )
        
        result["route_analysis"] = route_analysis
        result["recommended_mode"] = self._determine_recommended_mode(
            primary_route_result, alternative_routes
        )
        result["comparison"] = self._create_route_comparison(
            primary_route_result, alternative_routes
        )
        
        # Progress update: Finalizing
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Finalizing route report",
            progress_percent=90
        )
        
        self.log_action(
            "Route analysis complete",
            f"Primary: {transport_mode}, Alternatives: {len(alternative_routes)}"
        )
        
        return result
    
    async def _generate_route_analysis(
        self,
        primary_route: Dict[str, Any],
        alternative_routes: Dict[str, Dict[str, Any]],
        origin: str,
        destination: str,
        session_id: str
    ) -> str:
        """Generate intelligent route analysis using LLM"""
        
        # Format route data for LLM
        route_text = self._format_routes_for_llm(primary_route, alternative_routes)
        
        user_input = f"""
Origin: {origin}
Destination: {destination}

Route Information:
{route_text}

Please provide a concise route analysis including:
1. Recommended transportation mode and why
2. Journey overview (distance and duration)
3. Key considerations for this route
4. Alternative options if relevant

Keep it brief and practical - 2-3 sentences maximum.
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
            self.log_error("Failed to generate route analysis", str(e))
            return self._get_fallback_summary(primary_route)
    
    def _format_routes_for_llm(
        self,
        primary_route: Dict[str, Any],
        alternative_routes: Dict[str, Dict[str, Any]]
    ) -> str:
        """Format route data for LLM consumption"""
        formatted_lines = []
        
        # Primary route
        mode = primary_route.get("transport_mode", "driving")
        distance = primary_route.get("distance", "N/A")
        duration = primary_route.get("duration", "N/A")
        
        formatted_lines.append(f"PRIMARY ROUTE ({mode.upper()}):")
        formatted_lines.append(f"  Distance: {distance}")
        formatted_lines.append(f"  Duration: {duration}")
        formatted_lines.append("")
        
        # Alternative routes
        if alternative_routes:
            formatted_lines.append("ALTERNATIVES:")
            for alt_mode, alt_route in alternative_routes.items():
                alt_distance = alt_route.get("distance", "N/A")
                alt_duration = alt_route.get("duration", "N/A")
                formatted_lines.append(f"  {alt_mode.upper()}:")
                formatted_lines.append(f"    Distance: {alt_distance}")
                formatted_lines.append(f"    Duration: {alt_duration}")
        
        return "\n".join(formatted_lines)
    
    def _create_fallback_route(
        self,
        origin: str,
        destination: str,
        transport_mode: str
    ) -> Dict[str, Any]:
        """Create fallback route when API fails"""
        return {
            "origin": origin,
            "destination": destination,
            "distance": "Distance unavailable",
            "duration": "Duration unavailable",
            "steps": [f"Travel from {origin} to {destination}"],
            "transport_mode": transport_mode,
            "fallback": True
        }
    
    def _get_fallback_summary(self, primary_route: Dict[str, Any]) -> str:
        """Generate basic fallback summary if LLM fails"""
        mode = primary_route.get("transport_mode", "driving")
        distance = primary_route.get("distance", "N/A")
        duration = primary_route.get("duration", "N/A")
        
        return (
            f"Route calculated: {distance} journey taking approximately {duration} "
            f"by {mode}. Please check detailed route information for turn-by-turn directions."
        )
    
    def _determine_recommended_mode(
        self,
        primary_route: Dict[str, Any],
        alternative_routes: Dict[str, Dict[str, Any]]
    ) -> str:
        """Determine the recommended transportation mode"""
        if primary_route and "error" not in primary_route:
            return primary_route.get("transport_mode", "driving")
        
        # Fall back to first available alternative
        for mode, route in alternative_routes.items():
            if route and "error" not in route:
                return mode
        
        return "driving"
    
    def _create_route_comparison(
        self,
        primary_route: Dict[str, Any],
        alternative_routes: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, str]]:
        """Create a comparison summary of all routes"""
        comparison = {}
        
        # Add primary route
        if primary_route and "error" not in primary_route:
            mode = primary_route.get("transport_mode", "driving")
            comparison[mode] = {
                "distance": primary_route.get("distance", "N/A"),
                "duration": primary_route.get("duration", "N/A"),
                "mode": mode
            }
        
        # Add alternatives
        for mode, route in alternative_routes.items():
            if route and "error" not in route:
                comparison[mode] = {
                    "distance": route.get("distance", "N/A"),
                    "duration": route.get("duration", "N/A"),
                    "mode": mode
                }
        
        return comparison


# ==================== STANDALONE RUNNER ====================

async def run_maps_agent_standalone():
    """Run the maps agent as a standalone service"""
    from app.messaging.redis_client import get_redis_client, RedisChannels
    from app.config.settings import settings
    
    # Get Redis client
    redis_client = get_redis_client()
    await redis_client.connect()
    
    # Create maps agent
    maps_agent = MapsAgent(
        redis_client=redis_client,
        groq_api_key=settings.groq_api_key,
        model_name=settings.model_name
    )
    
    # Start the agent
    await maps_agent.start()
    
    print(f"✅ Maps Agent is running!")
    print(f"   Agent: {maps_agent.name}")
    print(f"   Type: {maps_agent.agent_type.value}")
    print(f"   Listening on: {RedisChannels.get_request_channel('maps')}")
    print(f"\nPress Ctrl+C to stop...")
    
    try:
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down Maps Agent...")
        await maps_agent.stop()
        await redis_client.disconnect()
        print("✅ Maps Agent stopped")


if __name__ == "__main__":
    import asyncio
    from app.messaging.redis_client import RedisChannels
    
    asyncio.run(run_maps_agent_standalone())