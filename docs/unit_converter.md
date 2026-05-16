# Unit Converter Answer Cards

Inline answer cards for unit conversion queries. Computed locally using a
built-in factor table — no external service or LLM required. Results appear
above BM25 search results and are also injected into `ai_context`.

---

## Detection Pattern

Queries matching any of the following patterns (case-insensitive):

```
<number> <unit> to <unit>
<number> <unit> in <unit>
convert <number> <unit> to <unit>
convert <number> <unit> in <unit>
```

Examples:
- `5 km to miles`
- `convert 100 fahrenheit to celsius`
- `1 kg in lb`
- `60 mph to km/h`

---

## Supported Unit Families

### Length (base: metre)
`mm`, `cm`, `m`, `km`, `in`, `ft`, `yd`, `mi`, `nmi`
Aliases: `millimeter`, `centimeter`, `meter`, `kilometer`, `inch`, `foot`, `yard`, `mile`, `nautical mile`

### Mass (base: kilogram)
`mg`, `g`, `kg`, `t` (metric ton), `oz`, `lb`, `st` (stone), `ton` (short ton)
Aliases: `milligram`, `gram`, `kilogram`, `ounce`, `pound`, `lbs`

### Temperature (explicit formulas)
`C`, `F`, `K`
Aliases: `celsius`, `fahrenheit`, `kelvin`, `degrees celsius`, `degrees fahrenheit`

### Volume (base: litre)
`ml`, `l`, `fl oz`, `cup`, `pt`, `qt`, `gal`
Aliases: `milliliter`, `liter`, `fluid oz`, `pint`, `quart`, `gallon`

### Speed (base: m/s)
`m/s`, `km/h`, `mph`, `knot`
Aliases: `kph`, `kmh`, `miles per hour`, `knots`

### Data (base: byte)
`bit`, `byte`, `KB`, `MB`, `GB`, `TB` (1024-based, binary prefixes)

### Time (base: second)
`s`, `min`, `h`, `day`, `week`
Aliases: `sec`, `second`, `minute`, `hour`

### Area (base: square metre)
`mm²`/`mm2`, `cm²`/`cm2`, `m²`/`m2`, `km²`/`km2`, `in²`/`in2`, `ft²`/`ft2`, `ac` (acre), `ha` (hectare)

### Pressure (base: pascal)
`Pa`, `kPa`, `MPa`, `bar`, `psi`, `atm`

### Energy (base: joule)
`J`, `kJ`, `cal`, `kcal`, `Wh`, `kWh`

---

## Temperature Special-Casing

Temperature conversions do not use a multiplicative factor table because the
scales have different offsets. Explicit formulas are used:

| From | To | Formula |
|---|---|---|
| C | F | `v × 9/5 + 32` |
| C | K | `v + 273.15` |
| F | C | `(v − 32) × 5/9` |
| F | K | `(v − 32) × 5/9 + 273.15` |
| K | C | `v − 273.15` |
| K | F | `(v − 273.15) × 9/5 + 32` |

All conversions pass through Celsius as the intermediate unit.

---

## Precision Behaviour

Results are formatted with `:.6g` (6 significant figures, trailing zeros
dropped). This means:
- `1 km → 0.621371 mi` (not `0.62137119...`)
- `0 °C → 32 °F` (not `32.0000`)
- `1 GB → 1024 MB` (exact integer, no decimal)

---

## `ai_context` Injection

When a unit converter card is shown, the conversion is prepended to
`ai_context` as:

```
Unit conversion: 5 km = 3.10686 miles
```

---

## Known Limitations

- Compound units are not supported (`km/h` can be detected as a speed unit
  but expressions like `5 km/h per second` are not supported).
- Currency conversion is not included — exchange rates change constantly and
  require an external API.
- Data prefixes use binary (1024-based) rather than SI decimal (1000-based)
  multipliers. `1 GB = 1024 MB`, not `1000 MB`.
