import httpx
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict
import logging

from app.config.settings import settings
from app.core.state import WeatherInfo, AirPollutionInfo

logger = logging.getLogger(__name__)

class WeatherService:
    """Service for fetching weather & air quality data using OpenWeather + Open-Meteo."""

    def __init__(self):
        self.api_key = settings.openweather_api_key
        self.ow_base_url = "https://api.openweathermap.org/data/2.5"
        self.ow_geo_url = "https://api.openweathermap.org/geo/1.0"
        self.om_base_url = "https://api.open-meteo.com/v1/forecast"

    # ------------------------- COORDINATES ------------------------- #

    async def get_coordinates(self, location: str) -> Optional[Dict[str, float]]:
        """Get latitude and longitude for a location using OpenWeather geocoding API."""
        try:
            async with httpx.AsyncClient() as client:
                params = {"q": location, "limit": 1, "appid": self.api_key}
                resp = await client.get(f"{self.ow_geo_url}/direct", params=params)
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    logger.error(f"Location not found: {location}")
                    return None
                return {"lat": data[0]["lat"], "lon": data[0]["lon"]}
        except Exception as e:
            logger.error(f"Failed to get coordinates for {location}: {e}")
            return None

    # ------------------------- OPENWEATHER ------------------------- #

    async def get_current_weather(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient() as client:
                params = {"lat": lat, "lon": lon, "appid": self.api_key, "units": "metric"}
                resp = await client.get(f"{self.ow_base_url}/weather", params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"Failed to get current weather: {e}")
            return None

    async def get_ow_forecast(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """5-day forecast (3-hour intervals)."""
        try:
            async with httpx.AsyncClient() as client:
                params = {"lat": lat, "lon": lon, "appid": self.api_key, "units": "metric"}
                resp = await client.get(f"{self.ow_base_url}/forecast", params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"Failed to get OpenWeather forecast: {e}")
            return None

    async def get_air_pollution_forecast(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """Air pollution forecast up to 5 days."""
        try:
            async with httpx.AsyncClient() as client:
                params = {"lat": lat, "lon": lon, "appid": self.api_key}
                resp = await client.get(f"{self.ow_base_url}/air_pollution/forecast", params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"Failed to get air pollution forecast: {e}")
            return None

    # ------------------------- OPEN-METEO ------------------------- #

    async def get_open_meteo_forecast(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """16-day daily forecast from Open-Meteo."""
        try:
            async with httpx.AsyncClient() as client:
                params = {
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,temperature_2m_min",
                    "timezone": "auto",
                }
                resp = await client.get(self.om_base_url, params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"Failed to get Open-Meteo forecast: {e}")
            return None

    # ------------------------- PARSERS ------------------------- #

    def _aggregate_daily_from_ow(self, forecast: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        """Aggregate 3-hour OpenWeather forecast into daily min/max."""
        daily = defaultdict(lambda: {"temp_min": float("inf"), "temp_max": float("-inf")})
        for item in forecast.get("list", []):
            dt = datetime.fromtimestamp(item["dt"])
            date_str = dt.strftime("%Y-%m-%d")
            main = item.get("main", {})
            temp_min = main.get("temp_min", main.get("temp", 0))
            temp_max = main.get("temp_max", main.get("temp", 0))
            daily[date_str]["temp_min"] = min(daily[date_str]["temp_min"], temp_min)
            daily[date_str]["temp_max"] = max(daily[date_str]["temp_max"], temp_max)
        return daily

    def _aggregate_air_pollution_by_day(self, air_data: Dict[str, Any]) -> Dict[str, AirPollutionInfo]:
        daily_vals = defaultdict(lambda: {"count": 0, "aqi": 0, "co": 0, "no": 0, "no2": 0, "o3": 0,
                                          "so2": 0, "pm2_5": 0, "pm10": 0, "nh3": 0})
        for item in air_data.get("list", []):
            dt = datetime.fromtimestamp(item["dt"])
            date_str = dt.strftime("%Y-%m-%d")
            comp = item["components"]
            daily_vals[date_str]["count"] += 1
            daily_vals[date_str]["aqi"] += item["main"]["aqi"]
            for k in comp:
                daily_vals[date_str][k] += comp[k]

        result = {}
        for date_str, vals in daily_vals.items():
            count = vals.pop("count")
            averaged = {k: v / count for k, v in vals.items()}
            result[date_str] = AirPollutionInfo(**averaged)
        return result

    def _create_weatherinfo(self, date: str, tmax: float, tmin: float, desc: str = "N/A") -> WeatherInfo:
        return WeatherInfo(
            date=date,
            temperature_max=tmax,
            temperature_min=tmin,
            description=desc,
            humidity=0,
            wind_speed=0,
            precipitation_chance=0
        )


    # ------------------------- MAIN PUBLIC ------------------------- #

    async def get_weather_for_dates(self, location: str, dates: List[str]) -> List[WeatherInfo]:
        """Return weather for the given dates:
        - ≤5 days: OpenWeather + air pollution
        - 6–16 days: Open-Meteo
        - >16 days: fallback
        """
        coords = await self.get_coordinates(location)
        if not coords:
            raise ValueError(f"Could not find coordinates for location: {location}")

        today = datetime.now().date()
        max_date = max(datetime.strptime(d, "%Y-%m-%d").date() for d in dates)
        delta_days = (max_date - today).days

        results: List[WeatherInfo] = []

        if delta_days <= 5:
            current = await self.get_current_weather(coords["lat"], coords["lon"])
            forecast = await self.get_ow_forecast(coords["lat"], coords["lon"])
            daily_agg = self._aggregate_daily_from_ow(forecast) if forecast else {}

            for d in dates:
                date_obj = datetime.strptime(d, "%Y-%m-%d").date()
                if date_obj == today and current:
                    main = current.get("main", {})
                    tmax = main.get("temp_max", main.get("temp", 0))
                    tmin = main.get("temp_min", main.get("temp", 0))
                    desc = current.get("weather", [{}])[0].get("description", "Unknown")
                    results.append(self._create_weatherinfo(d, tmax, tmin, desc))
                elif d in daily_agg:
                    agg = daily_agg[d]
                    results.append(self._create_weatherinfo(d, agg["temp_max"], agg["temp_min"]))
                else:
                    results.append(self._create_fallback_weather(d))

            # Attach air pollution data
            air_data = await self.get_air_pollution_forecast(coords["lat"], coords["lon"])
            if air_data:
                daily_air = self._aggregate_air_pollution_by_day(air_data)
                for r in results:
                    if r.date in daily_air:
                        r.air_pollution = daily_air[r.date]

        elif 6 <= delta_days <= 16:
            om_data = await self.get_open_meteo_forecast(coords["lat"], coords["lon"])
            if not om_data or "daily" not in om_data:
                logger.warning("Open-Meteo forecast unavailable, falling back.")
                return [self._create_fallback_weather(d) for d in dates]

            daily = om_data["daily"]
            daily_map = {
                daily["time"][i]: (daily["temperature_2m_max"][i], daily["temperature_2m_min"][i])
                for i in range(len(daily["time"]))
            }

            for d in dates:
                if d in daily_map:
                    tmax, tmin = daily_map[d]
                    results.append(self._create_weatherinfo(d, tmax, tmin))
                else:
                    results.append(self._create_fallback_weather(d))

        else:
            results = [self._create_fallback_weather(d) for d in dates]

        return results

    # ------------------------- FALLBACK ------------------------- #

    def _create_fallback_weather(self, date_str: str) -> WeatherInfo:
        return WeatherInfo(
            date=date_str,
            temperature_max=22.0,
            temperature_min=18.0,
            description="Partly cloudy",
            humidity=60,
            wind_speed=5.0,
            precipitation_chance=20
        )
