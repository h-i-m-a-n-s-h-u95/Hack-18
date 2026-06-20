"""
app/services/hotel_service.py

Hotel recommendation service — real data from Booking.com RapidAPI,
enriched with Groq LLM for tier categorization, descriptions, and booking tips.

Pipeline:
  1. Booking.com /v1/hotels/locations → get dest_id
  2. Booking.com /v1/hotels/search   → real hotels with prices/ratings/photos
  3. Groq LLM                        → categorize tiers + write descriptions + tips
  4. Cache in Redis with 6-hour TTL

Graceful degradation:
  Real API → Groq-only fallback → empty state with search link
"""

import httpx
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config.settings import settings

logger = logging.getLogger(__name__)

BOOKING_HOST = "booking-com.p.rapidapi.com"
HOTEL_CACHE_TTL = 60 * 60 * 6  # 6 hours — hotel prices move daily
RATE_LIMIT_SECONDS = 600        # 1 force-refresh per 10 minutes per session


def _rapidapi_headers() -> Dict[str, str]:
    key = settings.rapidapi_key
    return {
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": BOOKING_HOST,
    }


# ────────────────────────────────────────────────────────────────────
# Step 1: Resolve destination → dest_id via Booking.com locations API
# ────────────────────────────────────────────────────────────────────

async def _resolve_dest_id(destination: str) -> Optional[Dict[str, Any]]:
    """Get Booking.com dest_id and dest_type for a city name."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://{BOOKING_HOST}/v1/hotels/locations",
                headers=_rapidapi_headers(),
                params={"name": destination, "locale": "en-gb"},
            )
            resp.raise_for_status()
            results = resp.json()

        if not results:
            logger.warning(f"[HotelService] No dest_id found for '{destination}'")
            return None

        # Prefer 'city' type, fall back to first result
        for r in results:
            if r.get("dest_type") == "city":
                return {"dest_id": r["dest_id"], "dest_type": "city", "label": r.get("label", destination)}

        first = results[0]
        return {
            "dest_id": first.get("dest_id"),
            "dest_type": first.get("dest_type", "city"),
            "label": first.get("label", destination),
        }

    except Exception as e:
        logger.error(f"[HotelService] dest_id resolution failed for '{destination}': {e}")
        return None


# ────────────────────────────────────────────────────────────────────
# Step 2: Search hotels via Booking.com
# ────────────────────────────────────────────────────────────────────

async def fetch_hotels_from_booking(
    destination: str,
    checkin: str,
    checkout: str,
    max_results: int = 12,
) -> List[Dict[str, Any]]:
    """
    Fetch real hotel data from Booking.com RapidAPI.
    Returns a list of raw hotel dicts with real names, prices, ratings, photos.
    """
    dest_info = await _resolve_dest_id(destination)
    if not dest_info:
        return []

    try:
        params = {
            "dest_id": dest_info["dest_id"],
            "dest_type": dest_info["dest_type"],
            "checkin_date": checkin,
            "checkout_date": checkout,
            "adults_number": "2",
            "room_number": "1",
            "order_by": "popularity",
            "locale": "en-gb",
            "filter_by_currency": "INR",
            "units": "metric",
            "page_number": "0",
            "include_adjacency": "true",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"https://{BOOKING_HOST}/v1/hotels/search",
                headers=_rapidapi_headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        raw_results = data.get("result", [])
        if not raw_results:
            logger.warning(f"[HotelService] Booking.com returned 0 hotels for '{destination}'")
            return []

        hotels = []
        for h in raw_results[:max_results]:
            price_raw = h.get("min_total_price") or h.get("composite_price_breakdown", {}).get("gross_amount_per_night", {}).get("value")
            price = round(float(price_raw)) if price_raw else None

            review_score = h.get("review_score") or h.get("review_score_word")
            if isinstance(review_score, str):
                # e.g. "Superb" — try to get numeric
                review_score = h.get("review_score", 0)

            hotels.append({
                "id": str(h.get("hotel_id", "")),
                "name": h.get("hotel_name", "Unknown Hotel"),
                "area": h.get("district", "") or h.get("address", "") or h.get("city", ""),
                "price_per_night": price,
                "currency": h.get("currency_code", "INR") or "INR",
                "rating": round(float(h.get("review_score", 0) or 0), 1),
                "review_count": int(h.get("review_nr", 0) or 0),
                "photo_url": h.get("max_photo_url") or h.get("main_photo_url") or "",
                "booking_url": h.get("url", ""),
                "lat": float(h.get("latitude", 0) or 0),
                "lng": float(h.get("longitude", 0) or 0),
                # Placeholders — will be filled by LLM
                "tier": "",
                "amenities": [],
                "description": "",
                "booking_tip": "",
            })

        logger.info(f"[HotelService] Fetched {len(hotels)} hotels from Booking.com for '{destination}'")
        return hotels

    except Exception as e:
        logger.error(f"[HotelService] Booking.com search failed for '{destination}': {e}")
        return []


# ────────────────────────────────────────────────────────────────────
# Step 3: Groq LLM enrichment — tier, description, booking_tip
# ────────────────────────────────────────────────────────────────────

async def enrich_hotels_with_llm(
    hotels: List[Dict[str, Any]],
    destination: str,
    groq_api_key: str,
) -> List[Dict[str, Any]]:
    """
    Send real hotel data to Groq LLM to:
      - Categorize each into budget / mid-range / luxury tier
      - Write a short creative description (using real facts)
      - Write a practical booking tip
      - Suggest key amenities based on the hotel name/area
    Returns the enriched hotel list.
    """
    if not groq_api_key or not hotels:
        return hotels

    # Build a compact summary for the LLM
    hotel_summaries = []
    for i, h in enumerate(hotels):
        hotel_summaries.append(
            f'{i}: "{h["name"]}" in {h["area"]}, '
            f'₹{h["price_per_night"] or "N/A"}/night, '
            f'rating {h["rating"]}/10, '
            f'{h["review_count"]} reviews'
        )

    prompt = f"""You are a travel expert for {destination}, India.

Here are real hotels from Booking.com:
{chr(10).join(hotel_summaries)}

For EACH hotel (by index), provide:
1. "tier": "budget" (< ₹2500/night), "mid-range" (₹2500-6000), or "luxury" (> ₹6000)
   If price is missing, infer from name/area.
2. "amenities": list of 3-4 likely amenities (e.g. "Free WiFi", "Pool", "Breakfast Included")
3. "description": 1 vivid sentence about what makes this hotel special for travelers
4. "booking_tip": 1 practical sentence (best booking platform, room request, timing advice)

Respond with ONLY a JSON array of objects, one per hotel, in the same order:
[{{"index": 0, "tier": "...", "amenities": [...], "description": "...", "booking_tip": "..."}}, ...]

Output raw JSON only. No markdown, no code fences, no extra text."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": "You are a travel expert. Always output valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

        # Clean up potential markdown fences
        content = content.replace("```json", "").replace("```", "").strip()
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1:
            content = content[start : end + 1]

        enrichments = json.loads(content)

        # Merge LLM data into hotel objects
        for item in enrichments:
            idx = item.get("index", -1)
            if 0 <= idx < len(hotels):
                hotels[idx]["tier"] = item.get("tier", "mid-range")
                hotels[idx]["amenities"] = item.get("amenities", [])
                hotels[idx]["description"] = item.get("description", "")
                hotels[idx]["booking_tip"] = item.get("booking_tip", "")

        # Fill any hotels the LLM missed
        for h in hotels:
            if not h["tier"]:
                price = h.get("price_per_night") or 3000
                if price < 2500:
                    h["tier"] = "budget"
                elif price < 6000:
                    h["tier"] = "mid-range"
                else:
                    h["tier"] = "luxury"
            if not h["description"]:
                h["description"] = f"A popular stay in {destination}."
            if not h["booking_tip"]:
                h["booking_tip"] = "Book early for the best rates."

        logger.info(f"[HotelService] LLM enrichment completed for {len(hotels)} hotels")
        return hotels

    except Exception as e:
        logger.error(f"[HotelService] Groq LLM enrichment failed: {e}")
        # Fallback: simple price-based tier assignment
        for h in hotels:
            price = h.get("price_per_night") or 3000
            if price < 2500:
                h["tier"] = "budget"
            elif price < 6000:
                h["tier"] = "mid-range"
            else:
                h["tier"] = "luxury"
            h["description"] = f"A popular stay in {destination}."
            h["booking_tip"] = "Book early for the best rates."
            h["amenities"] = ["Free WiFi", "AC Rooms"]
        return hotels


# ────────────────────────────────────────────────────────────────────
# Groq-only fallback — when Booking.com API fails entirely
# ────────────────────────────────────────────────────────────────────

async def generate_hotels_via_llm_only(
    destination: str,
    checkin: str,
    checkout: str,
    groq_api_key: str,
) -> List[Dict[str, Any]]:
    """
    Pure LLM fallback when real API is unavailable.
    Generates plausible hotel recommendations based on Groq's knowledge.
    Source is marked as 'groq_fallback' so frontend can show disclaimer.
    """
    if not groq_api_key:
        return []

    prompt = f"""You are a travel expert. A user is visiting {destination} from {checkin} to {checkout}.

Suggest 6 real, well-known hotels in {destination} across 3 price tiers:
- 2 budget hotels (under ₹2500/night)
- 2 mid-range hotels (₹2500-6000/night)
- 2 luxury hotels (over ₹6000/night)

For each hotel, provide:
- "name": the real hotel name
- "area": neighborhood/landmark area
- "price_per_night": estimated price in INR
- "rating": estimated rating out of 10
- "review_count": estimated number of reviews
- "tier": "budget", "mid-range", or "luxury"
- "amenities": list of 3-4 amenities
- "description": 1 vivid sentence
- "booking_tip": 1 practical sentence

Output ONLY a raw JSON array. No markdown, no code fences."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": "You are a travel expert. Always output valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.4,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

        content = content.replace("```json", "").replace("```", "").strip()
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1:
            content = content[start : end + 1]

        hotels = json.loads(content)

        # Normalize and add missing fields
        for i, h in enumerate(hotels):
            h.setdefault("id", f"groq_fallback_{i}")
            h.setdefault("currency", "INR")
            h.setdefault("photo_url", "")
            h.setdefault("booking_url", "")
            h.setdefault("lat", 0)
            h.setdefault("lng", 0)

        logger.info(f"[HotelService] Groq-only fallback generated {len(hotels)} hotels for '{destination}'")
        return hotels

    except Exception as e:
        logger.error(f"[HotelService] Groq-only fallback also failed: {e}")
        return []
