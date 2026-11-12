"""
Real daily weather forecast for a trip, from Open-Meteo (free, no API key).

Open-Meteo forecasts up to 16 days ahead. For trips further out there is no
forecast yet, and callers must say so instead of inventing one.
"""
from datetime import date, datetime
from typing import Any, Dict, List

import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_HORIZON_DAYS = 16

# WMO weather codes → short description (https://open-meteo.com/en/docs)
_WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Rain showers", 81: "Rain showers", 82: "Violent rain showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}
_BAD_WEATHER_CODES = {55, 63, 65, 66, 67, 73, 75, 81, 82, 86, 95, 96, 99}


class ForecastUnavailable(ValueError):
    """No real forecast can be given. The message is safe to show to the user."""


def get_trip_forecast(latitude: float, longitude: float, start_date: str, end_date: str) -> Dict[str, Any]:
    start = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
    end = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
    today = date.today()
    if (start - today).days >= FORECAST_HORIZON_DAYS:
        raise ForecastUnavailable(
            f"The weather forecast is only available {FORECAST_HORIZON_DAYS} days ahead. "
            "Try weather replan closer to your trip."
        )
    start = max(start, today)

    try:
        res = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Asia/Kolkata",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
            timeout=8,
        )
        res.raise_for_status()
        daily = res.json().get("daily") or {}
    except Exception:
        raise ForecastUnavailable("Couldn't get the weather forecast right now. Please try again in a moment.")

    days: List[Dict[str, Any]] = []
    for i, day in enumerate(daily.get("time") or []):
        code = (daily.get("weather_code") or [None])[i]
        days.append({
            "date": day,
            "condition": _WMO.get(code, "Unknown"),
            "badWeather": code in _BAD_WEATHER_CODES,
            "tempMaxC": (daily.get("temperature_2m_max") or [None])[i],
            "tempMinC": (daily.get("temperature_2m_min") or [None])[i],
            "rainChancePercent": (daily.get("precipitation_probability_max") or [None])[i],
        })
    if not days:
        raise ForecastUnavailable("No forecast is available for these dates.")

    bad_days = [d for d in days if d["badWeather"]]
    return {
        "source": "open-meteo",
        "days": days,
        "badWeatherDates": [d["date"] for d in bad_days],
        "condition": bad_days[0]["condition"] if bad_days else days[0]["condition"],
        "summary": (
            "Bad weather expected on " + ", ".join(f"{d['date']} ({d['condition']})" for d in bad_days)
            if bad_days else "No bad weather expected during the trip."
        ),
    }
