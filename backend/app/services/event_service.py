import httpx
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from app.config.settings import settings
import random
from app.core.state import EventInfo
import logging

logger = logging.getLogger(__name__)


class EventService:
    """Service for fetching events data from OpenWeb Ninja Real-Time Events Search API"""
    
    def __init__(self):
        self.api_key = getattr(settings, 'openweb_ninja_api_key', None)
        self.base_url = getattr(settings,'openweb_ninja_base_url',None)
        self.timeout = 30.0
    
    async def search_events(
        self, 
        location: str, 
        start_date: str, 
        end_date: str,
        categories: List[str] = None,
        size: int = 20
    ) -> List[EventInfo]:
        """Search for events in a location within date range"""
        if not self.api_key:
            logger.warning("OpenWeb Ninja API key not configured, using fallback data")
            return await self._create_fallback_events(location, start_date, end_date)
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Determine date filter based on date range
                date_filter = self._get_date_filter(start_date, end_date)
                
                params = {
                    "query": f"Events in {location}",
                    "date": date_filter,
                    "is_virtual": False,
                    "start": 0
                }
                
                headers = {
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json"
                }
                
                response = await client.get(self.base_url, params=params, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                events = self._parse_openweb_events(data)
                
                # Filter events by date range and categories
                filtered_events = self._filter_events(events, start_date, end_date, categories)
                
                return filtered_events[:size]
                
        except httpx.TimeoutException:
            logger.error("OpenWeb Ninja API timeout")
            return await self._create_fallback_events(location, start_date, end_date)
        except httpx.HTTPError as e:
            logger.error(f"OpenWeb Ninja API HTTP error: {str(e)}")
            return await self._create_fallback_events(location, start_date, end_date)
        except Exception as e:
            logger.error(f"Failed to fetch events from OpenWeb Ninja: {str(e)}")
            return await self._create_fallback_events(location, start_date, end_date)
    
    def _get_date_filter(self, start_date: str, end_date: str) -> str:
        """Convert date range to OpenWeb Ninja date filter"""
        try:
            start_dt = datetime.fromisoformat(start_date).date()
            end_dt = datetime.fromisoformat(end_date).date()
            today = datetime.now().date()
            
            # Calculate days from today
            days_to_start = (start_dt - today).days
            days_to_end = (end_dt - today).days
            
            if days_to_start <= 0 and days_to_end >= 0:
                return "today"
            elif days_to_start == 1:
                return "tomorrow"
            elif days_to_start <= 7:
                return "week"
            elif days_to_start <= 14:
                return "next_week"
            elif days_to_start <= 30:
                return "month"
            elif days_to_start <= 60:
                return "next_month"
            else:
                return "any"
        except:
            return "any"
    
    def _parse_openweb_events(self, data: Dict[str, Any]) -> List[EventInfo]:
        """Parse OpenWeb Ninja API response into EventInfo objects"""
        events = []
        
        if data.get("status") != "OK":
            logger.warning(f"OpenWeb Ninja API returned status: {data.get('status')}")
            return events
        
        events_data = data.get("data", [])
        
        for event_data in events_data:
            try:
                # Extract event details
                name = event_data.get("name", "Unknown Event")
                description = event_data.get("description") or ""
                
                # Parse date and time
                start_time = event_data.get("start_time", "")
                end_time = event_data.get("end_time", "")
                
                if start_time:
                    # Convert to date and time format
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    date_str = start_dt.date().isoformat()
                    time_str = start_dt.time().strftime('%H:%M')
                else:
                    date_str = ""
                    time_str = ""
                
                # Extract venue information
                venue_info = event_data.get("venue", {})
                venue_name = venue_info.get("name", "TBA")
                venue_address = venue_info.get("full_address", "")
                
                # Determine category from event data or venue type
                category = self._determine_category(event_data, venue_info)
                
                # Extract pricing information
                ticket_links = event_data.get("ticket_links", [])
                price_min = None
                price_max = None
                currency = "USD"
                
                # OpenWeb Ninja doesn't provide direct pricing, 
                # so we'll leave it as None or try to parse from description
                
                # Get event URL
                event_url = event_data.get("link") or ""
                
                # Get image
                image_url = event_data.get("thumbnail", "")
                
                # Create EventInfo object
                event_info = EventInfo(
                    name=name,
                    date=date_str,
                    time=time_str,
                    venue=venue_name,
                    address=venue_address,
                    category=category,
                    price_min=price_min,
                    price_max=price_max,
                    currency=currency,
                    description=description,
                    url=event_url,
                    image_url=image_url
                )
                
                events.append(event_info)
                
            except Exception as e:
                logger.error(f"Error parsing event data: {str(e)}")
                continue
        
        return events
    
    def _determine_category(self, event_data: Dict, venue_info: Dict) -> str:
        """Determine event category based on venue type and event name"""
        name = event_data.get("name", "").lower()
        venue_subtypes = venue_info.get("subtypes", [])
        
        # Check venue types first
        if "movie_theater" in venue_subtypes:
            return "film"
        elif "sports_club" in venue_subtypes or "stadium" in venue_subtypes:
            return "sports"
        elif "night_club" in venue_subtypes or "bar" in venue_subtypes:
            return "music"
        elif "museum" in venue_subtypes or "art_gallery" in venue_subtypes:
            return "arts"
        elif "theater" in venue_subtypes:
            return "theatre"
        elif "restaurant" in venue_subtypes:
            return "food"
        
        # Check event name for keywords
        if any(word in name for word in ["concert", "music", "band", "singer", "dj"]):
            return "music"
        elif any(word in name for word in ["sport", "match", "game", "championship", "tournament"]):
            return "sports"
        elif any(word in name for word in ["art", "gallery", "exhibition", "museum"]):
            return "arts"
        elif any(word in name for word in ["theater", "theatre", "play", "drama"]):
            return "theatre"
        elif any(word in name for word in ["comedy", "comedian", "stand-up"]):
            return "comedy"
        elif any(word in name for word in ["festival", "fair", "celebration"]):
            return "miscellaneous"
        elif any(word in name for word in ["food", "wine", "dining", "restaurant"]):
            return "food"
        elif any(word in name for word in ["family", "kids", "children"]):
            return "family"
        elif any(word in name for word in ["business", "conference", "seminar", "workshop"]):
            return "business"
        elif any(word in name for word in ["film", "movie", "cinema", "screening"]):
            return "film"
        
        return "miscellaneous"
    
    def _filter_events(
        self, 
        events: List[EventInfo], 
        start_date: str, 
        end_date: str, 
        categories: List[str] = None
    ) -> List[EventInfo]:
        """Filter events by date range and categories"""
        filtered = []
        
        try:
            start_dt = datetime.fromisoformat(start_date).date()
            end_dt = datetime.fromisoformat(end_date).date()
        except:
            # If date parsing fails, return all events
            return events
        
        for event in events:
            # Filter by date
            if event.date:
                try:
                    event_date = datetime.fromisoformat(event.date).date()
                    if not (start_dt <= event_date <= end_dt):
                        continue
                except:
                    continue
            
            # Filter by categories
            if categories and event.category.lower() not in [cat.lower() for cat in categories]:
                continue
            
            filtered.append(event)
        
        return filtered
    
    async def get_events_for_dates(
        self, 
        location: str, 
        dates: List[str],
        categories: List[str] = None
    ) -> List[EventInfo]:
        """Get events for specific dates"""
        if not dates:
            return []
        
        # Sort dates to get range
        sorted_dates = sorted(dates)
        start_date = sorted_dates[0]
        end_date = sorted_dates[-1]
        
        # Get all events in the date range
        all_events = await self.search_events(
            location=location,
            start_date=start_date,
            end_date=end_date,
            categories=categories,
            size=50  # Get more events to filter
        )
        
        # Filter events that fall on the specific dates
        filtered_events = []
        target_dates = set(dates)
        
        for event in all_events:
            if event.date in target_dates:
                filtered_events.append(event)
        
        return filtered_events
    
    async def get_popular_events(
        self, 
        location: str, 
        days_ahead: int = 30,
        limit: int = 10
    ) -> List[EventInfo]:
        """Get popular upcoming events in a location"""
        start_date = datetime.now().date().isoformat()
        end_date = (datetime.now().date() + timedelta(days=days_ahead)).isoformat()
        
        events = await self.search_events(
            location=location,
            start_date=start_date,
            end_date=end_date,
            size=limit
        )
        
        return events
    
    async def search_events_by_category(
        self,
        location: str,
        category: str,
        start_date: str,
        end_date: str,
        limit: int = 20
    ) -> List[EventInfo]:
        """Search events by specific category"""
        return await self.search_events(
            location=location,
            start_date=start_date,
            end_date=end_date,
            categories=[category],
            size=limit
        )
    
    async def get_event_details(self, event_id: str) -> Optional[EventInfo]:
        """Get detailed information about a specific event"""
        if not self.api_key:
            logger.warning("OpenWeb Ninja API key not configured")
            return None
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                params = {"event_id": event_id}
                headers = {
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json"
                }
                
                response = await client.get(
                    f"{self.base_url}/event-details", 
                    params=params, 
                    headers=headers
                )
                response.raise_for_status()
                
                data = response.json()
                if data.get("status") == "OK" and data.get("data"):
                    event_data = data["data"]
                    events = self._parse_openweb_events({"status": "OK", "data": [event_data]})
                    return events[0] if events else None
                
                return None
                
        except Exception as e:
            logger.error(f"Failed to get event details: {str(e)}")
            return None
    
    async def search_events_with_query(
        self,
        query: str,
        location: str = "",
        date_filter: str = "any",
        is_virtual: bool = False,
        limit: int = 20
    ) -> List[EventInfo]:
        """Search events with a custom query"""
        if not self.api_key:
            logger.warning("OpenWeb Ninja API key not configured, using fallback data")
            return []
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Build search query
                search_query = query
                if location:
                    search_query = f"{query} in {location}"
                
                params = {
                    "query": search_query,
                    "date": date_filter,
                    "is_virtual": is_virtual,
                    "start": 0
                }
                
                headers = {
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json"
                }
                
                response = await client.get(self.base_url, params=params, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                events = self._parse_openweb_events(data)
                
                return events[:limit]
                
        except Exception as e:
            logger.error(f"Failed to search events with query: {str(e)}")
            return []
    
    async def _create_fallback_events(
        self, 
        location: str, 
        start_date: str, 
        end_date: str
    ) -> List[EventInfo]:
        """Create fallback event data when API is unavailable"""
        fallback_events = [
            EventInfo(
                name=f"Local Music Festival - {location}",
                date=start_date,
                time="19:00",
                venue=f"Central Park, {location}",
                address=f"Main Street, {location}",
                category="music",
                price_min=25.0,
                price_max=75.0,
                currency="USD",
                description="Annual local music festival featuring various artists",
                url="",
                image_url=""
            ),
            EventInfo(
                name="Art Gallery Opening",
                date=start_date,
                time="18:00",
                venue=f"Modern Art Gallery, {location}",
                address=f"Art District, {location}",
                category="arts",
                price_min=0.0,
                price_max=15.0,
                currency="USD",
                description="Contemporary art exhibition opening",
                url="",
                image_url=""
            ),
            EventInfo(
                name="Food & Wine Festival",
                date=end_date if start_date != end_date else start_date,
                time="12:00",
                venue=f"Convention Center, {location}",
                address=f"Downtown, {location}",
                category="food",
                price_min=30.0,
                price_max=85.0,
                currency="USD",
                description="Local food and wine tasting festival",
                url="",
                image_url=""
            )
        ]
        
        logger.info(f"Using fallback events for {location}")
        return fallback_events
    
    def get_event_categories(self) -> List[str]:
        """Get available event categories"""
        return [
            "music",
            "sports", 
            "arts",
            "theatre",
            "comedy",
            "family",
            "business",
            "food",
            "film",
            "miscellaneous"
        ]
    
    def get_date_filters(self) -> List[str]:
        """Get available OpenWeb Ninja date filters"""
        return [
            "any",
            "today",
            "tomorrow",
            "week",
            "weekend",
            "next_week",
            "month",
            "next_month"
        ]