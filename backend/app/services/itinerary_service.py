from typing import Dict, List, Optional
import re
from datetime import datetime, timedelta
from app.core.state import ItineraryDay, WeatherInfo, BudgetBreakdown
import logging

logger = logging.getLogger(__name__)


class ItineraryService:

    def __init__(self):
        self.destination_attractions = {
            "agra": {
                "must_visit": [
                    "Taj Mahal - Best visited at sunrise or sunset",
                    "Agra Fort - Explore the Mughal architecture",
                    "Itimad-ud-Daulah (Baby Taj) - Beautiful marble work"
                ],
                "optional": [
                    "Mehtab Bagh - Sunset view of Taj Mahal",
                    "Local markets - Handicrafts and leather goods",
                    "Fatehpur Sikri - Day trip to abandoned Mughal city"
                ],
                "food": [
                    "Try Agra's famous petha (sweet)",
                    "Mughlai cuisine at local restaurants",
                    "Street food near Sadar Bazaar"
                ],
                "tips": [
                    "Book Taj Mahal tickets online in advance",
                    "Carry water and wear comfortable shoes",
                    "Best light for photography: early morning or late afternoon"
                ]
            },
            "delhi": {
                "must_visit": [
                    "Red Fort - Historic Mughal fortress",
                    "India Gate - War memorial and iconic landmark",
                    "Qutub Minar - UNESCO World Heritage site",
                    "Lotus Temple - Modern architectural marvel"
                ],
                "optional": [
                    "Chandni Chowk - Old Delhi markets and street food",
                    "Humayun's Tomb - Beautiful garden tomb",
                    "Connaught Place - Shopping and dining",
                    "Akshardham Temple - Modern Hindu temple complex"
                ],
                "food": [
                    "Street food at Chandni Chowk",
                    "Paranthas at Paranthe Wali Gali",
                    "South Indian food at Saravana Bhavan"
                ],
                "tips": [
                    "Use Delhi Metro for efficient transport",
                    "Carry cash for street vendors",
                    "Avoid peak traffic hours (8-10 AM, 6-8 PM)"
                ]
            },
            "jaipur": {
                "must_visit": [
                    "Amber Fort - Majestic hilltop fort",
                    "City Palace - Royal residence and museum",
                    "Hawa Mahal - Palace of Winds",
                    "Jantar Mantar - Ancient astronomical observatory"
                ],
                "optional": [
                    "Nahargarh Fort - Sunset views over Jaipur",
                    "Jal Mahal - Palace in the middle of a lake",
                    "Local bazaars - Textiles, jewelry, handicrafts"
                ],
                "food": [
                    "Dal Baati Churma - Traditional Rajasthani dish",
                    "Lassi at famous local shops",
                    "Rajasthani thali at heritage restaurants"
                ],
                "tips": [
                    "Negotiate prices at local markets",
                    "Carry sunscreen and hat",
                    "Evening sound and light show at Amber Fort"
                ]
            }
        }

    def get_destination_info(self, destination: str) -> Dict:
        destination_lower = destination.lower()
        for city, info in self.destination_attractions.items():
            if city in destination_lower:
                return info
        return {
            "must_visit": [f"Explore main attractions in {destination}"],
            "optional": ["Visit local markets", "Try local cuisine", "Walk around city center"],
            "food": ["Try local specialties", "Visit popular restaurants"],
            "tips": ["Research local customs", "Carry water and comfortable shoes", "Keep emergency contacts handy"]
        }

    def _expand_travel_dates(self, travel_dates: list) -> list:
        """
        Expand date range strings into individual dates.
        ["2026-07-15 to 2026-07-18"] -> ["2026-07-15","2026-07-16","2026-07-17","2026-07-18"]
        Already-individual dates are passed through unchanged.
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

    def create_daily_itinerary(
        self,
        destination: str,
        travel_dates: List[str],
        weather_data: Optional[List[WeatherInfo]] = None,
        budget_data: Optional[BudgetBreakdown] = None,
        travelers_count: int = 1
    ) -> List[ItineraryDay]:
        """Create day-by-day itinerary — handles date range strings"""

        expanded_dates = self._expand_travel_dates(travel_dates)

        logger.info(
            f"Creating itinerary: raw_dates={travel_dates}, "
            f"expanded={expanded_dates} ({len(expanded_dates)} days)"
        )

        itinerary_days = []
        destination_info = self.get_destination_info(destination)
        all_attractions = destination_info["must_visit"] + destination_info["optional"]
        total_days = len(expanded_dates)

        for i, date_str in enumerate(expanded_dates):
            day_number = i + 1
            day_weather = weather_data[i] if weather_data and i < len(weather_data) else None

            activities = self._plan_day_activities(
                day_number, all_attractions, destination_info, day_weather, total_days
            )
            estimated_cost = self._estimate_daily_cost(budget_data, total_days, travelers_count)
            notes = self._create_day_notes(day_weather, destination_info, day_number)

            itinerary_days.append(ItineraryDay(
                day=day_number,
                date=date_str,
                activities=activities,
                notes=notes,
                estimated_cost=estimated_cost
            ))

        return itinerary_days

    def _plan_day_activities(
        self,
        day_number: int,
        all_attractions: List[str],
        destination_info: Dict,
        weather: Optional[WeatherInfo],
        total_days: int
    ) -> List[str]:
        activities = []

        if day_number == 1:
            activities.append("Arrival and check-in to accommodation")
            if destination_info["must_visit"]:
                activities.append(destination_info["must_visit"][0])
            activities.append("Explore nearby area and local food")

        elif day_number == total_days and total_days > 1:
            activities.append("Visit remaining attractions or shopping")
            activities.append("Pack and prepare for departure")
            activities.append("Departure")

        else:
            attractions_per_day = max(2, len(destination_info["must_visit"]) // max(1, total_days - 1))
            start_idx = (day_number - 2) * attractions_per_day
            end_idx = min(start_idx + attractions_per_day, len(all_attractions))
            activities.extend(all_attractions[start_idx:end_idx])

            if destination_info["food"]:
                food_idx = (day_number - 1) % len(destination_info["food"])
                activities.append(destination_info["food"][food_idx])

        weather_dict = self._normalize_weather(weather)
        if weather_dict.get("precipitation_chance", 0) > 70:
            activities.append("High chance of rain - carry umbrella")
        if weather_dict.get("temperature_max", 25) > 35:
            activities.append("Hot weather - plan indoor activities during midday")
        if weather_dict.get("temperature_max", 25) < 15:
            activities.append("Cold weather - dress warmly")

        return activities

    def _estimate_daily_cost(
        self,
        budget_data,
        total_days: int,
        travelers_count: int
    ) -> float:
        """Estimate cost for a single day — safe for both Pydantic models and dicts"""
        if not budget_data or total_days == 0:
            return 1500.0

        def _get(obj, key, default=0):
            if isinstance(obj, dict):
                return obj.get(key, default) or default
            return getattr(obj, key, default) or default

        nights = max(1, total_days - 1)
        daily_accommodation = _get(budget_data, "accommodation") / nights
        daily_food = _get(budget_data, "food") / total_days
        daily_activities = _get(budget_data, "activities") / total_days
        daily_transport = 200

        return round(daily_accommodation + daily_food + daily_activities + daily_transport, 2)

    def _create_day_notes(
        self,
        weather: Optional[WeatherInfo],
        destination_info: Dict,
        day_number: int
    ) -> str:
        notes = []

        weather_dict = self._normalize_weather(weather)
        if weather_dict:
            notes.append(
                f"Weather: {weather_dict.get('description', 'N/A')}, "
                f"{weather_dict.get('temperature_min', '?')}-{weather_dict.get('temperature_max', '?')}C"
            )
            if weather_dict.get("precipitation_chance", 0) > 50:
                notes.append("Chance of rain - plan indoor activities")
            if weather_dict.get("wind_speed", 0) > 15:
                notes.append("Windy conditions - secure loose items")

        if destination_info["tips"]:
            tip_idx = (day_number - 1) % len(destination_info["tips"])
            notes.append(f"Tip: {destination_info['tips'][tip_idx]}")

        return " | ".join(notes) if notes else "Enjoy your day of exploration!"

    def _normalize_weather(self, weather: Optional[WeatherInfo]) -> Dict:
        if not weather:
            return {}
        if isinstance(weather, dict):
            return weather
        if hasattr(weather, "__dict__"):
            return vars(weather)
        return {}