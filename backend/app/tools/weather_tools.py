import httpx
import asyncio
from typing import List, Optional, Dict, Any, Annotated
from datetime import datetime, timedelta
from collections import defaultdict
import re
import logging
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config.settings import settings
from app.core.state import WeatherInfo, AirPollutionInfo

logger = logging.getLogger(__name__)

# ========================= WMO CODE MAP ========================= #

WMO_DESCRIPTIONS = {
    0:"Clear sky", 1:"Mainly clear", 2:"Partly cloudy", 3:"Overcast",
    45:"Fog", 48:"Icy fog",
    51:"Light drizzle", 53:"Moderate drizzle", 55:"Dense drizzle",
    61:"Slight rain", 63:"Moderate rain", 65:"Heavy rain",
    71:"Slight snow", 73:"Moderate snow", 75:"Heavy snow", 77:"Snow grains",
    80:"Slight showers", 81:"Moderate showers", 82:"Heavy showers",
    85:"Slight snow showers", 86:"Heavy snow showers",
    95:"Thunderstorm", 96:"Thunderstorm with hail", 99:"Thunderstorm with heavy hail",
}

# Seasonal fallback: city -> month -> (tmax, tmin, rain_pct, description)
SEASONAL_DATA = {
    "jaipur":  {1:(22,8,5,"Cool and sunny"),2:(26,11,5,"Warm and clear"),3:(33,17,5,"Hot and dry"),4:(39,23,5,"Very hot"),5:(42,27,10,"Extremely hot"),6:(41,31,30,"Hot with some showers"),7:(37,27,60,"Monsoon season"),8:(34,26,55,"Monsoon season"),9:(35,24,35,"Post-monsoon showers"),10:(35,19,10,"Pleasant"),11:(29,12,5,"Cool and pleasant"),12:(23,9,5,"Cold and sunny")},
    "delhi":   {1:(21,7,5,"Cool and sunny"),2:(24,10,5,"Mild and clear"),3:(30,15,5,"Warm"),4:(36,21,5,"Hot"),5:(40,26,10,"Very hot"),6:(40,29,25,"Hot with showers"),7:(36,28,55,"Monsoon season"),8:(34,27,55,"Monsoon season"),9:(34,25,30,"Partly cloudy"),10:(33,19,10,"Pleasant"),11:(28,12,5,"Cool"),12:(22,8,5,"Cold and clear")},
    "agra":    {1:(22,8,5,"Cool and sunny"),2:(25,11,5,"Mild"),3:(32,16,5,"Warm"),4:(38,22,5,"Hot"),5:(42,27,8,"Very hot"),6:(41,30,25,"Hot with showers"),7:(36,27,55,"Monsoon season"),8:(34,26,55,"Monsoon season"),9:(34,24,30,"Partly cloudy"),10:(33,18,8,"Pleasant"),11:(28,12,5,"Cool"),12:(23,8,5,"Cold")},
    "mumbai":  {1:(31,19,5,"Sunny"),2:(32,20,5,"Sunny"),3:(34,23,5,"Hot"),4:(36,26,5,"Hot and humid"),5:(36,28,20,"Hot with showers"),6:(32,27,85,"Heavy monsoon"),7:(30,26,90,"Heavy monsoon"),8:(30,26,85,"Heavy monsoon"),9:(32,26,70,"Monsoon"),10:(33,25,30,"Partly cloudy"),11:(33,23,10,"Warm"),12:(32,21,5,"Warm and sunny")},
    "goa":     {1:(32,19,5,"Sunny"),2:(33,21,5,"Sunny"),3:(34,24,5,"Hot"),4:(35,27,10,"Hot"),5:(34,28,40,"Hot with showers"),6:(31,26,90,"Heavy monsoon"),7:(29,25,95,"Heavy monsoon"),8:(29,25,90,"Heavy monsoon"),9:(30,25,75,"Monsoon"),10:(31,24,40,"Partly cloudy"),11:(33,23,10,"Pleasant"),12:(32,21,5,"Sunny")},
    "default": {1:(28,15,10,"Partly cloudy"),2:(30,17,10,"Partly cloudy"),3:(34,21,10,"Warm"),4:(38,26,10,"Hot"),5:(40,29,15,"Hot"),6:(38,30,40,"Showers likely"),7:(35,28,60,"Monsoon season"),8:(34,27,55,"Monsoon season"),9:(34,26,40,"Partly cloudy"),10:(33,22,15,"Pleasant"),11:(30,18,10,"Mild"),12:(28,15,10,"Partly cloudy")},
}

def _seasonal_fallback(location: str, date_str: str) -> Dict[str, Any]:
    """Return realistic seasonal weather estimate."""
    month = datetime.strptime(date_str, "%Y-%m-%d").month
    loc = location.lower()
    key = next((k for k in SEASONAL_DATA if k in loc), "default")
    tmax, tmin, rain, desc = SEASONAL_DATA[key][month]
    return {
        "date": date_str,
        "temp_max": float(tmax),
        "temp_min": float(tmin),
        "description": desc,
        "humidity": 70 if month in (6,7,8,9) else 45,
        "wind_speed": 12.0 if month in (6,7,8,9) else 6.0,
        "precipitation_chance": rain,
        "seasonal_estimate": True,
    }

def _expand_dates(dates: List[str]) -> List[str]:
    expanded = []
    for d in dates:
        d = d.strip()
        m = re.match(r'(\d{4}-\d{2}-\d{2})\s*(?:to|-)\s*(\d{4}-\d{2}-\d{2})', d)
        if m:
            cur = datetime.strptime(m.group(1), "%Y-%m-%d")
            end = datetime.strptime(m.group(2), "%Y-%m-%d")
            while cur <= end:
                expanded.append(cur.strftime("%Y-%m-%d"))
                cur += timedelta(days=1)
        else:
            expanded.append(d)
    return expanded

# ========================= INPUT SCHEMAS ========================= #

class LocationInput(BaseModel):
    location: str = Field(..., description="City name or location")

class CoordinatesInput(BaseModel):
    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")

class WeatherDatesInput(BaseModel):
    location: str = Field(..., description="City name or location")
    dates: Annotated[List[str], "List of dates YYYY-MM-DD"]

# ========================= HELPER ========================= #

class WeatherServiceHelpers:
    @staticmethod
    def aggregate_daily_from_ow(forecast: Dict) -> Dict:
        daily = defaultdict(lambda: {"temp_min": float("inf"), "temp_max": float("-inf"), "descriptions": [], "humidity": [], "wind": [], "pop": []})
        for item in forecast.get("list", []):
            dt = datetime.fromtimestamp(item["dt"])
            ds = dt.strftime("%Y-%m-%d")
            main = item.get("main", {})
            daily[ds]["temp_min"] = min(daily[ds]["temp_min"], main.get("temp_min", main.get("temp", 0)))
            daily[ds]["temp_max"] = max(daily[ds]["temp_max"], main.get("temp_max", main.get("temp", 0)))
            daily[ds]["descriptions"].append(item.get("weather", [{}])[0].get("description", ""))
            daily[ds]["humidity"].append(main.get("humidity", 60))
            daily[ds]["wind"].append(item.get("wind", {}).get("speed", 5))
            daily[ds]["pop"].append(int(item.get("pop", 0) * 100))
        return daily

    @staticmethod
    def aggregate_air_pollution_by_day(air_data: Dict) -> Dict:
        dv = defaultdict(lambda: {"count":0,"aqi":0,"co":0,"no":0,"no2":0,"o3":0,"so2":0,"pm2_5":0,"pm10":0,"nh3":0})
        for item in air_data.get("list", []):
            ds = datetime.fromtimestamp(item["dt"]).strftime("%Y-%m-%d")
            comp = item["components"]
            dv[ds]["count"] += 1
            dv[ds]["aqi"] += item["main"]["aqi"]
            for k in comp: dv[ds][k] += comp[k]
        result = {}
        for ds, vals in dv.items():
            count = vals.pop("count")
            result[ds] = {k: v/count for k, v in vals.items()}
        return result

# ========================= TOOLS ========================= #

@tool
async def get_location_coordinates(location: str) -> Dict[str, Any]:
    """Get latitude and longitude for a location.
    Args:
        location: City name
    Returns:
        Dict with lat, lon
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.openweathermap.org/geo/1.0/direct",
                params={"q": location, "limit": 1, "appid": settings.openweather_api_key}, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return {"error": f"Location not found: {location}"}
            return {"location": location, "lat": data[0]["lat"], "lon": data[0]["lon"], "name": data[0].get("name"), "country": data[0].get("country")}
    except Exception as e:
        return {"error": str(e)}

@tool
async def get_current_weather(lat: float, lon: float) -> Dict[str, Any]:
    """Get current weather at coordinates.
    Args:
        lat: Latitude
        lon: Longitude
    Returns:
        Current weather dict
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"lat": lat, "lon": lon, "appid": settings.openweather_api_key, "units": "metric"}, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "temperature": data["main"]["temp"], "temp_min": data["main"]["temp_min"],
                "temp_max": data["main"]["temp_max"], "humidity": data["main"]["humidity"],
                "wind_speed": data["wind"]["speed"],
                "description": data["weather"][0]["description"].capitalize(),
                "precipitation_chance": 0,
            }
    except Exception as e:
        return {"error": str(e)}

@tool
async def get_5day_forecast(lat: float, lon: float) -> Dict[str, Any]:
    """Get 5-day weather forecast.
    Args:
        lat: Latitude
        lon: Longitude
    Returns:
        Dict with daily_summary keyed by date
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={"lat": lat, "lon": lon, "appid": settings.openweather_api_key, "units": "metric"}, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            daily_agg = WeatherServiceHelpers.aggregate_daily_from_ow(data)
            return {"forecast_type": "5-day", "daily_summary": daily_agg, "raw_data": data}
    except Exception as e:
        return {"error": str(e)}

@tool
async def get_extended_forecast(lat: float, lon: float) -> Dict[str, Any]:
    """Get 16-day extended forecast from Open-Meteo with full weather details.
    Args:
        lat: Latitude
        lon: Longitude
    Returns:
        Dict with daily_forecast list
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 16,
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode,windspeed_10m_max,relative_humidity_2m_max",
                }, timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            if "daily" not in data:
                return {"error": "No forecast data"}
            d = data["daily"]
            times       = d.get("time", [])
            tmax_list   = d.get("temperature_2m_max", [])
            tmin_list   = d.get("temperature_2m_min", [])
            rain_list   = d.get("precipitation_probability_max", [])
            code_list   = d.get("weathercode", [])
            wind_list   = d.get("windspeed_10m_max", [])
            humid_list  = d.get("relative_humidity_2m_max", [])
            forecast = []
            for i, t in enumerate(times):
                code = int(code_list[i]) if i < len(code_list) and code_list[i] is not None else 2
                desc = WMO_DESCRIPTIONS.get(code, "Partly cloudy")
                forecast.append({
                    "date": t,
                    "temp_max": round(tmax_list[i], 1) if i < len(tmax_list) and tmax_list[i] is not None else 30.0,
                    "temp_min": round(tmin_list[i], 1) if i < len(tmin_list) and tmin_list[i] is not None else 20.0,
                    "description": desc,
                    "precipitation_chance": int(rain_list[i]) if i < len(rain_list) and rain_list[i] is not None else 0,
                    "wind_speed": round(float(wind_list[i]), 1) if i < len(wind_list) and wind_list[i] is not None else 5.0,
                    "humidity": int(humid_list[i]) if i < len(humid_list) and humid_list[i] is not None else 60,
                })
            return {"forecast_type": "16-day", "daily_forecast": forecast}
    except Exception as e:
        return {"error": str(e)}

@tool
async def get_air_quality(lat: float, lon: float) -> Dict[str, Any]:
    """Get air quality forecast.
    Args:
        lat: Latitude
        lon: Longitude
    Returns:
        Dict with daily_air_quality
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.openweathermap.org/data/2.5/air_pollution/forecast",
                params={"lat": lat, "lon": lon, "appid": settings.openweather_api_key}, timeout=10
            )
            resp.raise_for_status()
            daily_air = WeatherServiceHelpers.aggregate_air_pollution_by_day(resp.json())
            return {"daily_air_quality": daily_air}
    except Exception as e:
        return {"error": str(e)}

@tool
async def get_weather_for_specific_dates(location: str, dates: List[str]) -> Dict[str, Any]:
    """Get weather forecast for specific travel dates at a location.

    Args:
        location: City name or location string
        dates: List of dates in YYYY-MM-DD format (also accepts range strings like '2026-07-15 to 2026-07-18')

    Returns:
        Weather information for each requested date with consistent field names
    """
    # Always expand date ranges first
    dates = _expand_dates(dates)

    coords = await get_location_coordinates.ainvoke({"location": location})
    if "error" in coords:
        # Return seasonal fallback for all dates
        return {
            "location": location,
            "weather_data": [_seasonal_fallback(location, d) for d in dates],
            "source": "seasonal_estimate"
        }

    lat, lon = coords["lat"], coords["lon"]
    today = datetime.now().date()
    max_date = max(datetime.strptime(d, "%Y-%m-%d").date() for d in dates)
    delta = (max_date - today).days

    results = []

    try:
        if delta <= 5:
            forecast_res = await get_5day_forecast.ainvoke({"lat": lat, "lon": lon})
            air_res = await get_air_quality.ainvoke({"lat": lat, "lon": lon})
            daily_agg = forecast_res.get("daily_summary", {}) if "error" not in forecast_res else {}
            daily_air = air_res.get("daily_air_quality", {}) if "error" not in air_res else {}

            for d in dates:
                date_obj = datetime.strptime(d, "%Y-%m-%d").date()
                if date_obj == today:
                    cur = await get_current_weather.ainvoke({"lat": lat, "lon": lon})
                    if "error" not in cur:
                        results.append({
                            "date": d,
                            "temp_max": cur.get("temp_max", 25),
                            "temp_min": cur.get("temp_min", 18),
                            "description": cur.get("description", "Partly cloudy"),
                            "humidity": cur.get("humidity", 60),
                            "wind_speed": cur.get("wind_speed", 5),
                            "precipitation_chance": cur.get("precipitation_chance", 0),
                            "air_quality": daily_air.get(d),
                        })
                    else:
                        results.append(_seasonal_fallback(location, d))
                elif d in daily_agg:
                    agg = daily_agg[d]
                    descs = agg.get("descriptions", [])
                    desc = max(set(descs), key=descs.count).capitalize() if descs else "Partly cloudy"
                    results.append({
                        "date": d,
                        "temp_max": round(agg["temp_max"], 1),
                        "temp_min": round(agg["temp_min"], 1),
                        "description": desc,
                        "humidity": int(sum(agg.get("humidity", [60])) / max(1, len(agg.get("humidity", [60])))),
                        "wind_speed": round(sum(agg.get("wind", [5])) / max(1, len(agg.get("wind", [5]))), 1),
                        "precipitation_chance": max(agg.get("pop", [0])),
                        "air_quality": daily_air.get(d),
                    })
                else:
                    results.append(_seasonal_fallback(location, d))

        elif 6 <= delta <= 16:
            forecast_res = await get_extended_forecast.ainvoke({"lat": lat, "lon": lon})
            if "error" in forecast_res:
                return {"location": location, "weather_data": [_seasonal_fallback(location, d) for d in dates], "source": "seasonal_estimate"}

            fm = {f["date"]: f for f in forecast_res.get("daily_forecast", [])}
            for d in dates:
                if d in fm:
                    f = fm[d]
                    results.append({
                        "date": d,
                        "temp_max": f["temp_max"],
                        "temp_min": f["temp_min"],
                        "description": f.get("description", "Partly cloudy"),
                        "humidity": f.get("humidity", 60),
                        "wind_speed": f.get("wind_speed", 5),
                        "precipitation_chance": f.get("precipitation_chance", 0),
                    })
                else:
                    results.append(_seasonal_fallback(location, d))
        else:
            # > 16 days: realistic seasonal estimates
            results = [_seasonal_fallback(location, d) for d in dates]

    except Exception as e:
        logger.error(f"Weather for dates failed: {e}")
        results = [_seasonal_fallback(location, d) for d in dates]

    return {
        "location": location,
        "coordinates": {"lat": lat, "lon": lon},
        "weather_data": results,
        "source": "live" if delta <= 16 else "seasonal_estimate",
    }


WEATHER_TOOLS = [
    get_location_coordinates,
    get_current_weather,
    get_5day_forecast,
    get_extended_forecast,
    get_air_quality,
    get_weather_for_specific_dates,
]