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

from app.ml.attraction_database import get_attractions_for_city, has_attraction_data, filter_by_interests
from app.ml.clustering_service import cluster_attractions_by_day
from app.ml.route_optimizer import optimize_full_itinerary

logger = logging.getLogger(__name__)

async def build_optimized_route_plan(
    destination: str,
    total_days: int,
    interest_tags: list = None,
) -> dict:
    """
    Run the full clustering + TSP pipeline for a destination, using
    LIVE Google Places data (no hardcoded coordinates).

    Returns:
    {
        "available": True,
        "day_routes": [[{...attraction...}, ...], ...],  # per day, in visit order
        "stats": {"km_saved": 8.4, "total_optimized_km": 22.1, "ortools_used": True}
    }

    Returns {"available": False} if the city has fewer than 2 discoverable
    attractions or the Google Places API key is missing — caller falls
    back to letting Groq freely decide order, no crash.
    """
    from app.ml.attraction_database import get_attractions_for_city, has_attraction_data, filter_by_interests
    from app.ml.clustering_service import cluster_attractions_by_day
    from app.ml.route_optimizer import optimize_full_itinerary

    if not await has_attraction_data(destination):
        logger.info(f"[Itinerary] No discoverable attractions for '{destination}' — skipping geo-optimization")
        return {"available": False}

    attractions = await get_attractions_for_city(destination)
    attractions = filter_by_interests(attractions, interest_tags or [])

    if len(attractions) < 2:
        return {"available": False}

    cluster_days = max(1, min(total_days, len(attractions)))

    day_clusters = cluster_attractions_by_day(
        attractions, num_days=cluster_days, max_per_day=4
    )
    optimized_routes, stats = optimize_full_itinerary(day_clusters)

    logger.info(
        f"[Itinerary] Geo-optimization for {destination}: "
        f"{len(attractions)} live attractions -> {cluster_days} days, "
        f"saved {stats['km_saved']}km vs naive order"
    )

    return {
        "available":  True,
        "day_routes": optimized_routes,
        "stats":      stats,
    }


def format_route_plan_for_prompt(route_plan: dict) -> str:
    """
    Convert the optimized route plan into text for the Groq prompt,
    giving the LLM a geographic skeleton instead of letting it guess order.
    This function stays SYNC — it's pure string formatting.
    """
    if not route_plan.get("available"):
        return ""

    lines = ["PRE-OPTIMIZED GEOGRAPHIC ROUTE (live data — use this exact attraction "
              "order per day, do not reorder — only add timing, food stops, and "
              "practical details around them):"]

    for day_idx, day_attractions in enumerate(route_plan["day_routes"], start=1):
        if not day_attractions:
            continue
        names = " → ".join(a["name"] for a in day_attractions)
        lines.append(f"  Day {day_idx}: {names}")

    stats = route_plan.get("stats", {})
    if stats.get("km_saved", 0) > 0:
        lines.append(f"  (Route optimization saved approximately {stats['km_saved']} km of travel)")

    return "\n".join(lines)



# ========================= DATE EXPANSION ========================= #

def expand_travel_dates(travel_dates: List[str]) -> List[str]:
    """
    Expand date range strings into individual dates.
    ["2026-07-15 to 2026-07-18"] -> ["2026-07-15","2026-07-16","2026-07-17","2026-07-18"]
    Also handles lists of two dates representing start and end of trip:
    ["2026-07-15", "2026-07-19"] -> ["2026-07-15","2026-07-16","2026-07-17","2026-07-18","2026-07-19"]
    """
    expanded = []
    for d in travel_dates:
        d = d.strip()
        range_match = re.match(
            r'(\d{4}-\d{2}-\d{2})\s*(?:to|-)\s*(\d{4}-\d{2}-\d{2})', d
        )
        if range_match:
            try:
                start = datetime.strptime(range_match.group(1), "%Y-%m-%d")
                end = datetime.strptime(range_match.group(2), "%Y-%m-%d")
                cur = start
                while cur <= end:
                    expanded.append(cur.strftime("%Y-%m-%d"))
                    cur += timedelta(days=1)
            except ValueError:
                expanded.append(d)
        else:
            expanded.append(d)

    # Handle list of two dates [start_date, end_date]
    if len(expanded) == 2:
        try:
            start = datetime.strptime(expanded[0], "%Y-%m-%d")
            end = datetime.strptime(expanded[1], "%Y-%m-%d")
            if start <= end:
                all_dates = []
                cur = start
                while cur <= end:
                    all_dates.append(cur.strftime("%Y-%m-%d"))
                    cur += timedelta(days=1)
                return all_dates
        except ValueError:
            pass

    return expanded if expanded else travel_dates


# ========================= GROQ LLM CALL =========================

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
    groq_api_key: Optional[str] = None,  # ← accept key directly from agent
    rag_context: Optional[str] = None,    # ← RAG tips from Pinecone
) -> tuple:
    """
    Call Groq API to generate a fully personalized day-by-day itinerary.
    Returns a tuple: (list of day dicts, route_plan dict)
    """
    total_days = len(travel_dates)
    daily_budget = round(budget_total / total_days, 0) if budget_total and total_days else 2000

    # ── NEW: Geographic clustering + TSP optimization (live Google Places) ──
    interest_list = []
    if user_preferences:
        interest_list = [w.strip().lower() for w in user_preferences.replace(".", ",").split(",") if w.strip()]

    route_plan = await build_optimized_route_plan(destination, total_days, interest_list)
    route_plan_text = format_route_plan_for_prompt(route_plan)

    # ── Resolve API key: prefer passed-in key, fall back to env ──────────────
    api_key = groq_api_key or os.environ.get("GROQ_API_KEY", "")

    logger.info(f"[Itinerary] generate_llm_itinerary called for {destination} ({total_days} days)")
    logger.info(f"[Itinerary] API key present: {bool(api_key)}, prefix: {api_key[:8] if api_key else 'NONE'}")

    if not api_key:
        logger.error("[Itinerary] No Groq API key available — check settings.groq_api_key or GROQ_API_KEY env var")
        return _fallback_itinerary(destination, travel_dates, daily_budget), route_plan

    # ── Format weather ────────────────────────────────────────────────────────
    weather_text = ""
    if weather_data:
        for i, w in enumerate(weather_data[:total_days]):
            if isinstance(w, dict):
                tmin = w.get('temperature_min') or w.get('temp_min', '?')
                tmax = w.get('temperature_max') or w.get('temp_max', '?')
                weather_text += (
                    f"  Day {i+1} ({travel_dates[i] if i < len(travel_dates) else ''}): "
                    f"{w.get('description', 'N/A')}, {tmin}-{tmax}C, "
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
        if isinstance(primary, dict) and (primary.get("distance") or primary.get("duration")):
            transport_text = (
                f"  {primary.get('transport_mode', 'driving')}: "
                f"{primary.get('distance', '?')}, {primary.get('duration', '?')}"
            )
        alts = maps_data.get("alternative_routes", {})
        if isinstance(alts, dict):
            for mode, info in alts.items():
                if isinstance(info, dict) and (info.get("distance") or info.get("duration")):
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
- Budget: {budget_range or 'moderate'} (~INR {int(budget_total) if budget_total else 'unspecified'} total, ~INR {int(daily_budget)}/day)
- Preferences: {user_preferences or 'historical places, local markets, authentic local food, relaxed pace'}

WEATHER FORECAST:
{weather_text or '  Not available'}

LOCAL EVENTS DURING TRIP:
{events_text or '  No events data'}

TRANSPORT OPTIONS FROM {origin.upper()} TO {destination.upper()}:
{transport_text or '  Not available'}

BUDGET BREAKDOWN:
{budget_text or '  Not available'}

{route_plan_text}

VERIFIED LOCAL GUIDELINES:
{rag_context or '  None available — use your own knowledge'}

RULES:
1. Respond ONLY with a valid JSON array — no markdown, no explanation, no extra text
2. Exactly {total_days} objects in the array, one per date
3. Dates must be exactly in this order: {dates_str}
4. Each day's "activities" list must be organized into time blocks, in this order:
   Morning, Midday, Afternoon, Late Afternoon / Sunset, Evening
   (skip a block only if truly nothing fits)
5. Each time block gets 1-3 bullet points (vary the count — Morning and Evening usually
   get 2-3, Midday often just 1 major stop)
6. Only the FIRST bullet point of a time block should start with the time block prefix (e.g. "Morning: **[Place Name]** — [vibe], [tip]").
   Any subsequent bullet points in that same time block MUST NOT repeat the label, and instead must start with "- **[Place Name]** — [vibe], [tip]".
7. Use SPECIFIC real place names, restaurant names, hotel names — never invent generic ones
8. Where relevant, offer a genuine alternative ("Or if you'd rather X, Y is also great")
9. Add real practical caveats where they matter (e.g. "book ahead", "only open Fridays", entry fees)
10. No generic filler like "explore local culture" — name actual dishes, views, specific details
11. Day 1: first Morning bullet covers arrival logistics and hotel check-in
12. Last day: last Evening bullet covers checkout/departure logistics
13. Include monsoon/weather tips in notes if applicable
14. estimated_cost is a number (INR) per day for both travelers combined

Respond with ONLY this JSON structure:
[
  {{
    "day": 1,
    "date": "{travel_dates[0]}",
    "activities": [
      "Morning: **[Place Name]** — [vibe], [tip]",
      "- **[Place Name]** — [vibe], [tip]",
      "Midday: **[Place Name]** — [vibe], [tip]",
      "Afternoon: **[Place Name]** — [vibe], [tip]",
      "- **[Place Name]** — [vibe], [tip]",
      "Late Afternoon / Sunset: **[Place Name]** — [vibe], [tip]",
      "Evening: **[Place Name]** — [vibe], [tip]",
      "- **[Place Name]** — [vibe], [tip]"
    ],
    "notes": "Practical tip or weather note for this day",
    "estimated_cost": {int(daily_budget)}
  }}
]"""

    logger.info(f"[Itinerary] Sending request to Groq, prompt length: {len(prompt)} chars")

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": os.environ.get("MODEL_NAME", "llama-3.1-8b-instant"),
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

        logger.info(f"[Itinerary] Groq response status: {response.status_code}")

        if response.status_code != 200:
            logger.error(f"[Itinerary] Groq API error: {response.status_code} {response.text[:500]}")
            return _fallback_itinerary(destination, travel_dates, daily_budget), route_plan

        raw = response.json()["choices"][0]["message"]["content"].strip()
        logger.info(f"[Itinerary] Groq raw response ({len(raw)} chars): {raw[:200]}")

        # Strip accidental markdown fences
        raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
        raw = raw.strip()

        # Find JSON array in case Groq adds preamble text
        array_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if array_match:
            raw = array_match.group(0)

        days = json.loads(raw)

        if not isinstance(days, list) or len(days) == 0:
            raise ValueError(f"Expected non-empty list, got: {type(days)}")

        # Pad if Groq returned fewer days than expected
        while len(days) < total_days:
            i = len(days)
            days.append(_fallback_day(destination, i + 1, travel_dates[i] if i < len(travel_dates) else "", daily_budget))
            logger.warning(f"[Itinerary] Padded missing day {i+1}")

        logger.info(f"[Itinerary] Successfully generated {len(days)} days for {destination}")
        return days, route_plan

    except httpx.TimeoutException:
        logger.error("[Itinerary] Groq request timed out after 90s")
        return _fallback_itinerary(destination, travel_dates, daily_budget), route_plan
    except json.JSONDecodeError as e:
        logger.error(f"[Itinerary] JSON parse error: {e} | Raw: {raw[:500]}")
        return _fallback_itinerary(destination, travel_dates, daily_budget), route_plan
    except Exception as e:
        logger.error(f"[Itinerary] Groq call failed: {type(e).__name__}: {e}")
        return _fallback_itinerary(destination, travel_dates, daily_budget), route_plan


def _fallback_day(destination: str, day_num: int, date: str, daily_budget: float) -> Dict:
    return {
        "day": day_num,
        "date": date,
        "activities": [f"Explore {destination} - Day {day_num} (regenerate for full plan)"],
        "notes": "Could not generate detailed plan. Please retry.",
        "estimated_cost": int(daily_budget),
    }


def _fallback_itinerary(destination: str, travel_dates: List[str], daily_budget: float) -> List[Dict]:
    return [_fallback_day(destination, i + 1, d, daily_budget) for i, d in enumerate(travel_dates)]


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

    expanded_dates = expand_travel_dates(travel_dates)
    logger.info(f"create_daily_itinerary tool: raw={travel_dates} -> expanded={expanded_dates} ({len(expanded_dates)} days)")

    total_days = len(expanded_dates)
    daily_budget = round(budget_total / total_days, 0) if budget_total and total_days else 2000

    # NOTE: this tool path does NOT have access to self.groq_api_key.
    # It relies on GROQ_API_KEY env var. The agent's handle_request calls
    # generate_llm_itinerary directly with the key, which is the preferred path.
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    generate_llm_itinerary(
                        destination=destination, origin="",
                        travel_dates=expanded_dates, travelers_count=travelers_count,
                        budget_total=budget_total, budget_range=None,
                        user_preferences=None, weather_data=weather_data,
                        events_data=None, maps_data=None, budget_data=None,
                        groq_api_key=None,  # will fall back to env var
                    )
                )
                result = future.result(timeout=90)
                days, route_plan = result if isinstance(result, tuple) else (result, {"available": False})
        else:
            result = loop.run_until_complete(
                generate_llm_itinerary(
                    destination=destination, origin="",
                    travel_dates=expanded_dates, travelers_count=travelers_count,
                    budget_total=budget_total, budget_range=None,
                    user_preferences=None, weather_data=weather_data,
                    events_data=None, maps_data=None, budget_data=None,
                    groq_api_key=None,
                )
            )
            days, route_plan = result if isinstance(result, tuple) else (result, {"available": False})
    except Exception as e:
        logger.error(f"Tool LLM call failed: {e}")
        days = _fallback_itinerary(destination, expanded_dates, daily_budget)

    return {
        "destination": destination, "travelers_count": travelers_count,
        "total_days": total_days, "start_date": expanded_dates[0],
        "end_date": expanded_dates[-1], "itinerary": days,
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
        temp_max = day_weather.get("temperature_max") or day_weather.get("temp_max", 25)
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
            "date": date_str, "day": i + 1,
            "weather": {"temp_max": temp_max, "precipitation_chance": precipitation, "description": day_weather.get("description", "N/A")},
            "recommendations": recommendations
        })
    return {"destination": destination, "optimized_itinerary": optimized_days, "total_days": len(expanded_dates)}


@tool
def get_food_recommendations(destination: str) -> Dict[str, Any]:
    """Get food recommendations for a destination.

    Args:
        destination: Destination city or location

    Returns:
        Food recommendations note
    """
    return {"destination": destination, "note": "Specific restaurant recommendations included in the LLM-generated itinerary"}


@tool
def get_travel_tips(destination: str) -> Dict[str, Any]:
    """Get travel tips for a destination.

    Args:
        destination: Destination city or location

    Returns:
        Travel tips note
    """
    return {"destination": destination, "note": "Practical tips included per-day in the generated itinerary"}


@tool
def plan_single_day_activities(
    destination: str, day_number: int, total_days: int,
    weather_temp_max: Optional[float] = None, precipitation_chance: Optional[float] = None
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
    return {"destination": destination, "day_number": day_number, "note": "Full day plan generated as part of complete itinerary"}


@tool
def get_available_destinations() -> Dict[str, Any]:
    """Get supported destinations info.

    Returns:
        Info about destination coverage
    """
    return {"coverage": "All destinations worldwide supported via LLM generation"}


@tool
def estimate_time_per_attraction(destination: str, attraction_count: int = None) -> Dict[str, Any]:
    """Estimate time needed for attractions.

    Args:
        destination: Destination city
        attraction_count: Number of attractions

    Returns:
        Time estimates
    """
    return {"destination": destination, "estimated_hours_per_attraction": 2.0, "recommended_daily_attractions": 3, "notes": "Relaxed pace recommended"}


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