"""
Itinerary Tools - LLM-driven via Groq, no hardcoded city data.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from langchain_core.tools import tool
import logging
import re
import json
import os
import httpx

logger = logging.getLogger(__name__)


# ========================= DATE EXPANSION ========================= #

def expand_travel_dates(travel_dates: List[str]) -> List[str]:
    """
    Expand date range strings into individual dates.
    ["2026-07-15 to 2026-07-18"] -> ["2026-07-15","2026-07-16","2026-07-17","2026-07-18"]
    """
    expanded = []
    for d in travel_dates:
        d = d.strip()
        range_match = re.match(
            r'(\d{4}-\d{2}-\d{2})\s*(?:to|-)\s*(\d{4}-\d{2}-\d{2})', d
        )
        if range_match:
            start = datetime.strptime(range_match.group(1), "%Y-%m-%d")
            end = datetime.strptime(range_match.group(2), "%Y-%m-%d")
            cur = start
            while cur <= end:
                expanded.append(cur.strftime("%Y-%m-%d"))
                cur += timedelta(days=1)
        else:
            expanded.append(d)
    return expanded if expanded else travel_dates


# ========================= GROQ LLM CALL ========================= #

async def generate_llm_itinerary(
    destination: str,
    origin: str,
    travel_dates: List[str],
    travelers_count: int,
    budget_total: Optional[float],
    budget_range: Optional[str],
    user_preferences: Optional[str],
    weather_data: Optional[List[Dict]],
    events_data: Optional[List[Dict]],
    maps_data: Optional[Dict],
    budget_data: Optional[Dict],
) -> List[Dict]:
    """
    Call Groq API to generate a fully personalized day-by-day itinerary.
    Returns a list of day dicts: [{day, date, activities, notes, estimated_cost}]
    """
    total_days = len(travel_dates)
    daily_budget = round(budget_total / total_days, 0) if budget_total and total_days else 2000

    # ── Format weather ────────────────────────────────────────────────────────
    weather_text = ""
    if weather_data:
        for i, w in enumerate(weather_data[:total_days]):
            if isinstance(w, dict):
                weather_text += (
                    f"  Day {i+1} ({travel_dates[i] if i < len(travel_dates) else ''}): "
                    f"{w.get('description', 'N/A')}, "
                    f"{w.get('temperature_min', '?')}-{w.get('temperature_max', '?')}C, "
                    f"rain {w.get('precipitation_chance', '?')}%\n"
                )

    # ── Format events ─────────────────────────────────────────────────────────
    events_text = ""
    if events_data:
        for e in (events_data[:5] if isinstance(events_data, list) else []):
            if isinstance(e, dict):
                events_text += (
                    f"  - {e.get('name', 'Event')} on "
                    f"{e.get('date', 'TBA')} at {e.get('venue', 'TBA')}\n"
                )

    # ── Format transport ──────────────────────────────────────────────────────
    transport_text = ""
    if maps_data and isinstance(maps_data, dict):
        primary = maps_data.get("primary_route", {})
        if isinstance(primary, dict):
            transport_text = (
                f"  {primary.get('transport_mode', 'N/A')}: "
                f"{primary.get('distance', '?')}, {primary.get('duration', '?')}"
            )
        alts = maps_data.get("alternative_routes", {})
        if isinstance(alts, dict):
            for mode, info in alts.items():
                if isinstance(info, dict):
                    transport_text += (
                        f"\n  {mode}: {info.get('distance','?')}, {info.get('duration','?')}"
                    )

    # ── Format budget breakdown ───────────────────────────────────────────────
    budget_text = ""
    if budget_data and isinstance(budget_data, dict):
        budget_text = (
            f"  Transport: INR {budget_data.get('transportation', 0):,.0f}, "
            f"Stay: INR {budget_data.get('accommodation', 0):,.0f}, "
            f"Food: INR {budget_data.get('food', 0):,.0f}, "
            f"Activities: INR {budget_data.get('activities', 0):,.0f}"
        )

    dates_str = ", ".join(travel_dates)

    prompt = f"""You are an expert Indian travel planner with deep local knowledge. 
Create a detailed, realistic, personalized day-by-day itinerary.

TRIP DETAILS:
- Destination: {destination}
- Origin: {origin}
- Dates: {dates_str} ({total_days} days)
- Travelers: {travelers_count} adults
- Budget: {budget_range or 'moderate'} (~INR {budget_total or 'unspecified'} total, ~INR {daily_budget}/day)
- Preferences: {user_preferences or 'historical places, local markets, authentic local food, relaxed pace'}

WEATHER FORECAST:
{weather_text or '  Not available'}

LOCAL EVENTS DURING TRIP:
{events_text or '  No events data'}

TRANSPORT OPTIONS FROM {origin.upper()} TO {destination.upper()}:
{transport_text or '  Not available'}

BUDGET BREAKDOWN:
{budget_text or '  Not available'}

RULES:
1. Respond ONLY with a valid JSON array — no markdown, no explanation, no extra text
2. Exactly {total_days} objects in the array, one per date
3. Dates must be exactly in this order: {dates_str}
4. Each day has 3-5 activities max (relaxed pace, not overly packed)
5. Use SPECIFIC real place names, restaurant names, hotel names
6. Include timing (9:00 AM, 1:00 PM etc) and entry fees where relevant
7. Day 1: include arrival logistics and hotel recommendation near attractions
8. Last day: include checkout and departure logistics
9. Include monsoon/weather tips in notes if applicable
10. estimated_cost is a number (INR) per day for both travelers combined

Respond with ONLY this JSON structure:
[
  {{
    "day": 1,
    "date": "{travel_dates[0]}",
    "activities": [
      "9:00 AM - Arrive at ...",
      "11:00 AM - Check in to ...",
      "1:00 PM - Lunch at ...",
      "3:00 PM - Visit ...",
      "7:00 PM - Dinner at ..."
    ],
    "notes": "Practical tip or weather note for this day",
    "estimated_cost": {int(daily_budget)}
  }}
]"""

    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_api_key:
        logger.warning("GROQ_API_KEY not set, using fallback itinerary")
        return _fallback_itinerary(destination, travel_dates, daily_budget)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "max_tokens": 4096,
                    "temperature": 0.7,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a travel planning expert. Always respond with valid JSON only, no markdown, no explanation."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                },
            )

        if response.status_code != 200:
            logger.error(f"Groq API error: {response.status_code} {response.text[:300]}")
            return _fallback_itinerary(destination, travel_dates, daily_budget)

        raw = response.json()["choices"][0]["message"]["content"].strip()

        # Strip accidental markdown fences
        raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
        raw = raw.strip()

        days = json.loads(raw)

        if not isinstance(days, list) or len(days) == 0:
            raise ValueError(f"Invalid response shape: {type(days)}")

        # Ensure correct number of days
        if len(days) != total_days:
            logger.warning(
                f"Groq returned {len(days)} days, expected {total_days}. "
                f"Patching with fallback for missing days."
            )
            # Patch missing days if short
            while len(days) < total_days:
                i = len(days)
                days.append(_fallback_day(destination, i + 1, travel_dates[i], daily_budget))

        logger.info(f"Groq itinerary: {len(days)} days for {destination}")
        return days

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error from Groq: {e}\nRaw: {raw[:500]}")
        return _fallback_itinerary(destination, travel_dates, daily_budget)
    except Exception as e:
        logger.error(f"Groq itinerary generation failed: {e}")
        return _fallback_itinerary(destination, travel_dates, daily_budget)


def _fallback_day(destination: str, day_num: int, date: str, daily_budget: float) -> Dict:
    return {
        "day": day_num,
        "date": date,
        "activities": [f"Explore {destination} - Day {day_num} (regenerate for full plan)"],
        "notes": "Could not generate detailed plan. Please retry.",
        "estimated_cost": int(daily_budget),
    }


def _fallback_itinerary(
    destination: str,
    travel_dates: List[str],
    daily_budget: float
) -> List[Dict]:
    return [
        _fallback_day(destination, i + 1, date, daily_budget)
        for i, date in enumerate(travel_dates)
    ]


# ========================= LANGCHAIN TOOLS ========================= #

@tool
def get_destination_info(destination: str) -> Dict[str, Any]:
    """Get information about a destination.

    Args:
        destination: Destination city or location name

    Returns:
        Basic destination info
    """
    return {
        "destination": destination,
        "note": "Full personalized details will be generated in the itinerary"
    }


@tool
def create_daily_itinerary(
    destination: str,
    travel_dates: List[str],
    weather_data: Optional[List[Dict[str, Any]]] = None,
    budget_total: Optional[float] = None,
    travelers_count: int = 1
) -> Dict[str, Any]:
    """Create a complete day-by-day itinerary for a trip using LLM.

    Args:
        destination: Destination city or location
        travel_dates: List of travel dates in YYYY-MM-DD format
        weather_data: Optional weather data for each day
        budget_total: Optional total budget in INR
        travelers_count: Number of travelers

    Returns:
        Dictionary with day-by-day itinerary
    """
    import asyncio

    # Expand date ranges
    expanded_dates = expand_travel_dates(travel_dates)

    logger.info(
        f"create_daily_itinerary tool: raw={travel_dates} -> "
        f"expanded={expanded_dates} ({len(expanded_dates)} days)"
    )

    total_days = len(expanded_dates)
    daily_budget = round(budget_total / total_days, 0) if budget_total and total_days else 2000

    # Run async LLM call from sync context
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    generate_llm_itinerary(
                        destination=destination,
                        origin="",
                        travel_dates=expanded_dates,
                        travelers_count=travelers_count,
                        budget_total=budget_total,
                        budget_range=None,
                        user_preferences=None,
                        weather_data=weather_data,
                        events_data=None,
                        maps_data=None,
                        budget_data=None,
                    )
                )
                days = future.result(timeout=90)
        else:
            days = loop.run_until_complete(
                generate_llm_itinerary(
                    destination=destination,
                    origin="",
                    travel_dates=expanded_dates,
                    travelers_count=travelers_count,
                    budget_total=budget_total,
                    budget_range=None,
                    user_preferences=None,
                    weather_data=weather_data,
                    events_data=None,
                    maps_data=None,
                    budget_data=None,
                )
            )
    except Exception as e:
        logger.error(f"Tool LLM call failed: {e}")
        days = _fallback_itinerary(destination, expanded_dates, daily_budget)

    return {
        "destination": destination,
        "travelers_count": travelers_count,
        "total_days": total_days,
        "start_date": expanded_dates[0],
        "end_date": expanded_dates[-1],
        "itinerary": days,
        "total_estimated_cost": budget_total or daily_budget * total_days,
        "currency": "INR"
    }


@tool
def optimize_itinerary_by_weather(
    destination: str,
    travel_dates: List[str],
    weather_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Optimize itinerary based on weather forecasts.

    Args:
        destination: Destination city or location
        travel_dates: List of travel dates
        weather_data: Weather data for each day

    Returns:
        Weather-optimized daily recommendations
    """
    expanded_dates = expand_travel_dates(travel_dates)
    optimized_days = []

    for i, date_str in enumerate(expanded_dates):
        day_weather = weather_data[i] if i < len(weather_data) else {}
        temp_max = day_weather.get("temp_max", 25)
        precipitation = day_weather.get("precipitation_chance", 0)
        recommendations = []

        if precipitation > 70:
            recommendations.append("High rain chance - prioritize indoor attractions")
        elif precipitation > 40:
            recommendations.append("Moderate rain - keep umbrella handy")
        else:
            recommendations.append("Good weather for outdoor sightseeing")

        if temp_max > 35:
            recommendations.append("Very hot - outdoor visits before 11 AM or after 4 PM")
        elif temp_max < 15:
            recommendations.append("Cold - dress in layers")

        optimized_days.append({
            "date": date_str,
            "day": i + 1,
            "weather": {
                "temp_max": temp_max,
                "precipitation_chance": precipitation,
                "description": day_weather.get("description", "N/A")
            },
            "recommendations": recommendations
        })

    return {
        "destination": destination,
        "optimized_itinerary": optimized_days,
        "total_days": len(expanded_dates)
    }


@tool
def get_food_recommendations(destination: str) -> Dict[str, Any]:
    """Get food recommendations for a destination.

    Args:
        destination: Destination city or location

    Returns:
        Food recommendations note
    """
    return {
        "destination": destination,
        "note": "Specific restaurant recommendations will be included in the LLM-generated itinerary"
    }


@tool
def get_travel_tips(destination: str) -> Dict[str, Any]:
    """Get travel tips for a destination.

    Args:
        destination: Destination city or location

    Returns:
        Travel tips note
    """
    return {
        "destination": destination,
        "note": "Practical tips will be included per-day in the generated itinerary"
    }


@tool
def plan_single_day_activities(
    destination: str,
    day_number: int,
    total_days: int,
    weather_temp_max: Optional[float] = None,
    precipitation_chance: Optional[float] = None
) -> Dict[str, Any]:
    """Plan activities for a single day.

    Args:
        destination: Destination city
        day_number: Day number (1-based)
        total_days: Total trip days
        weather_temp_max: Max temperature
        precipitation_chance: Rain chance 0-100

    Returns:
        Activities for the day
    """
    return {
        "destination": destination,
        "day_number": day_number,
        "note": "Full day plan generated as part of complete itinerary"
    }


@tool
def get_available_destinations() -> Dict[str, Any]:
    """Get supported destinations info.

    Returns:
        Info about destination coverage
    """
    return {
        "coverage": "All destinations worldwide supported via LLM generation",
        "note": "No hardcoded city list — plans are generated fresh for every query"
    }


@tool
def estimate_time_per_attraction(
    destination: str,
    attraction_count: int = None
) -> Dict[str, Any]:
    """Estimate time needed for attractions.

    Args:
        destination: Destination city
        attraction_count: Number of attractions

    Returns:
        Time estimates
    """
    count = attraction_count or 4
    return {
        "destination": destination,
        "estimated_hours_per_attraction": 2.0,
        "recommended_daily_attractions": 3,
        "notes": "Relaxed pace recommended — quality over quantity"
    }


# ========================= TOOL LIST ========================= #

ITINERARY_TOOLS = [
    get_destination_info,
    create_daily_itinerary,
    plan_single_day_activities,
    get_food_recommendations,
    get_travel_tips,
    get_available_destinations,
    optimize_itinerary_by_weather,
    estimate_time_per_attraction,
]