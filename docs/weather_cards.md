# Weather Answer Cards

Inline answer cards for weather queries. Data is fetched from one of four
configured sources (tried in priority order). All sources are optional — if
none are configured the card is silently suppressed. Results appear above
BM25 search results and are injected into `ai_context`.

---

## Detection Keywords

Any query containing one of the following keywords (case-insensitive,
word-boundary match) triggers a weather lookup:

`weather`, `temperature`, `how hot`, `how cold`, `forecast`, `will it rain`,
`humidity`, `wind speed`, `feels like`, `raining`, `snowing`, `sunny`, `cloudy`

---

## Source Priority

Sources are tried in this order. The first one that returns data wins;
all others are skipped.

| Priority | Source | Required env vars |
|---|---|---|
| 1 | Home Assistant | `HA_URL`, `HA_TOKEN`, `HA_WEATHER_ENTITY` (default: `weather.home`) |
| 2 | InfluxDB | `INFLUXDB_URL`, `INFLUXDB_TOKEN`, `INFLUXDB_ORG`, `INFLUXDB_BUCKET`, `INFLUXDB_MEASUREMENT` |
| 3 | Open-Meteo | `LAT`, `LON` |
| 4 | NWS/NOAA | `LAT`, `LON` (US coordinates only) |

If all adapters fail or none are configured, the card is suppressed and
BM25 results render normally. Failed adapters log at `WARNING`.

---

## Required Env Vars per Source

### Home Assistant
```env
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your_long_lived_access_token
HA_WEATHER_ENTITY=weather.home   # optional, defaults to weather.home
```

Create a Long-Lived Access Token in Home Assistant under
Profile → Security → Long-Lived Access Tokens.

### InfluxDB
```env
INFLUXDB_URL=http://influx:8086
INFLUXDB_TOKEN=your_influxdb_token
INFLUXDB_ORG=myorg
INFLUXDB_BUCKET=sensors
INFLUXDB_MEASUREMENT=weather
```

The Flux query fetches the last value from each field in the past hour.
Field names must include at least `temperature`; `humidity` and `wind_speed`
are optional.

Install the client: `pip install influxdb-client`

### Open-Meteo (no API key)
```env
LAT=51.5
LON=-0.1
```

### NWS/NOAA (no API key, US only)
```env
LAT=40.7
LON=-74.0
```

NWS returns a 404 for non-US coordinates — the adapter raises `RuntimeError`
which causes `get_weather()` to fall through to the next source if any.

---

## WMO Weather Code Reference

Open-Meteo uses WMO weather interpretation codes. Selected codes:

| Code | Condition |
|---|---|
| 0 | Clear sky |
| 1 / 2 / 3 | Mainly clear / Partly cloudy / Overcast |
| 45 / 48 | Foggy / Icy fog |
| 51 / 53 / 55 | Light / Moderate / Dense drizzle |
| 61 / 63 / 65 | Slight / Moderate / Heavy rain |
| 71 / 73 / 75 | Slight / Moderate / Heavy snow |
| 80 / 81 / 82 | Slight / Moderate / Violent rain showers |
| 95 | Thunderstorm |
| 96 / 99 | Thunderstorm with hail |

Unknown codes are displayed as `WMO <code>`.

---

## `ai_context` Injection

When a weather card is shown, the formatted summary is prepended to
`ai_context` as:

```
Weather: 22°C · Mainly clear · Humidity: 55% · Wind: 15 km/h
```

---

## Known Limitations

- All adapters use a fixed 8-second HTTP timeout per request.
- NWS requires two HTTP round-trips (points → forecast) and is US-only.
- InfluxDB requires `influxdb-client` to be installed separately.
- CWOP (APRS-IS personal weather stations) is not supported — it uses a raw
  TCP socket protocol rather than HTTP. Add as a future enhancement if needed.
