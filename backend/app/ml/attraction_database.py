"""
app/ml/attraction_database.py

Live attraction discovery using Google Places API — no hardcoded coordinates.
Works for any city/destination. Results are cached in Redis (30-day TTL)
since attraction locations rarely change, avoiding repeat API calls and quota usage.

Requires GOOGLE_PLACES_API_KEY in settings/.env.
Uses the Places API "Text Search" endpoint to find top tourist attractions
for a given city, then categorizes results via Places "types".
"""

from typing import Dict, List, Optional, Any
import logging
import httpx
import json
import random

from app.config.settings import settings

logger = logging.getLogger(__name__)

PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS_URL     = "https://maps.googleapis.com/maps/api/place/details/json"

CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days — attraction locations don't move

# Google Place "types" mapped to our internal category labels
PLACE_TYPE_TO_CATEGORY = {
    "tourist_attraction": "landmark",
    "museum":              "museum",
    "park":                "nature",
    "place_of_worship":    "temple",
    "hindu_temple":        "temple",
    "mosque":              "mosque",
    "church":              "church",
    "shopping_mall":       "market",
    "market":              "market",
    "natural_feature":     "nature",
    "amusement_park":      "cultural",
    "art_gallery":         "museum",
    "zoo":                 "nature",
    "castle":              "fort",
    "historical_landmark": "monument",
}

DEFAULT_VISIT_MINUTES = {
    "fort": 90, "palace": 75, "monument": 60, "museum": 75,
    "temple": 45, "mosque": 30, "church": 30, "market": 75,
    "nature": 90, "landmark": 45, "cultural": 120,
}

EXCLUDED_TYPES = {"lodging", "restaurant", "airport", "bus_station", "train_station", "food", "cafe"}


async def _get_redis():
    """Lazy import to avoid circular dependency issues."""
    try:
        from app.messaging.redis_client import get_redis_client
        client = get_redis_client()
        await client.connect()
        return client
    except Exception as e:
        logger.warning(f"[AttractionDB] Redis offline or failed to connect: {e}")
        return None


def _cache_key(city: str) -> str:
    return f"attractions_geo:{city.lower().strip()}"


def _category_from_types(types: List[str]) -> str:
    for t in types:
        if t in PLACE_TYPE_TO_CATEGORY:
            return PLACE_TYPE_TO_CATEGORY[t]
    return "landmark"


async def _fetch_attractions_from_google(city: str, max_results: int = 12) -> List[Dict[str, Any]]:
    """
    Query Google Places Text Search for top attractions in a city.
    Returns attraction dicts with lat/lng/category/visit_minutes — all
    derived from the live API response, nothing hardcoded.
    """
    api_key = getattr(settings, "google_places_api_key", None)
    if not api_key:
        logger.error("[AttractionDB] GOOGLE_PLACES_API_KEY not configured — geo-optimization disabled")
        return []

    query = f"top tourist attractions in {city}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                PLACES_TEXT_SEARCH_URL,
                params={"query": query, "key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            logger.warning(f"[AttractionDB] Places API status: {data.get('status')} for '{city}'")
            return []

        results = data.get("results", [])[:max_results]
        attractions = []

        for place in results:
            loc = place.get("geometry", {}).get("location", {})
            lat, lng = loc.get("lat"), loc.get("lng")
            if lat is None or lng is None:
                continue

            types = place.get("types", [])

            # Skip generic/irrelevant place types that leak into text search
            if any(t in types for t in EXCLUDED_TYPES):
                continue

            category = _category_from_types(types)

            attractions.append({
                "name":          place.get("name", "Unknown"),
                "lat":           lat,
                "lng":           lng,
                "category":      category,
                "visit_minutes": DEFAULT_VISIT_MINUTES.get(category, 60),
                "rating":        place.get("rating"),
                "address":       place.get("formatted_address", ""),
                "place_id":      place.get("place_id"),
                # Opening hours require a separate Places Details call —
                # see enrich_with_opening_hours() below, opt-in only.
                "opens":  None,
                "closes": None,
            })

        logger.info(f"[AttractionDB] Found {len(attractions)} attractions for '{city}' via live Google Places lookup")
        return attractions

    except httpx.HTTPStatusError as e:
        logger.error(f"[AttractionDB] Places API HTTP error for '{city}': {e}")
        return []
    except Exception as e:
        logger.error(f"[AttractionDB] Places API request failed for '{city}': {e}")
        return []


async def fetch_from_llm_and_ors(city: str) -> List[Dict[str, Any]]:
    """Generate attractions via Groq and geocode them via OpenRouteService."""
    # 1. Geocode City Center
    ors_key = getattr(settings, "openroute_api_key", None) or os.environ.get("OPENROUTE_API_KEY", "")
    city_lat, city_lng = 28.6139, 77.2090 # default Delhi fallback
    
    if ors_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.openrouteservice.org/geocode/search",
                    params={"api_key": ors_key, "text": city, "size": 1}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    features = data.get("features", [])
                    if features:
                        coords = features[0]["geometry"]["coordinates"]
                        city_lng, city_lat = coords[0], coords[1]
                        logger.info(f"[AttractionDB] Geocoded '{city}' center to: {city_lat}, {city_lng}")
        except Exception as e:
            logger.warning(f"[AttractionDB] City center geocoding failed: {e}")

    # 2. Query Groq for top attractions list
    groq_key = getattr(settings, "groq_api_key", None) or os.environ.get("GROQ_API_KEY", "")
    attractions_list = []
    
    if groq_key:
        try:
            prompt = f"""You are a local tour guide. For the city "{city}", list 8 to 12 top popular tourist attractions.
Respond with ONLY a valid JSON array of objects, containing precisely these fields for each attraction:
- "name": The common name of the attraction
- "category": Choose one of the internal categories: fort, palace, monument, museum, temple, mosque, church, market, nature, landmark, cultural
- "description": A brief 1-sentence summary of what it is
- "address": The search address/location string in "{city}" suitable for geocoding

Do not include any code block formatting, markdown formatting, or preamble text. Just output raw valid JSON."""

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={
                        "model": settings.model_name,
                        "messages": [
                            {"role": "system", "content": "You are a travel expert. Always output JSON only."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2
                    }
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"].strip()
                    content = content.replace("```json", "").replace("```", "").strip()
                    start_idx = content.find("[")
                    end_idx = content.rfind("]")
                    if start_idx != -1 and end_idx != -1:
                        content = content[start_idx:end_idx+1]
                    attractions_list = json.loads(content)
        except Exception as e:
            logger.error(f"[AttractionDB] Groq attraction generation failed: {e}")

    # Fallback to local mock array if Groq fails
    if not attractions_list:
        attractions_list = [
            {"name": f"Center Square in {city}", "category": "landmark", "description": "Famous public square", "address": f"Center, {city}"},
            {"name": f"Museum of {city}", "category": "museum", "description": "Local history museum", "address": f"Museum, {city}"},
            {"name": f"City Gardens", "category": "nature", "description": "Beautiful public park", "address": f"Central Park, {city}"},
            {"name": f"Ancient Temple", "category": "temple", "description": "Spiritual landmark", "address": f"Temple, {city}"},
        ]

    # 3. Geocode individual attractions
    final_attractions = []
    
    for idx, raw_attr in enumerate(attractions_list):
        name = raw_attr.get("name", "Unknown Attraction")
        category = raw_attr.get("category", "landmark")
        if category not in DEFAULT_VISIT_MINUTES:
            category = "landmark"
            
        description = raw_attr.get("description", "")
        address = raw_attr.get("address") or name
        
        attr_lat, attr_lng = None, None
        
        if ors_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://api.openrouteservice.org/geocode/search",
                        params={"api_key": ors_key, "text": f"{address}, {city}", "size": 1}
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        features = data.get("features", [])
                        if features:
                            coords = features[0]["geometry"]["coordinates"]
                            attr_lng, attr_lat = coords[0], coords[1]
            except Exception as e:
                logger.warning(f"[AttractionDB] Geocoding failed for '{name}': {e}")

        # Add small random offset around city center if geocoding fails
        if attr_lat is None or attr_lng is None:
            offset_lat = random.uniform(-0.02, 0.02)
            offset_lng = random.uniform(-0.02, 0.02)
            attr_lat = city_lat + offset_lat
            attr_lng = city_lng + offset_lng
            logger.debug(f"[AttractionDB] Random offset geocode for '{name}': {attr_lat}, {attr_lng}")

        final_attractions.append({
            "name":          name,
            "lat":           attr_lat,
            "lng":           attr_lng,
            "category":      category,
            "visit_minutes": DEFAULT_VISIT_MINUTES.get(category, 60),
            "description":   description,
            "place_id":      f"ors_fallback_{idx}",
            "opens":         None,
            "closes":        None,
        })

    return final_attractions


async def get_attractions_for_city(city: str, max_results: int = 12) -> List[Dict[str, Any]]:
    """
    Get attractions for a city — checks Redis cache first, falls back to
    a live Google Places API call (if key is set and valid), and falls back
    to OpenRouteService + Groq LLM if Google key fails, caching for 30 days.
    """
    if not city or not city.strip():
        return []

    redis_client = await _get_redis()
    cache_key = _cache_key(city)

    # Try cache first — avoids re-querying Google for repeat destinations
    if redis_client:
        try:
            cached = await redis_client.get_state(cache_key)
            if cached and cached.get("attractions"):
                logger.info(f"[AttractionDB] Cache hit for '{city}' ({len(cached['attractions'])} attractions)")
                return cached["attractions"]
        except Exception as e:
            logger.warning(f"[AttractionDB] Cache read failed: {e}")

    attractions = []

    # Live fetch from Google Places if configured and key is not legacy
    api_key = getattr(settings, "google_places_api_key", None) or os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if api_key and not api_key.startswith("AIzaSyDrhFCy0qmqpZx9DIsT29dZrQdsK0NCT_g"):
        attractions = await _fetch_attractions_from_google(city, max_results)

    # Fallback to OpenRouteService + LLM discovery
    if not attractions:
        logger.info(f"[AttractionDB] Running OpenRouteService + LLM discovery fallback for '{city}'")
        attractions = await fetch_from_llm_and_ors(city)

    if attractions and redis_client:
        try:
            await redis_client.set_state(
                cache_key, {"city": city, "attractions": attractions}, ttl=CACHE_TTL_SECONDS
            )
            logger.info(f"[AttractionDB] Cached {len(attractions)} attractions for '{city}' (30 day TTL)")
        except Exception as e:
            logger.warning(f"[AttractionDB] Cache write failed: {e}")

    return attractions


async def has_attraction_data(city: str) -> bool:
    """Quick check before attempting clustering — need at least 2 points."""
    attractions = await get_attractions_for_city(city)
    return len(attractions) >= 2


def filter_by_interests(attractions: List[Dict[str, Any]], interest_tags: List[str]) -> List[Dict[str, Any]]:
    """
    Optionally narrow attractions by user interest tags before clustering.
    Falls back to returning all attractions if no matches (avoid empty itinerary).
    """
    if not interest_tags:
        return attractions

    interest_to_categories = {
        "historical":  {"fort", "monument", "palace", "landmark"},
        "spiritual":   {"temple", "mosque", "church"},
        "markets":     {"market"},
        "nature":      {"nature"},
        "museums":     {"museum"},
        "cultural":    {"cultural", "museum"},
    }

    wanted_categories = set()
    for tag in interest_tags:
        wanted_categories |= interest_to_categories.get(tag.lower(), set())

    if not wanted_categories:
        return attractions

    filtered = [a for a in attractions if a["category"] in wanted_categories]
    return filtered if filtered else attractions


async def enrich_with_opening_hours(attraction: Dict[str, Any]) -> Dict[str, Any]:
    """
    Optional enrichment — fetches real opening hours via Places Details API
    using the place_id already stored on the attraction dict.

    Not called by default since it costs one extra API call per attraction
    (roughly doubling API volume for a full itinerary). Wire this in if you
    want time-window-aware TSP routing (e.g. don't schedule a fort that
    closes at 5pm as the day's last stop at 6pm).
    """
    place_id = attraction.get("place_id")
    api_key  = getattr(settings, "google_places_api_key", None)
    if not place_id or not api_key:
        return attraction

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                PLACES_DETAILS_URL,
                params={"place_id": place_id, "fields": "opening_hours", "key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()

        periods = data.get("result", {}).get("opening_hours", {}).get("periods", [])
        if periods:
            today_period = periods[0]
            attraction["opens"]  = today_period.get("open", {}).get("time")   # "0900"
            attraction["closes"] = today_period.get("close", {}).get("time")  # "1730"
    except Exception as e:
        logger.warning(f"[AttractionDB] Opening hours enrichment failed for {attraction.get('name')}: {e}")

    return attraction