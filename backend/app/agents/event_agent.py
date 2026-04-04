from typing import List
import json
from app.agents.base_agent import BaseAgent
from app.core.state import TravelState, EventInfo
from app.services.event_service import EventService


class EventAgent(BaseAgent):
    """Event Explorer - Local events and entertainment agent using OpenWeb Ninja API"""
    
    def __init__(self):
        super().__init__(
            name="Event Explorer",
            role="Local Events Specialist", 
            expertise="Finding local events, entertainment, festivals, and cultural activities using OpenWeb Ninja Real-Time Events Search"
        )
        self.event_service = EventService()
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for the event agent"""
        return """
        You are the Event Explorer, a local events and entertainment specialist using the OpenWeb Ninja Real-Time Events Search API. Your role is to:
        
        1. Find real-time events and activities during travel dates from Google Events
        2. Recommend events based on traveler interests and venue types
        3. Provide comprehensive event details including timing, venues, and booking links
        4. Suggest must-attend cultural experiences, festivals, and entertainment
        5. Help optimize travel itinerary around special events and local happenings
        6. Warn about major events that might affect accommodation, transport, or crowd levels
        7. Identify free events and budget-friendly entertainment options
        
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
        
        When given event data, create a summary that includes:
        - Highlighted must-attend events during the trip
        - Event categories available with venue details
        - Pricing information and booking sources
        - Transportation and timing considerations
        - Cultural significance and local context of major events
        - Free events and budget-friendly options
        """
    
    async def process(self, state: TravelState) -> TravelState:
        """Process event information for the travel destination using OpenWeb Ninja API"""
        self.log_action("Starting OpenWeb Ninja event search", f"Destination: {state['destination']}")
        
        try:
            # Get events for travel dates using date range
            events_data = await self.event_service.get_events_for_dates(
                location=state['destination'],
                dates=state['travel_dates'],
                categories=state.get('preferred_event_categories')
            )
            
            # Also get popular upcoming events for broader context
            popular_events = await self.event_service.get_popular_events(
                location=state['destination'],
                days_ahead=30,
                limit=5
            )
            
            # Combine and deduplicate events
            all_events = self._deduplicate_events(events_data + popular_events)
            
            if all_events:
                # Store event data in state
                state['events_data'] = all_events
                state['events_complete'] = True
                
                # Generate event insights using LLM with OpenWeb Ninja data
                event_summary = await self._generate_openweb_event_insights(all_events, state)
                
                # Extract event statistics
                stats = self._get_event_statistics(all_events)
                
                self.add_message_to_state(
                    state, 
                    f"Found {len(all_events)} events in {state['destination']} via OpenWeb Ninja. {stats} {event_summary}"
                )
                
                self.log_action("OpenWeb Ninja event search completed", f"Found {len(all_events)} events")
            else:
                # No events found, but don't treat as error
                state['events_data'] = []
                state['events_complete'] = True
                self.add_message_to_state(
                    state,
                    f"No major events found for your travel dates in {state['destination']} via OpenWeb Ninja. Check local venues for smaller events or try expanding your date range."
                )
                self.log_action("No events found for travel dates")
                
        except Exception as e:
            error_msg = f"Failed to get event data from OpenWeb Ninja: {str(e)}"
            self.add_error_to_state(state, error_msg)
            state['events_complete'] = True  # Mark as complete to continue workflow
            self.log_error("OpenWeb Ninja event search failed", str(e))
            
        return state
    
    async def _generate_openweb_event_insights(self, events_data: List[EventInfo], state: TravelState) -> str:
        """Generate event insights using the LLM with OpenWeb Ninja data structure"""
        # Format event data for the LLM with OpenWeb Ninja specific details
        events_summary = self._format_openweb_events_for_llm(events_data)
        location_context = self.format_location_context(state)
        
        user_input = f"""
        {location_context}
        
        Real-Time Events Data from OpenWeb Ninja (Google Events):
        {events_summary}
        
        Please provide event recommendations and insights for this trip. Focus on:
        - Must-attend events during travel dates with venue details
        - Cultural significance and local context of events
        - Venue ratings and accessibility information  
        - Pricing and booking advice with multiple sources
        - Events that align with travel schedule and interests
        - Free events and budget-friendly entertainment options
        - Transportation considerations for venue locations
        """
        
        try:
            insights = await self.invoke_llm(self.get_system_prompt(), user_input)
            return insights
        except Exception as e:
            self.log_error("Failed to generate OpenWeb Ninja event insights", str(e))
            return self._create_basic_openweb_event_summary(events_data)
    
    def _format_openweb_events_for_llm(self, events_data: List[EventInfo]) -> str:
        """Format OpenWeb Ninja event data for LLM consumption"""
        if not events_data:
            return "No events found for the specified dates."
        
        formatted_events = []
        
        # Group events by category and include venue details
        categories = {}
        for event in events_data:
            category = event.category
            if category not in categories:
                categories[category] = []
            categories[category].append(event)
        
        for category, events in categories.items():
            formatted_events.append(f"\n{category.upper()} EVENTS:")
            
            for event in events[:3]:  # Limit to 3 events per category for LLM
                # Format pricing information
                price_info = event.price_range if hasattr(event, 'price_range') else "Price TBA"
                
                # Include venue details from OpenWeb Ninja
                venue_details = f"Venue: {event.venue}"
                if event.address:
                    venue_details += f" ({event.address})"
                
                formatted_events.append(f"""
                • {event.name}
                  Date: {event.datetime_str if hasattr(event, 'datetime_str') else f"{event.date} at {event.time}"}
                  {venue_details}
                  Price: {price_info}
                  URL: {event.url if event.url else 'Direct booking required'}
                  Description: {event.description[:150]}{'...' if len(event.description) > 150 else ''}
                """)
        
        return "\n".join(formatted_events)
    
    def _create_basic_openweb_event_summary(self, events_data: List[EventInfo]) -> str:
        """Create a basic event summary without LLM using OpenWeb Ninja data"""
        if not events_data:
            return "No events found during your travel period via OpenWeb Ninja."
        
        categories = set(event.category for event in events_data)
        free_events = sum(1 for event in events_data if hasattr(event, 'is_free') and event.is_free())
        venues_count = len(set(event.venue for event in events_data))
        
        summary = f"Found {len(events_data)} events across {len(categories)} categories at {venues_count} venues"
        if free_events > 0:
            summary += f", including {free_events} free events"
        
        return summary
    
    def _get_event_statistics(self, events_data: List[EventInfo]) -> str:
        """Get comprehensive event statistics from OpenWeb Ninja data"""
        if not events_data:
            return ""
        
        categories = {}
        venues = set()
        free_events = 0
        paid_events = 0
        
        for event in events_data:
            # Count by category
            categories[event.category] = categories.get(event.category, 0) + 1
            # Count venues
            venues.add(event.venue)
            # Count free vs paid
            if hasattr(event, 'is_free') and event.is_free():
                free_events += 1
            elif event.price_min is not None and event.price_min > 0:
                paid_events += 1
        
        # Format category distribution
        top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:3]
        category_summary = ", ".join([f"{count} {cat}" for cat, count in top_categories])
        
        stats = f"Categories: {category_summary}. Venues: {len(venues)}."
        if free_events > 0:
            stats += f" {free_events} free events."
        
        return stats
    
    def _deduplicate_events(self, events: List[EventInfo]) -> List[EventInfo]:
        """Remove duplicate events based on name, date, and venue"""
        seen = set()
        unique_events = []
    
        for event in events:
            # Create a unique identifier for each event
            event_key = (
                event.name.lower().strip(),
                event.date,
                event.venue.lower().strip()
            )
        
            if event_key not in seen:
                seen.add(event_key)
                unique_events.append(event)
    
        return unique_events