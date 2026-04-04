"""
Events Agent Implementation with LangChain Tools and Redis Pub/Sub

Follows the same structure as WeatherAgent and MapsAgent:
- Extends BaseAgent
- Uses LangChain tools for event operations
- Supports MCP protocol via Redis pub/sub
- Streaming updates
"""

from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from app.agents.base_agent import BaseAgent, AgentType, StreamingUpdateType
from app.tools.events_tools import EVENT_TOOLS, search_events, get_events_for_dates, get_popular_events
from app.messaging.redis_client import RedisClient
from app.services.event_service import EventService
from app.core.state import EventInfo


class EventsAgent(BaseAgent):
    """
    Events Agent - Local events and entertainment discovery
    
    Uses LangChain tools and Google Gemini for intelligent event recommendations
    """
    
    def __init__(
        self,
        redis_client: RedisClient,
        gemini_api_key: str = None,
        model_name: str = "gemini-2.0-flash-exp"
    ):
        super().__init__(
            name="Buzzfinder",
            role="Local Events Specialist",
            expertise="Finding local events, entertainment, festivals, and cultural activities using OpenWeb Ninja Real-Time Events Search",
            agent_type=AgentType.EVENTS,
            redis_client=redis_client,
            tools=EVENT_TOOLS,
            gemini_api_key=gemini_api_key,
            model_name=model_name
        )
        
        self.event_service = EventService()
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for the events agent"""
        return f"""
You are {self.name}, a {self.role}. Your role is to:

1. Find real-time events and activities during travel dates from Google Events
2. Recommend events based on traveler interests and venue types
3. Provide comprehensive event details including timing, venues, and booking links
4. Suggest must-attend cultural experiences, festivals, and entertainment
5. Help optimize travel itinerary around special events and local happenings
6. Warn about major events that might affect accommodation, transport, or crowd levels
7. Identify free events and budget-friendly entertainment options

Expertise: {self.expertise}

You have access to event tools that can:
- Search for events in a location and date range
- Get events for specific dates
- Find popular upcoming events
- Search events by category (music, sports, arts, theatre, comedy, family, business, food, film)
- Search events with custom queries
- Get detailed event information
- List available categories and date filters

Event data includes:
- Concert and music events at various venues
- Sports matches and tournaments
- Art exhibitions and cultural events
- Film festivals and movie screenings
- Food festivals and culinary events
- Business conferences and workshops
- Family-friendly activities
- Comedy shows and entertainment

Always provide practical event recommendations that enhance the travel experience.
Focus on events that are accessible to travelers and worth attending.
Consider the traveler's schedule, budget, and interests when making recommendations.
Highlight venue information, ratings, and accessibility details.

When analyzing events, include:
- Highlighted must-attend events during the trip
- Event categories available with venue details
- Pricing information and booking sources
- Transportation and timing considerations
- Cultural significance and local context of major events
- Free events and budget-friendly options

Keep responses concise and actionable.
"""
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle events request
        
        Expected request payload:
        {
            "destination": "Paris, France",
            "travel_dates": ["2025-07-01", "2025-07-02"],
            "interests": ["music", "arts"],  # optional
            "include_popular": true  # optional, default: true
        }
        
        Returns:
        {
            "events": [...],
            "event_summary": "...",
            "statistics": {...},
            "free_events": [...],
            "categories": {...}
        }
        """
        payload = request.get("payload", {})
        session_id = request.get("session_id")
        
        destination = payload.get("destination")
        travel_dates = payload.get("travel_dates", [])
        interests = payload.get("interests")  # List of categories
        include_popular = payload.get("include_popular", True)
        
        # Validate required fields
        if not destination:
            raise ValueError("Missing required field: destination")
        if not travel_dates:
            raise ValueError("Missing required field: travel_dates")
        
        self.log_action("Searching events", f"{destination}, {len(travel_dates)} days")
        
        # Progress update: Searching for events
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message=f"Searching events in {destination}",
            progress_percent=30
        )
        
        # Fetch events for specific dates using the tool
        events_result = await get_events_for_dates.ainvoke({
            "location": destination,
            "dates": travel_dates,
            "categories": interests
        })
        
        if "error" in events_result:
            self.logger.warning(f"Events fetch failed: {events_result['error']}")
        
        events_list = events_result.get("events", [])
        
        # Get popular events if requested
        popular_events_list = []
        if include_popular:
            await self._send_streaming_update(
                session_id=session_id,
                update_type=StreamingUpdateType.PROGRESS,
                message="Fetching popular upcoming events",
                progress_percent=50,
                data={"events_for_dates_complete": True}
            )
            
            popular_result = await get_popular_events.ainvoke({
                "location": destination,
                "days_ahead": 30,
                "limit": 10
            })
            
            popular_events_list = popular_result.get("events", [])
        
        # Combine and deduplicate
        all_events = self._deduplicate_events(events_list + popular_events_list)
        
        # Progress update: Analyzing events
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message=f"Analyzing {len(all_events)} events",
            progress_percent=70
        )
        
        # Generate intelligent event analysis using LLM
        event_summary = await self._generate_event_analysis(
            events=all_events,
            destination=destination,
            travel_dates=travel_dates,
            interests=interests,
            session_id=session_id
        )
        
        # Calculate statistics
        statistics = self._calculate_statistics(all_events)
        free_events = [e for e in all_events if self._is_free_event(e)]
        categories_breakdown = self._categorize_events(all_events)
        
        # Progress update: Finalizing
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Finalizing event recommendations",
            progress_percent=90
        )
        
        self.log_action("Events search complete", f"Found {len(all_events)} events")
        
        return {
            "events": all_events,
            "event_summary": event_summary,
            "statistics": statistics,
            "free_events": free_events,
            "categories": categories_breakdown,
            "destination": destination,
            "total_events": len(all_events),
            "free_events_count": len(free_events),
            "has_events": len(all_events) > 0
        }
    
    async def _generate_event_analysis(
        self,
        events: List[Dict[str, Any]],
        destination: str,
        travel_dates: List[str],
        interests: Optional[List[str]],
        session_id: str
    ) -> str:
        """Generate intelligent event analysis using LLM"""
        
        if not events:
            return f"No major events found for your travel dates in {destination}. Check local venues for smaller events or consider expanding your date range."
        
        # Format events for LLM
        events_text = self._format_events_for_llm(events)
        
        interests_text = f"Interests: {', '.join(interests)}" if interests else "No specific interests provided"
        
        user_input = f"""
Destination: {destination}
Travel Dates: {', '.join(travel_dates)}
{interests_text}

Real-Time Events Data (OpenWeb Ninja):
{events_text}

Please provide event recommendations and insights for this trip. Focus on:
- Must-attend events during travel dates with venue details
- Cultural significance and local context of events
- Pricing and booking advice
- Events that align with travel schedule and interests
- Free events and budget-friendly entertainment options
- Transportation considerations for venue locations

Keep the analysis concise and practical - 3-4 sentences maximum.
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
            self.log_error("Failed to generate event analysis", str(e))
            return self._get_fallback_summary(events)
    
    def _format_events_for_llm(self, events: List[Dict[str, Any]]) -> str:
        """Format event data for LLM consumption"""
        if not events:
            return "No events available."
        
        formatted_lines = []
        
        # Group events by category
        categories = {}
        for event in events:
            category = event.get("category", "miscellaneous")
            if category not in categories:
                categories[category] = []
            categories[category].append(event)
        
        # Format each category
        for category, category_events in categories.items():
            formatted_lines.append(f"\n{category.upper()} EVENTS:")
            
            # Limit to top 3 events per category
            for event in category_events[:3]:
                name = event.get("name", "Unknown Event")
                date = event.get("date", "TBA")
                time = event.get("time", "")
                venue = event.get("venue", "TBA")
                price_min = event.get("price_min")
                price_max = event.get("price_max")
                
                # Format price
                if price_min is not None and price_max is not None:
                    if price_min == 0:
                        price_text = "Free"
                    else:
                        currency = event.get("currency", "USD")
                        price_text = f"{currency} {price_min}-{price_max}"
                else:
                    price_text = "Price TBA"
                
                formatted_lines.append(
                    f"  • {name}\n"
                    f"    Date: {date} {time}\n"
                    f"    Venue: {venue}\n"
                    f"    Price: {price_text}"
                )
        
        return "\n".join(formatted_lines)
    
    def _get_fallback_summary(self, events: List[Dict[str, Any]]) -> str:
        """Generate basic fallback summary if LLM fails"""
        if not events:
            return "No events found during your travel period."
        
        categories = set(e.get("category", "miscellaneous") for e in events)
        free_events = sum(1 for e in events if self._is_free_event(e))
        
        summary = f"Found {len(events)} events across {len(categories)} categories"
        if free_events > 0:
            summary += f", including {free_events} free events"
        
        return f"{summary}. Check the detailed event list for more information."
    
    def _calculate_statistics(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate detailed event statistics"""
        if not events:
            return {
                "total_events": 0,
                "categories": {},
                "venues_count": 0,
                "free_events_count": 0,
                "paid_events_count": 0
            }
        
        categories = {}
        venues = set()
        free_events = 0
        paid_events = 0
        
        for event in events:
            # Count by category
            category = event.get("category", "miscellaneous")
            categories[category] = categories.get(category, 0) + 1
            
            # Count venues
            venue = event.get("venue")
            if venue:
                venues.add(venue)
            
            # Count free vs paid
            if self._is_free_event(event):
                free_events += 1
            elif event.get("price_min") is not None and event.get("price_min") > 0:
                paid_events += 1
        
        return {
            "total_events": len(events),
            "categories": categories,
            "venues_count": len(venues),
            "free_events_count": free_events,
            "paid_events_count": paid_events
        }
    
    def _categorize_events(self, events: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Categorize events by type"""
        categories = {}
        for event in events:
            category = event.get("category", "miscellaneous")
            if category not in categories:
                categories[category] = []
            categories[category].append(event.get("name", "Unknown Event"))
        return categories
    
    def _is_free_event(self, event: Dict[str, Any]) -> bool:
        """Check if event is free"""
        price_min = event.get("price_min")
        return price_min is not None and price_min == 0
    
    def _deduplicate_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate events based on name, date, and venue"""
        seen = set()
        unique_events = []
        
        for event in events:
            name = event.get("name", "").lower().strip()
            date = event.get("date", "")
            venue = event.get("venue", "").lower().strip()
            
            event_key = (name, date, venue)
            
            if event_key not in seen:
                seen.add(event_key)
                unique_events.append(event)
        
        return unique_events


# ==================== STANDALONE RUNNER ====================

async def run_events_agent_standalone():
    """Run the events agent as a standalone service"""
    from app.messaging.redis_client import get_redis_client, RedisChannels
    from app.config.settings import settings
    
    # Get Redis client
    redis_client = get_redis_client()
    await redis_client.connect()
    
    # Create events agent
    events_agent = EventsAgent(
        redis_client=redis_client,
        gemini_api_key=settings.google_api_key,
        model_name=settings.model_name
    )
    
    # Start the agent
    await events_agent.start()
    
    print(f"✅ Events Agent is running!")
    print(f"   Agent: {events_agent.name}")
    print(f"   Type: {events_agent.agent_type.value}")
    print(f"   Listening on: {RedisChannels.get_request_channel('events')}")
    print(f"\nPress Ctrl+C to stop...")
    
    try:
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down Events Agent...")
        await events_agent.stop()
        await redis_client.disconnect()
        print("✅ Events Agent stopped")


if __name__ == "__main__":
    import asyncio
    from app.messaging.redis_client import RedisChannels
    
    asyncio.run(run_events_agent_standalone())