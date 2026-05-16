"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Weather answer card service. Detects weather queries and fetches current
    conditions from one of four configured sources (tried in priority order):
      1. Home Assistant REST API (HA_URL + HA_TOKEN)
      2. InfluxDB Flux query (INFLUXDB_* env vars)
      3. Open-Meteo (LAT + LON, no API key)
      4. NWS/NOAA (LAT + LON, US only, no API key)

    If none are configured or all fail, the card is silently suppressed.
    All adapter failures are logged at WARNING before the next source is tried.
    influxdb-client is a conditional import inside _fetch_influx so a missing
    package only breaks that adapter.
"""
# Imports
import logging
import os
import re
from typing import Optional

import requests as _requests

# Globals
logger = logging.getLogger(__name__)

_TIMEOUT = 8  # seconds per HTTP request

# ── WMO weather code → human-readable string ─────────────────────────────────
_WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
    56: "Freezing drizzle", 57: "Heavy freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Rain showers", 82: "Violent rain showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

# Detection keywords (case-insensitive partial match)
_WEATHER_KEYWORDS = re.compile(
    r"\b(weather|temperature|how hot|how cold|forecast|will it rain|"
    r"humidity|wind speed|feels like|raining|snowing|sunny|cloudy)\b",
    re.IGNORECASE,
)

# NWS wind speed pattern: "10 mph" or "5 to 10 mph"
_RE_NWS_WIND = re.compile(r"(\d+)\s+mph$", re.IGNORECASE)


# Functions
def detect_weather_query(q: str) -> bool:
    """
    Input: q — raw search query string
    Output: True if the query contains a weather keyword
    """
    return bool(_WEATHER_KEYWORDS.search(q))


def _fetch_ha(config: dict) -> dict:
    """
    Input: config dict with HA_URL, HA_TOKEN, HA_WEATHER_ENTITY
    Output: weather dict {temp_c, conditions, humidity, wind_kph, source}
    Details:
        GETs the Home Assistant state for the configured weather entity.
        Raises RuntimeError on non-200 or missing attributes.
    """
    url = f"{config['HA_URL']}/api/states/{config['HA_WEATHER_ENTITY']}"
    headers = {"Authorization": f"Bearer {config['HA_TOKEN']}"}
    resp = _requests.get(url, headers=headers, timeout=_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"HA returned {resp.status_code}")
    data = resp.json()
    attrs = data.get("attributes", {})
    return {
        "temp_c":    attrs.get("temperature"),
        "conditions":data.get("state", "unknown"),
        "humidity":  attrs.get("humidity"),
        "wind_kph":  attrs.get("wind_speed"),
        "source":    "Home Assistant",
    }


def _fetch_influx(config: dict) -> dict:
    """
    Input: config dict with INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG,
           INFLUXDB_BUCKET, INFLUXDB_MEASUREMENT
    Output: weather dict {temp_c, conditions, humidity, wind_kph, source}
    Details:
        Imports influxdb_client inside the function so a missing package
        only breaks this adapter. Runs a Flux last() query on the bucket.
        Raises RuntimeError on connection failure or empty result.
    """
    try:
        from influxdb_client import InfluxDBClient  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("influxdb-client not installed") from exc

    client = InfluxDBClient(
        url=config["INFLUXDB_URL"],
        token=config["INFLUXDB_TOKEN"],
        org=config["INFLUXDB_ORG"],
    )
    query = (
        f'from(bucket:"{config["INFLUXDB_BUCKET"]}")'
        f' |> range(start:-1h)'
        f' |> filter(fn:(r) => r._measurement == "{config["INFLUXDB_MEASUREMENT"]}")'
        f' |> last()'
    )
    tables = client.query_api().query(query)
    if not tables:
        raise RuntimeError("InfluxDB query returned no results")

    fields: dict = {}
    for table in tables:
        for record in table.records:
            fields[record.get_field()] = record.get_value()

    if not fields:
        raise RuntimeError("InfluxDB result has no field records")

    return {
        "temp_c":    fields.get("temperature"),
        "conditions":fields.get("conditions", "unknown"),
        "humidity":  fields.get("humidity"),
        "wind_kph":  fields.get("wind_speed"),
        "source":    "InfluxDB",
    }


def _fetch_open_meteo(config: dict) -> dict:
    """
    Input: config dict with LAT, LON
    Output: weather dict {temp_c, conditions, humidity, wind_kph, source}
    Details:
        GETs the Open-Meteo forecast API (no API key required).
        Maps WMO weather codes to human-readable strings.
        Raises RuntimeError on non-200 response.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={config['LAT']}&longitude={config['LON']}"
        f"&current_weather=true"
        f"&hourly=relativehumidity_2m,windspeed_10m"
        f"&timezone=auto"
    )
    resp = _requests.get(url, timeout=_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Open-Meteo returned {resp.status_code}")
    data = resp.json()
    cw = data.get("current_weather", {})
    code = cw.get("weathercode", -1)
    hourly = data.get("hourly", {})
    humidity_list = hourly.get("relativehumidity_2m", [])
    humidity = humidity_list[0] if humidity_list else None
    return {
        "temp_c":    cw.get("temperature"),
        "conditions":_WMO_CODES.get(code, f"WMO {code}"),
        "humidity":  humidity,
        "wind_kph":  cw.get("windspeed"),
        "source":    "Open-Meteo",
    }


def _fetch_nws(config: dict) -> dict:
    """
    Input: config dict with LAT, LON
    Output: weather dict {temp_c, conditions, humidity, wind_kph, source}
    Details:
        Two-step NWS/NOAA call: points → forecastHourly → first period.
        Converts temperature from °F to °C. Parses wind speed string.
        Raises RuntimeError on non-200 or non-US coordinates (NWS returns 404).
    """
    points_url = f"https://api.weather.gov/points/{config['LAT']},{config['LON']}"
    r1 = _requests.get(points_url, timeout=_TIMEOUT,
                        headers={"User-Agent": "SHSE/1.0 (eyeclept@pm.me)"})
    if r1.status_code != 200:
        raise RuntimeError(f"NWS /points returned {r1.status_code} — may be non-US coordinates")
    forecast_url = r1.json()["properties"]["forecastHourly"]

    r2 = _requests.get(forecast_url, timeout=_TIMEOUT,
                        headers={"User-Agent": "SHSE/1.0 (eyeclept@pm.me)"})
    if r2.status_code != 200:
        raise RuntimeError(f"NWS forecast returned {r2.status_code}")
    periods = r2.json()["properties"]["periods"]
    if not periods:
        raise RuntimeError("NWS forecast has no periods")

    period = periods[0]
    temp_f = period.get("temperature")
    temp_c = round((temp_f - 32) * 5 / 9, 1) if temp_f is not None else None

    wind_str = period.get("windSpeed", "")
    wind_kph = None
    m = _RE_NWS_WIND.search(wind_str)
    if m:
        wind_kph = round(float(m.group(1)) * 1.60934, 1)

    return {
        "temp_c":    temp_c,
        "conditions":period.get("shortForecast", "unknown"),
        "humidity":  None,
        "wind_kph":  wind_kph,
        "source":    "NWS/NOAA",
    }


def _build_config() -> dict:
    """Read weather-related env vars into a single config dict."""
    return {
        "HA_URL":               os.environ.get("HA_URL", ""),
        "HA_TOKEN":             os.environ.get("HA_TOKEN", ""),
        "HA_WEATHER_ENTITY":    os.environ.get("HA_WEATHER_ENTITY", "weather.home"),
        "INFLUXDB_URL":         os.environ.get("INFLUXDB_URL", ""),
        "INFLUXDB_TOKEN":       os.environ.get("INFLUXDB_TOKEN", ""),
        "INFLUXDB_ORG":         os.environ.get("INFLUXDB_ORG", ""),
        "INFLUXDB_BUCKET":      os.environ.get("INFLUXDB_BUCKET", ""),
        "INFLUXDB_MEASUREMENT": os.environ.get("INFLUXDB_MEASUREMENT", "weather"),
        "LAT":                  os.environ.get("LAT", ""),
        "LON":                  os.environ.get("LON", ""),
    }


_ADAPTERS = [
    ("ha",         lambda cfg: bool(cfg["HA_URL"] and cfg["HA_TOKEN"]),         _fetch_ha),
    ("influx",     lambda cfg: bool(cfg["INFLUXDB_URL"] and cfg["INFLUXDB_TOKEN"]), _fetch_influx),
    ("open_meteo", lambda cfg: bool(cfg["LAT"] and cfg["LON"]),                 _fetch_open_meteo),
    ("nws",        lambda cfg: bool(cfg["LAT"] and cfg["LON"]),                 _fetch_nws),
]


def get_weather() -> Optional[dict]:
    """
    Input: None (reads env vars via _build_config)
    Output: weather dict or None
    Details:
        Iterates adapters in priority order. Returns on first success.
        Logs WARNING for each failed adapter before continuing.
        Returns None if all adapters fail or none are configured.
    """
    config = _build_config()
    for name, is_configured, fetch_fn in _ADAPTERS:
        if not is_configured(config):
            continue
        try:
            result = fetch_fn(config)
            return result
        except Exception:
            logger.warning("Weather adapter '%s' failed", name, exc_info=True)
    return None


def _format_weather(result: dict) -> str:
    """
    Input: weather dict from an adapter
    Output: human-readable summary string
    """
    parts = []
    if result.get("temp_c") is not None:
        parts.append(f"{result['temp_c']}°C")
    if result.get("conditions"):
        parts.append(result["conditions"])
    if result.get("humidity") is not None:
        parts.append(f"Humidity: {result['humidity']}%")
    if result.get("wind_kph") is not None:
        parts.append(f"Wind: {result['wind_kph']} km/h")
    return " · ".join(parts) if parts else "Weather data unavailable"


def build_weather_card(q: str) -> tuple:
    """
    Input: q — raw search query string
    Output: (answer_card dict, ai_context str) or (None, None)
    Details:
        Entry point for the inline dispatcher. Detects, fetches, and returns
        a structured answer_card and ai_context string.
    """
    if not detect_weather_query(q):
        return None, None

    result = get_weather()
    if result is None:
        return None, None

    body = _format_weather(result)
    answer_card = {
        "type":   "weather",
        "label":  "Current Weather",
        "body":   body,
        "source": result["source"],
    }
    ai_context = f"Weather: {body}"
    return answer_card, ai_context


if __name__ == "__main__":
    pass
