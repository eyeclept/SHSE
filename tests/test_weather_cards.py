"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for task 17c — weather answer card detection and adapter logic.
    All external HTTP calls are mocked with unittest.mock. No real network
    requests are made. InfluxDB tests mock the InfluxDBClient.
"""
# Imports
import logging
from unittest.mock import MagicMock, patch

import pytest

from flask_app.services.weather_cards import (
    _fetch_ha,
    _fetch_nws,
    _fetch_open_meteo,
    _format_weather,
    build_weather_card,
    detect_weather_query,
    get_weather,
)

# Globals
logger = logging.getLogger(__name__)

_HA_CONFIG = {
    "HA_URL": "http://homeassistant.local:8123",
    "HA_TOKEN": "test_token",
    "HA_WEATHER_ENTITY": "weather.home",
}

_INFLUX_CONFIG = {
    "INFLUXDB_URL": "http://influx:8086",
    "INFLUXDB_TOKEN": "token",
    "INFLUXDB_ORG": "myorg",
    "INFLUXDB_BUCKET": "sensors",
    "INFLUXDB_MEASUREMENT": "weather",
}

_GEO_CONFIG = {"LAT": "51.5", "LON": "-0.1"}


# ── detect_weather_query ───────────────────────────────────────────────────────

def test_detect_weather_true():
    assert detect_weather_query("weather in london") is True


def test_detect_weather_temperature():
    assert detect_weather_query("what is the temperature outside") is True


def test_detect_weather_forecast():
    assert detect_weather_query("forecast for tomorrow") is True


def test_detect_weather_false():
    assert detect_weather_query("human anatomy") is False


def test_detect_weather_false_plain_digit():
    assert detect_weather_query("2 + 2") is False


# ── HA adapter ─────────────────────────────────────────────────────────────────

def _make_ha_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "state": "sunny",
        "attributes": {
            "temperature": 22.5,
            "humidity": 55,
            "wind_speed": 15.0,
        },
    }
    return mock_resp


def test_ha_adapter_shape():
    with patch("flask_app.services.weather_cards._requests.get", return_value=_make_ha_response()):
        result = _fetch_ha(_HA_CONFIG)
    assert result["temp_c"] == 22.5
    assert result["conditions"] == "sunny"
    assert result["humidity"] == 55
    assert result["wind_kph"] == 15.0
    assert result["source"] == "Home Assistant"


def test_ha_adapter_non_200_raises():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch("flask_app.services.weather_cards._requests.get", return_value=mock_resp):
        with pytest.raises(RuntimeError):
            _fetch_ha(_HA_CONFIG)


# ── InfluxDB adapter ───────────────────────────────────────────────────────────

def _make_influx_tables():
    """Build a minimal mock InfluxDB result matching what query_api().query() returns."""
    record = MagicMock()
    record.get_field.side_effect = ["temperature", "humidity", "wind_speed", "conditions"]
    record.get_value.side_effect = [19.0, 60, 10.5, "overcast"]

    table_temp = MagicMock()
    table_temp.records = [_make_influx_record("temperature", 19.0)]

    table_hum = MagicMock()
    table_hum.records = [_make_influx_record("humidity", 60)]

    table_wind = MagicMock()
    table_wind.records = [_make_influx_record("wind_speed", 10.5)]

    table_cond = MagicMock()
    table_cond.records = [_make_influx_record("conditions", "overcast")]

    return [table_temp, table_hum, table_wind, table_cond]


def _make_influx_record(field, value):
    r = MagicMock()
    r.get_field.return_value = field
    r.get_value.return_value = value
    return r


def test_influx_adapter_shape():
    mock_client = MagicMock()
    mock_client.query_api.return_value.query.return_value = _make_influx_tables()

    from flask_app.services import weather_cards as _wc
    with patch.dict("sys.modules", {"influxdb_client": MagicMock(InfluxDBClient=lambda **kw: mock_client)}):
        # Re-import inside the patch so conditional import resolves
        import importlib
        import sys
        # Directly call the private function with a mock client injected
        with patch("flask_app.services.weather_cards._requests"):
            # Build expected behaviour manually
            from flask_app.services.weather_cards import _fetch_influx
            # Patch influxdb_client at the sys.modules level
            sys.modules.setdefault("influxdb_client", MagicMock())
            sys.modules["influxdb_client"].InfluxDBClient = lambda **kw: mock_client
            result = _fetch_influx(_INFLUX_CONFIG)

    assert result["temp_c"] == 19.0
    assert result["humidity"] == 60
    assert result["source"] == "InfluxDB"


# ── Open-Meteo adapter ─────────────────────────────────────────────────────────

def _make_open_meteo_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "current_weather": {
            "temperature": 18.0,
            "weathercode": 1,
            "windspeed": 12.0,
        },
        "hourly": {
            "relativehumidity_2m": [65, 64, 63],
        },
    }
    return mock_resp


def test_open_meteo_adapter_shape():
    with patch("flask_app.services.weather_cards._requests.get", return_value=_make_open_meteo_response()):
        result = _fetch_open_meteo(_GEO_CONFIG)
    assert result["temp_c"] == 18.0
    assert result["conditions"] == "Mainly clear"  # WMO code 1
    assert result["humidity"] == 65
    assert result["wind_kph"] == 12.0
    assert result["source"] == "Open-Meteo"


def test_open_meteo_non_200_raises():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("flask_app.services.weather_cards._requests.get", return_value=mock_resp):
        with pytest.raises(RuntimeError):
            _fetch_open_meteo(_GEO_CONFIG)


# ── NWS adapter ────────────────────────────────────────────────────────────────

def _make_nws_responses():
    r1 = MagicMock()
    r1.status_code = 200
    r1.json.return_value = {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/X/Y/forecast/hourly"}}

    r2 = MagicMock()
    r2.status_code = 200
    r2.json.return_value = {
        "properties": {
            "periods": [{
                "temperature": 68,
                "shortForecast": "Partly Cloudy",
                "windSpeed": "10 mph",
            }]
        }
    }
    return [r1, r2]


def test_nws_adapter_shape():
    responses = _make_nws_responses()
    with patch("flask_app.services.weather_cards._requests.get", side_effect=responses):
        result = _fetch_nws(_GEO_CONFIG)
    assert result["temp_c"] == pytest.approx(20.0, abs=0.1)
    assert result["conditions"] == "Partly Cloudy"
    assert result["wind_kph"] is not None
    assert result["source"] == "NWS/NOAA"


def test_nws_non_200_points_raises():
    r = MagicMock()
    r.status_code = 404
    with patch("flask_app.services.weather_cards._requests.get", return_value=r):
        with pytest.raises(RuntimeError):
            _fetch_nws(_GEO_CONFIG)


# ── get_weather ────────────────────────────────────────────────────────────────

def test_get_weather_falls_through_on_failure():
    """HA configured but fails → Open-Meteo succeeds."""
    env = {
        "HA_URL": "http://ha", "HA_TOKEN": "tok", "HA_WEATHER_ENTITY": "weather.home",
        "LAT": "51.5", "LON": "-0.1",
        "INFLUXDB_URL": "", "INFLUXDB_TOKEN": "", "INFLUXDB_ORG": "",
        "INFLUXDB_BUCKET": "", "INFLUXDB_MEASUREMENT": "weather",
    }
    ha_fail = MagicMock()
    ha_fail.status_code = 500
    om_ok = _make_open_meteo_response()

    with patch("flask_app.services.weather_cards._build_config", return_value=env):
        with patch("flask_app.services.weather_cards._requests.get", side_effect=[ha_fail, om_ok]):
            result = get_weather()

    assert result is not None
    assert result["source"] == "Open-Meteo"


def test_get_weather_returns_none_when_all_fail():
    env = {
        "HA_URL": "http://ha", "HA_TOKEN": "tok", "HA_WEATHER_ENTITY": "weather.home",
        "LAT": "", "LON": "",
        "INFLUXDB_URL": "", "INFLUXDB_TOKEN": "", "INFLUXDB_ORG": "",
        "INFLUXDB_BUCKET": "", "INFLUXDB_MEASUREMENT": "weather",
    }
    ha_fail = MagicMock()
    ha_fail.status_code = 503

    with patch("flask_app.services.weather_cards._build_config", return_value=env):
        with patch("flask_app.services.weather_cards._requests.get", return_value=ha_fail):
            result = get_weather()

    assert result is None


def test_get_weather_logs_warning_on_failure(caplog):
    env = {
        "HA_URL": "http://ha", "HA_TOKEN": "tok", "HA_WEATHER_ENTITY": "weather.home",
        "LAT": "", "LON": "",
        "INFLUXDB_URL": "", "INFLUXDB_TOKEN": "", "INFLUXDB_ORG": "",
        "INFLUXDB_BUCKET": "", "INFLUXDB_MEASUREMENT": "weather",
    }
    ha_fail = MagicMock()
    ha_fail.status_code = 503

    with patch("flask_app.services.weather_cards._build_config", return_value=env):
        with patch("flask_app.services.weather_cards._requests.get", return_value=ha_fail):
            with caplog.at_level(logging.WARNING, logger="flask_app.services.weather_cards"):
                get_weather()

    assert any("failed" in r.message.lower() for r in caplog.records)


# ── build_weather_card ─────────────────────────────────────────────────────────

def test_build_weather_card_shape():
    with patch("flask_app.services.weather_cards.get_weather", return_value={
        "temp_c": 20.0, "conditions": "Sunny", "humidity": 50, "wind_kph": 10.0, "source": "Open-Meteo"
    }):
        card, ctx = build_weather_card("what's the weather")
    assert card is not None
    assert card["type"] == "weather"
    assert card["label"] == "Current Weather"
    assert "20" in card["body"]
    assert card["source"] == "Open-Meteo"
    for key in ("type", "label", "body", "source"):
        assert key in card
    assert ctx is not None and "weather" in ctx.lower()


def test_build_weather_card_no_match():
    card, ctx = build_weather_card("human anatomy")
    assert card is None
    assert ctx is None


def test_build_weather_card_no_source():
    with patch("flask_app.services.weather_cards.get_weather", return_value=None):
        card, ctx = build_weather_card("weather")
    assert card is None
    assert ctx is None


if __name__ == "__main__":
    pass
