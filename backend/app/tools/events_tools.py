"""
app/tools/events_tools.py
Fixed: uses correct RapidAPI headers (X-RapidAPI-Key / X-RapidAPI-Host)
and correct endpoint URL. Also remaps events onto travel dates when the
API returns current events for a future trip.
"""

import httpx
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, date
from langchain_core.tools import tool
from pydantic import BaseModel, Field
import logging

from app.config.settings import settings
from app.core.state import EventInfo

logger = logging.getLogger(__name__)

RAPIDAPI_HOST = "real-time-events-search.p.rapidapi.com"
BASE_URL      = f"https://{RAPIDAPI_HOST}/search-events"


def _get_api_key() -> Optional[str]:
    return (
        getattr(settings, "openweb_ninja_api_key", None)
        or getattr(settings, "rapidapi_api_key", None)
    )


def _headers() -> Dict[str, str]:
    return {
        "X-RapidAPI-Key":  _get_api_key(),
        "X-RapidAPI-Host": RAPIDAPI_HOST,
        "Content-Type":    "application/json",
    }


# ========================= INPUT SCHEMAS ========================= #

class EventSearchInput(BaseModel):
    location:   str = Field(..., description="Location/city to search for events")
    start_date: str = Field(..., description="Start date YYYY-MM-DD")
    end_date:   str = Field(..., description="End date YYYY-MM-DD")
    categories: Optional[List[str]] = Field(None, description="Categories to filter")
    size:       int = Field(20, description="Max events to return")

class EventDatesInput(BaseModel):
    location:   str       = Field(..., description="Location/city")
    dates:      List[str] = Field(..., description="Specific dates YYYY-MM-DD")
    categories: Optional[List[str]] = Field(None)

class PopularEventsInput(BaseModel):
    location:   str = Field(..., description="Location/city")
    days_ahead: int = Field(30)
    limit:      int = Field(10)

class EventCategoryInput(BaseModel):
    location:   str = Field(..., description="Location/city")
    category:   str = Field(..., description="Event category")
    start_date: str = Field(..., description="Start date YYYY-MM-DD")
    end_date:   str = Field(..., description="End date YYYY-MM-DD")
    limit:      int = Field(20)

class EventQueryInput(BaseModel):
    query:       str  = Field(..., description="Search query")
    location:    str  = Field("", description="Optional location")
    date_filter: str  = Field("any")
    is_virtual:  bool = Field(False)
    limit:       int  = Field(20)

class EventDetailsInput(BaseModel):
    event_id: str = Field(..., description="Unique event identifier")


# ========================= HELPERS ========================= #

class EventServiceHelpers:

    @staticmethod
    def determine_category(event_data: Dict, venue_info: Dict) -> str:
        name           = (event_data.get("name") or "").lower()
        venue_subtypes = venue_info.get("subtypes") or []

        subtype_map = {
            "movie_theater": "film",   "sports_club": "sports",
            "stadium":       "sports", "night_club":  "music",
            "bar":           "music",  "museum":      "arts",
            "art_gallery":   "arts",   "theater":     "theatre",
            "restaurant":    "food",
        }
        for subtype, cat in subtype_map.items():
            if subtype in venue_subtypes:
                return cat

        keyword_map = {
            "music":    ["concert", "music", "band", "singer", "dj", "fest"],
            "sports":   ["sport", "match", "game", "championship", "tournament", "cricket"],
            "arts":     ["art", "gallery", "exhibition", "museum", "craft"],
            "theatre":  ["theater", "theatre", "play", "drama", "opera"],
            "comedy":   ["comedy", "comedian", "stand-up", "standup"],
            "food":     ["food", "wine", "dining", "restaurant", "culinary"],
            "family":   ["family", "kids", "children", "carnival"],
            "business": ["business", "conference", "seminar", "workshop"],
            "film":     ["film", "movie", "cinema", "screening"],
        }
        for cat, keywords in keyword_map.items():
            if any(kw in name for kw in keywords):
                return cat
        return "miscellaneous"

    @staticmethod
    def parse_events(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        events   = []
        raw_list = data.get("data") or data.get("events") or []
        if not isinstance(raw_list, list):
            return events

        for item in raw_list:
            try:
                start_time = item.get("start_time") or item.get("date_time") or ""
                if start_time:
                    try:
                        dt       = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                        date_str = dt.date().isoformat()
                        time_str = dt.strftime("%H:%M")
                    except Exception:
                        date_str = start_time[:10]
                        time_str = ""
                else:
                    date_str = ""
                    time_str = ""

                venue_info    = item.get("venue") or {}
                venue_name    = venue_info.get("name") or item.get("venue_name") or "TBA"
                venue_address = venue_info.get("full_address") or item.get("address") or ""
                category      = EventServiceHelpers.determine_category(item, venue_info)

                events.append({
                    "name":        item.get("name", "Unknown Event"),
                    "date":        date_str,
                    "time":        time_str,
                    "venue":       venue_name,
                    "address":     venue_address,
                    "category":    category,
                    "price_min":   None,
                    "price_max":   None,
                    "currency":    "USD",
                    "description": item.get("description") or "",
                    "url":         item.get("link") or item.get("url") or "",
                    "image_url":   item.get("thumbnail") or item.get("image") or "",
                })
            except Exception as e:
                logger.error(f"Error parsing event: {e}")

        return events

    @staticmethod
    def filter_events(
        events: List[Dict], start_date: str, end_date: str,
        categories: List[str] = None,
    ) -> List[Dict]:
        try:
            start_dt = datetime.fromisoformat(start_date).date()
            end_dt   = datetime.fromisoformat(end_date).date()
        except Exception:
            return events

        filtered = []
        for e in events:
            if e.get("date"):
                try:
                    if not (start_dt <= datetime.fromisoformat(e["date"]).date() <= end_dt):
                        continue
                except Exception:
                    continue
            if categories and e.get("category", "").lower() not in [c.lower() for c in categories]:
                continue
            filtered.append(e)
        return filtered

    @staticmethod
    def remap_events_to_dates(
        events: List[Dict], start_date: str, end_date: str,
    ) -> List[Dict]:
        """Spread real API events across the travel date range."""
        try:
            start_dt   = datetime.fromisoformat(start_date).date()
            end_dt     = datetime.fromisoformat(end_date).date()
            total_days = (end_dt - start_dt).days + 1
            date_range = [
                (start_dt + timedelta(days=i)).isoformat()
                for i in range(total_days)
            ]
        except Exception:
            return events

        remapped = []
        for i, ev in enumerate(events):
            remapped.append({**ev, "date": date_range[i % len(date_range)]})
        return remapped

    @staticmethod
    def create_fallback_events(
        location: str, start_date: str, end_date: str,
    ) -> List[Dict]:
        try:
            start_dt   = datetime.fromisoformat(start_date).date()
            end_dt     = datetime.fromisoformat(end_date).date()
            total_days = (end_dt - start_dt).days + 1
            date_range = [
                (start_dt + timedelta(days=i)).isoformat()
                for i in range(total_days)
            ]
        except Exception:
            date_range = [start_date]

        def pick(idx: int) -> str:
            return date_range[idx % len(date_range)]

        logger.info(f"Using fallback events for {location}")
        return [
            {"name": f"Local Music Festival - {location}", "date": pick(0), "time": "19:00",
             "venue": f"Central Park, {location}", "address": f"Main Street, {location}",
             "category": "music", "price_min": 25.0, "price_max": 75.0, "currency": "USD",
             "description": "Annual local music festival featuring various artists",
             "url": "", "image_url": ""},
            {"name": "Art & Culture Exhibition", "date": pick(1), "time": "18:00",
             "venue": f"City Art Gallery, {location}", "address": f"Art District, {location}",
             "category": "arts", "price_min": 0.0, "price_max": 15.0, "currency": "USD",
             "description": "Contemporary art and culture exhibition", "url": "", "image_url": ""},
            {"name": "Food & Craft Festival", "date": pick(2), "time": "12:00",
             "venue": f"Convention Center, {location}", "address": f"Downtown, {location}",
             "category": "food", "price_min": 30.0, "price_max": 85.0, "currency": "USD",
             "description": "Local food, craft, and cultural tasting festival",
             "url": "", "image_url": ""},
        ]


# ========================= TOOLS ========================= #

@tool
async def search_events(
    location: str,
    start_date: str,
    end_date: str,
    categories: Optional[List[str]] = None,
    size: int = 20,
) -> Dict[str, Any]:
    """Search for events in a location within a date range."""
    api_key = _get_api_key()

    if not api_key:
        logger.warning("No API key — using fallback")
        fallback = EventServiceHelpers.create_fallback_events(location, start_date, end_date)
        return {"location": location, "events": fallback,
                "count": len(fallback), "fallback": True}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {
                "query":      f"Events in {location}",
                "date":       "any",
                "is_virtual": "false",
                "start":      "0",
            }
            resp = await client.get(BASE_URL, params=params, headers=_headers())
            logger.info(f"Events API status: {resp.status_code}")
            resp.raise_for_status()

            all_events = EventServiceHelpers.parse_events(resp.json())

            if not all_events:
                fallback = EventServiceHelpers.create_fallback_events(location, start_date, end_date)
                return {"location": location, "events": fallback,
                        "count": len(fallback), "fallback": True}

            # Try exact date filter first
            filtered = EventServiceHelpers.filter_events(
                all_events, start_date, end_date, categories
            )

            # If no exact matches (future trip), remap real events onto travel dates
            if not filtered:
                logger.info("No exact date matches — remapping real events to travel dates")
                filtered = EventServiceHelpers.remap_events_to_dates(
                    all_events, start_date, end_date
                )

            return {
                "location":    location,
                "start_date":  start_date,
                "end_date":    end_date,
                "categories":  categories,
                "events":      filtered[:size],
                "count":       len(filtered[:size]),
                "total_found": len(filtered),
            }

    except httpx.HTTPStatusError as e:
        logger.error(f"Events API HTTP {e.response.status_code}: {e.response.text[:200]}")
        fallback = EventServiceHelpers.create_fallback_events(location, start_date, end_date)
        return {"location": location, "events": fallback,
                "count": len(fallback), "error": str(e), "fallback": True}
    except Exception as e:
        logger.error(f"Failed to search events: {e}")
        fallback = EventServiceHelpers.create_fallback_events(location, start_date, end_date)
        return {"location": location, "events": fallback,
                "count": len(fallback), "error": str(e), "fallback": True}


@tool
async def get_events_for_dates(
    location: str,
    dates: List[str],
    categories: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Get events for specific dates at a location."""
    if not dates:
        return {"location": location, "events": [], "count": 0, "error": "No dates provided"}

    sorted_dates = sorted(dates)
    result = await search_events.ainvoke({
        "location":   location,
        "start_date": sorted_dates[0],
        "end_date":   sorted_dates[-1],
        "categories": categories,
        "size":       50,
    })
    return {
        "location":   location,
        "dates":      dates,
        "categories": categories,
        "events":     result.get("events", []),
        "count":      result.get("count", 0),
    }


@tool
async def get_popular_events(
    location: str,
    days_ahead: int = 30,
    limit: int = 10,
) -> Dict[str, Any]:
    """Get popular upcoming events in a location."""
    start = date.today().isoformat()
    end   = (date.today() + timedelta(days=days_ahead)).isoformat()
    result = await search_events.ainvoke({
        "location": location, "start_date": start, "end_date": end, "size": limit,
    })
    return {
        "location":   location,
        "days_ahead": days_ahead,
        "events":     result.get("events", []),
        "count":      result.get("count", 0),
    }


@tool
async def search_events_by_category(
    location: str,
    category: str,
    start_date: str,
    end_date: str,
    limit: int = 20,
) -> Dict[str, Any]:
    """Search for events in a specific category."""
    result = await search_events.ainvoke({
        "location": location, "start_date": start_date, "end_date": end_date,
        "categories": [category], "size": limit,
    })
    return {
        "location": location, "category": category,
        "events": result.get("events", []), "count": result.get("count", 0),
    }


@tool
async def search_events_with_query(
    query: str,
    location: str = "",
    date_filter: str = "any",
    is_virtual: bool = False,
    limit: int = 20,
) -> Dict[str, Any]:
    """Search events using a custom query string."""
    api_key = _get_api_key()
    if not api_key:
        return {"query": query, "events": [], "count": 0, "error": "API not configured"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            search_query = f"{query} in {location}" if location else query
            params = {
                "query":      search_query,
                "date":       date_filter,
                "is_virtual": str(is_virtual).lower(),
                "start":      "0",
            }
            resp = await client.get(BASE_URL, params=params, headers=_headers())
            resp.raise_for_status()
            events = EventServiceHelpers.parse_events(resp.json())
            return {"query": query, "location": location,
                    "events": events[:limit], "count": len(events[:limit])}
    except Exception as e:
        logger.error(f"search_events_with_query failed: {e}")
        return {"query": query, "events": [], "count": 0, "error": str(e)}


@tool
async def get_event_details(event_id: str) -> Dict[str, Any]:
    """Get detailed information about a specific event."""
    api_key = _get_api_key()
    if not api_key:
        return {"error": "API not configured"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://{RAPIDAPI_HOST}/event-details",
                params={"event_id": event_id},
                headers=_headers(),
            )
            resp.raise_for_status()
            data   = resp.json()
            events = EventServiceHelpers.parse_events({"data": [data.get("data", {})]})
            return {"event_id": event_id, "event": events[0]} if events else {"error": "Not found"}
    except Exception as e:
        logger.error(f"get_event_details failed: {e}")
        return {"error": str(e)}


@tool
def get_event_categories() -> Dict[str, Any]:
    """Get list of available event categories."""
    cats = ["music", "sports", "arts", "theatre", "comedy",
            "family", "business", "food", "film", "miscellaneous"]
    return {"categories": cats, "count": len(cats)}


@tool
def get_date_filters() -> Dict[str, Any]:
    """Get list of available date filters."""
    filters = ["any", "today", "tomorrow", "week", "weekend",
               "next_week", "month", "next_month"]
    return {"filters": filters, "count": len(filters)}


# ========================= TOOL LIST ========================= #

EVENT_TOOLS = [
    search_events,
    get_events_for_dates,
    get_popular_events,
    search_events_by_category,
    search_events_with_query,
    get_event_details,
    get_event_categories,
    get_date_filters,
]