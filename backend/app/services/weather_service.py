import httpx
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict
import logging

from app.config.settings import settings
from app.core.state import WeatherInfo, AirPollutionInfo

logger = logging.getLogger(__name__)

# WMO weather code -> human description mapping
WMO_DESCRIPTIONS = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Heavy showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

# Seasonal fallback data per month for Indian cities
SEASONAL_DATA = {
    "jaipur":   {1:(22,8,5), 2:(26,11,5), 3:(33,17,5), 4:(39,23,5), 5:(42,27,10), 6:(41,31,30), 7:(37,27,60), 8:(34,26,55), 9:(35,24,35), 10:(35,19,10), 11:(29,12,5), 12:(23,9,5)},
    "delhi":    {1:(21,7,5), 2:(24,10,5), 3:(30,15,5), 4:(36,21,5), 5:(40,26,10), 6:(40,29,25), 7:(36,28,55), 8:(34,27,55), 9:(34,25,30), 10:(33,19,10), 11:(28,12,5), 12:(22,8,5)},
    "agra":     {1:(22,8,5), 2:(25,11,5), 3:(32,16,5), 4:(38,22,5), 5:(42,27,8), 6:(41,30,25), 7:(36,27,55), 8:(34,26,55), 9:(34,24,30), 10:(33,18,8), 11:(28,12,5), 12:(23,8,5)},
    "mumbai":   {1:(31,19,5), 2:(32,20,5), 3:(34,23,5), 4:(36,26,5), 5:(36,28,20), 6:(32,27,85), 7:(30,26,90), 8:(30,26,85), 9:(32,26,70), 10:(33,25,30), 11:(33,23,10), 12:(32,21,5)},
    "goa":      {1:(32,19,5), 2:(33,21,5), 3:(34,24,5), 4:(35,27,10), 5:(34,28,40), 6:(31,26,90), 7:(29,25,95), 8:(29,25,90), 9:(30,25,75), 10:(31,24,40), 11:(33,23,10), 12:(32,21,5)},
    "default":  {1:(28,15,10), 2:(30,17,10), 3:(34,21,10), 4:(38,26,10), 5:(40,29,15), 6:(38,30,40), 7:(35,28,60), 8:(34,27,55), 9:(34,26,40), 10:(33,22,15), 11:(30,18,10), 12:(28,15,10)},
}

def get_seasonal_weather(location: str, date_str: str) -> WeatherInfo:
    """Return realistic seasonal estimates when live forecast is unavailable."""
    month = datetime.strptime(date_str, "%Y-%m-%d").month
    loc = location.lower()
    city_key = next((k for k in SEASONAL_DATA if k in loc), "default")
    tmax, tmin, rain = SEASONAL_DATA[city_key][month]

    # Add monsoon note for July-September
    if month in (6, 7, 8, 9):
        desc = "Monsoon season — expect rain showers"
    elif month in (12, 1, 2):
        desc = "Pleasant winter weather"
    elif month in (3, 4, 5):
        desc = "Hot and dry"
    else:
        desc = "Partly cloudy"

    return WeatherInfo(
        date=date_str,
        temperature_max=float(tmax),
        temperature_min=float(tmin),
        description=desc,
        humidity=70 if month in (6,7,8,9) else 40,
        wind_speed=10.0 if month in (6,7,8,9) else 5.0,
        precipitation_chance=rain,
    )


class WeatherService:
    """Service for fetching weather & air quality data."""

    def __init__(self):
        self.api_key = settings.openweather_api_key
        self.ow_base_url = "https://api.openweathermap.org/data/2.5"
        self.ow_geo_url = "https://api.openweathermap.org/geo/1.0"
        self.om_base_url = "https://api.open-meteo.com/v1/forecast"

    async def get_coordinates(self, location: str) -> Optional[Dict[str, float]]:
        try:
            async with httpx.AsyncClient() as client:
                params = {"q": location, "limit": 1, "appid": self.api_key}
                resp = await client.get(f"{self.ow_geo_url}/direct", params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    return None
                return {"lat": data[0]["lat"], "lon": data[0]["lon"]}
        except Exception as e:
            logger.error(f"Geocoding failed for {location}: {e}")
            return None

    async def get_current_weather(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient() as client:
                params = {"lat": lat, "lon": lon, "appid": self.api_key, "units": "metric"}
                resp = await client.get(f"{self.ow_base_url}/weather", params=params, timeout=10)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"Current weather failed: {e}")
            return None

    async def get_ow_forecast(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient() as client:
                params = {"lat": lat, "lon": lon, "appid": self.api_key, "units": "metric"}
                resp = await client.get(f"{self.ow_base_url}/forecast", params=params, timeout=10)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"OW forecast failed: {e}")
            return None

    async def get_air_pollution_forecast(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient() as client:
                params = {"lat": lat, "lon": lon, "appid": self.api_key}
                resp = await client.get(f"{self.ow_base_url}/air_pollution/forecast", params=params, timeout=10)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"Air pollution forecast failed: {e}")
            return None

    async def get_open_meteo_forecast(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """16-day daily forecast — now includes precipitation probability and weather codes."""
        try:
            async with httpx.AsyncClient() as client:
                params = {
                    "latitude": lat,
                    "longitude": lon,
                    "daily": ",".join([
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "precipitation_probability_max",
                        "weathercode",
                        "windspeed_10m_max",
                        "relative_humidity_2m_max",
                    ]),
                    "timezone": "auto",
                    "forecast_days": 16,
                }
                resp = await client.get(self.om_base_url, params=params, timeout=15)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"Open-Meteo forecast failed: {e}")
            return None

    def _aggregate_daily_from_ow(self, forecast: Dict[str, Any]) -> Dict[str, Dict]:
        daily = defaultdict(lambda: {"temp_min": float("inf"), "temp_max": float("-inf"), "descriptions": [], "humidity": [], "wind": [], "pop": []})
        for item in forecast.get("list", []):
            dt = datetime.fromtimestamp(item["dt"])
            date_str = dt.strftime("%Y-%m-%d")
            main = item.get("main", {})
            daily[date_str]["temp_min"] = min(daily[date_str]["temp_min"], main.get("temp_min", main.get("temp", 0)))
            daily[date_str]["temp_max"] = max(daily[date_str]["temp_max"], main.get("temp_max", main.get("temp", 0)))
            daily[date_str]["descriptions"].append(item.get("weather", [{}])[0].get("description", ""))
            daily[date_str]["humidity"].append(main.get("humidity", 0))
            daily[date_str]["wind"].append(item.get("wind", {}).get("speed", 0))
            daily[date_str]["pop"].append(int(item.get("pop", 0) * 100))
        return daily

    def _aggregate_air_pollution_by_day(self, air_data: Dict[str, Any]) -> Dict[str, AirPollutionInfo]:
        daily_vals = defaultdict(lambda: {"count":0,"aqi":0,"co":0,"no":0,"no2":0,"o3":0,"so2":0,"pm2_5":0,"pm10":0,"nh3":0})
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
            result[date_str] = AirPollutionInfo(**{k: v/count for k, v in vals.items()})
        return result

    async def get_weather_for_dates(self, location: str, dates: List[str]) -> List[WeatherInfo]:
        """
        Return WeatherInfo for each requested date:
        - <= 5 days out  : OpenWeather current + 5-day forecast
        - 6–16 days out  : Open-Meteo 16-day (with real descriptions + rain probability)
        - > 16 days out  : Seasonal estimates (realistic, not blank)
        """
        # Expand any date range strings
        import re
        expanded = []
        for d in dates:
            m = re.match(r'(\d{4}-\d{2}-\d{2})\s*(?:to|-)\s*(\d{4}-\d{2}-\d{2})', d.strip())
            if m:
                cur = datetime.strptime(m.group(1), "%Y-%m-%d")
                end = datetime.strptime(m.group(2), "%Y-%m-%d")
                while cur <= end:
                    expanded.append(cur.strftime("%Y-%m-%d"))
                    cur += timedelta(days=1)
            else:
                expanded.append(d)
        dates = expanded

        coords = await self.get_coordinates(location)
        if not coords:
            logger.warning(f"Could not geocode {location}, using seasonal fallback")
            return [get_seasonal_weather(location, d) for d in dates]

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
                    desc = current.get("weather", [{}])[0].get("description", "Partly cloudy")
                    results.append(WeatherInfo(
                        date=d,
                        temperature_max=main.get("temp_max", main.get("temp", 25)),
                        temperature_min=main.get("temp_min", main.get("temp", 18)),
                        description=desc.capitalize(),
                        humidity=int(main.get("humidity", 60)),
                        wind_speed=float(current.get("wind", {}).get("speed", 5)),
                        precipitation_chance=0,
                    ))
                elif d in daily_agg:
                    agg = daily_agg[d]
                    desc = max(set(agg["descriptions"]), key=agg["descriptions"].count) if agg["descriptions"] else "Partly cloudy"
                    results.append(WeatherInfo(
                        date=d,
                        temperature_max=round(agg["temp_max"], 1),
                        temperature_min=round(agg["temp_min"], 1),
                        description=desc.capitalize(),
                        humidity=int(sum(agg["humidity"]) / len(agg["humidity"])) if agg["humidity"] else 60,
                        wind_speed=round(sum(agg["wind"]) / len(agg["wind"]), 1) if agg["wind"] else 5,
                        precipitation_chance=max(agg["pop"]) if agg["pop"] else 0,
                    ))
                else:
                    results.append(get_seasonal_weather(location, d))

            # Attach air pollution
            air_data = await self.get_air_pollution_forecast(coords["lat"], coords["lon"])
            if air_data:
                daily_air = self._aggregate_air_pollution_by_day(air_data)
                for r in results:
                    if r.date in daily_air:
                        r.air_pollution = daily_air[r.date]

        elif 6 <= delta_days <= 16:
            om_data = await self.get_open_meteo_forecast(coords["lat"], coords["lon"])

            if not om_data or "daily" not in om_data:
                logger.warning("Open-Meteo unavailable, using seasonal fallback")
                return [get_seasonal_weather(location, d) for d in dates]

            daily = om_data["daily"]
            times = daily.get("time", [])
            tmax_list = daily.get("temperature_2m_max", [])
            tmin_list = daily.get("temperature_2m_min", [])
            rain_list = daily.get("precipitation_probability_max", [])
            code_list = daily.get("weathercode", [])
            wind_list = daily.get("windspeed_10m_max", [])
            humid_list = daily.get("relative_humidity_2m_max", [])

            # Build lookup by date
            om_map = {}
            for i, t in enumerate(times):
                om_map[t] = {
                    "tmax": tmax_list[i] if i < len(tmax_list) else None,
                    "tmin": tmin_list[i] if i < len(tmin_list) else None,
                    "rain": rain_list[i] if i < len(rain_list) else 0,
                    "code": code_list[i] if i < len(code_list) else 0,
                    "wind": wind_list[i] if i < len(wind_list) else 5,
                    "humid": humid_list[i] if i < len(humid_list) else 60,
                }

            for d in dates:
                if d in om_map:
                    entry = om_map[d]
                    code = int(entry["code"] or 0)
                    desc = WMO_DESCRIPTIONS.get(code, "Partly cloudy")
                    results.append(WeatherInfo(
                        date=d,
                        temperature_max=round(entry["tmax"], 1) if entry["tmax"] is not None else 30.0,
                        temperature_min=round(entry["tmin"], 1) if entry["tmin"] is not None else 20.0,
                        description=desc,
                        humidity=int(entry["humid"] or 60),
                        wind_speed=round(float(entry["wind"] or 5), 1),
                        precipitation_chance=int(entry["rain"] or 0),
                    ))
                else:
                    results.append(get_seasonal_weather(location, d))

        else:
            # > 16 days: use realistic seasonal estimates
            logger.info(f"Dates beyond 16-day forecast window — using seasonal estimates for {location}")
            results = [get_seasonal_weather(location, d) for d in dates]

        return results