# S08 — Data sources: US Regional Weather & Climate Trends

**Date:** 2026-07-04 · **Type:** Data-source spec · **Status:** 🟡 PLANNED
**Requirements:** binding — [`_engineering_requirements.md`](_engineering_requirements.md)
(public-sources-only: **free, documented HTTP APIs, no scraping**).
**For dataset:** [`s06-first-dataset-us-regional-weather.md`](s06-first-dataset-us-regional-weather.md).

**Purpose.** Pin the exact, free, **API-only** sources that feed the US Regional Weather &
Climate Trends dataset, with real base URLs, auth, request structure, and example
request/response — plus the datavibes adapter each maps onto. Every operation the dataset
promises — **aggregates, anomalies, rolling averages, correlations** — is served by one of
these endpoints; none require HTML scraping.

---

## Source inventory (all free, all JSON/CSV over HTTPS)

| # | Source | Base URL | Auth | Free-tier limit | Role |
|---|---|---|---|---|---|
| A | **NCEI Access Data Service v1** | `https://www.ncei.noaa.gov/access/services/data/v1` | **none** | fair-use | Historical daily summaries (GHCND) — the backbone |
| B | **NCEI Climate Normals** (via A) | `https://www.ncei.noaa.gov/access/services/data/v1` | **none** | fair-use | 1991–2020 baseline for **anomalies** |
| C | **NCEI Search Service v1** | `https://www.ncei.noaa.gov/access/services/search/v1/data` | **none** | fair-use | Station discovery by bounding box |
| D | **NCEI CDO API v2** (alt. to A) | `https://www.ncdc.noaa.gov/cdo-web/api/v2` | **token** (free) | 5 req/s, 10k/day | Token-gated equivalent; paging demo |
| E | **NOAA weather.gov API** | `https://api.weather.gov` | **none** (User-Agent required) | fair-use | Current observations to freshen "today" |
| F | **OpenWeatherMap** | `https://api.openweathermap.org` | **appid** (free) | 60/min, 1M/month | Current conditions + geocoding fallback |

> **A + B are the primary path** (no key, bulk historical + baseline). E/F add same-day
> freshness. C is discovery. D is the token/paging alternative to A (kept as the reference
> for `paged_http_json`). No source here is scraped — each is a published API.

---

## A. NCEI Access Data Service — daily summaries (GHCND)

The backbone: historical daily station observations, no token.

**Endpoint**
```
GET https://www.ncei.noaa.gov/access/services/data/v1
```
**Key parameters**
| Param | Example | Meaning |
|---|---|---|
| `dataset` | `daily-summaries` | GHCND daily |
| `dataTypes` | `TMAX,TMIN,PRCP` | vars (also `TAVG,SNOW,SNWD,AWND`) |
| `stations` | `USW00094728` | one or more GHCND station IDs |
| `startDate` / `endDate` | `2025-01-01` / `2025-12-31` | inclusive range (`YYYY-MM-DD`) |
| `boundingBox` | `41.1,-74.3,40.5,-73.7` | `north,west,south,east` (alt. to `stations`) |
| `units` | `metric` | `metric` or `standard` |
| `format` | `json` | `json` / `csv` |
| `includeStationName` / `includeStationLocation` | `true` | attach names + lat/lon |

**Example request**
```bash
curl -G 'https://www.ncei.noaa.gov/access/services/data/v1' \
  --data-urlencode 'dataset=daily-summaries' \
  --data-urlencode 'dataTypes=TMAX,TMIN,PRCP' \
  --data-urlencode 'stations=USW00094728' \
  --data-urlencode 'startDate=2025-06-01' \
  --data-urlencode 'endDate=2025-06-03' \
  --data-urlencode 'units=metric' \
  --data-urlencode 'includeStationName=true' \
  --data-urlencode 'includeStationLocation=true' \
  --data-urlencode 'format=json'
```
**Example response** (trimmed)
```json
[
  {"DATE":"2025-06-01","STATION":"USW00094728","NAME":"NY CITY CENTRAL PARK, NY US",
   "LATITUDE":"40.7789","LONGITUDE":"-73.9692","TMAX":"27.2","TMIN":"18.3","PRCP":"0.0"},
  {"DATE":"2025-06-02","STATION":"USW00094728","NAME":"NY CITY CENTRAL PARK, NY US",
   "LATITUDE":"40.7789","LONGITUDE":"-73.9692","TMAX":"24.4","TMIN":"17.8","PRCP":"5.6"}
]
```
**datavibes mapping** — built-in `http_csv` (use `format=csv`) or `http_json`:
```yaml
- type: http_json
  url: https://www.ncei.noaa.gov/access/services/data/v1
  select: "$[*]"
  params:
    dataset: daily-summaries
    dataTypes: TMAX,TMIN,PRCP
    stations: "${GHCND_STATIONS}"      # comma list, from config/env
    startDate: "${LOOKBACK_START}"     # generator injects (clock - lookback)
    endDate: "${TODAY}"
    units: metric
    includeStationName: "true"
    includeStationLocation: "true"
    format: json
```
Rows land as `DATE/STATION/TMAX/TMIN/PRCP/...` → `normalize` maps to the schema
(`region`←NAME/station group, `date`←DATE, `temp_*`, `precip_mm`←PRCP).

---

## B. NCEI Climate Normals — anomaly baseline (1991–2020)

Same service, a normals dataset. Gives the 30-year climatology so `anomaly()` can compute
`temp_anomaly_c = temp_mean_c − normal`.

**Example request**
```bash
curl -G 'https://www.ncei.noaa.gov/access/services/data/v1' \
  --data-urlencode 'dataset=normals-daily-1991-2020' \
  --data-urlencode 'dataTypes=DLY-TMAX-NORMAL,DLY-TMIN-NORMAL' \
  --data-urlencode 'stations=USW00094728' \
  --data-urlencode 'format=json'
```
**Example response** (trimmed)
```json
[{"STATION":"USW00094728","month":"06","day":"01",
  "DLY-TMAX-NORMAL":"26.1","DLY-TMIN-NORMAL":"17.4"}]
```
**datavibes mapping** — a **second `http_json` source**, then a `join` step on
`(station, month, day)` merges the normal onto each daily row; `derive: anomaly(...)`
consumes it. (Baselines change once per decade → the generator may cache B and refetch A
daily.)

---

## C. NCEI Search Service — station discovery (no hand-picked lists)

Discover stations inside a region by bounding box instead of maintaining a station file.

**Example request**
```bash
curl -G 'https://www.ncei.noaa.gov/access/services/search/v1/data' \
  --data-urlencode 'dataset=daily-summaries' \
  --data-urlencode 'bbox=41.1,-74.3,40.5,-73.7' \
  --data-urlencode 'startDate=2025-01-01' \
  --data-urlencode 'endDate=2025-12-31' \
  --data-urlencode 'limit=100'
```
Returns station stubs (`id`, `name`, geometry). **datavibes mapping** — used at
`new`/config-authoring time (or a preflight step) to fill `stations` for A; not part of the
daily hot path.

---

## D. NCEI CDO API v2 — token + paging (reference for `paged_http_json`)

The classic, token-gated equivalent to A. Kept here as the concrete example the S07
`paged_http_json` adapter is built against.

**Auth** — free token from `https://www.ncdc.noaa.gov/cdo-web/token`, sent as a header:
```
token: YOUR_NCEI_TOKEN
```
**Example request** (paged: `limit` ≤ 1000, `offset` cursor)
```bash
curl -H "token: $NCEI_TOKEN" -G 'https://www.ncdc.noaa.gov/cdo-web/api/v2/data' \
  --data-urlencode 'datasetid=GHCND' \
  --data-urlencode 'stationid=GHCND:USW00094728' \
  --data-urlencode 'datatypeid=TMAX' \
  --data-urlencode 'datatypeid=TMIN' \
  --data-urlencode 'datatypeid=PRCP' \
  --data-urlencode 'startdate=2025-06-01' \
  --data-urlencode 'enddate=2025-06-30' \
  --data-urlencode 'units=metric' \
  --data-urlencode 'limit=1000' \
  --data-urlencode 'offset=1'
```
**Example response** (trimmed — note `metadata.resultset` drives paging)
```json
{"metadata":{"resultset":{"offset":1,"count":93,"limit":1000}},
 "results":[
   {"date":"2025-06-01T00:00:00","datatype":"TMAX","station":"GHCND:USW00094728","value":27.2},
   {"date":"2025-06-01T00:00:00","datatype":"PRCP","station":"GHCND:USW00094728","value":0.0}
 ]}
```
**datavibes mapping** — `paged_http_json` (S07): `select: "$.results[*]"`, token header,
paging via `metadata.resultset.{offset,count,limit}`; long-form `datatype/value` → a pivot
in `aggregate`/`normalize`. Rate limits: **5 req/s, 10 000 req/day** → backoff on 429.

---

## E. NOAA weather.gov API — same-day observations (no key)

Freshens "today" before NCEI's archival lag. **No key; a `User-Agent` header is required.**

**Endpoints**
```
GET https://api.weather.gov/points/{lat},{lon}                         # resolve grid + stations
GET https://api.weather.gov/stations/{stationId}/observations?start=&end=
GET https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}/forecast
```
**Example request**
```bash
curl -H 'User-Agent: datavibes (contact@datavibes.example)' \
     -H 'Accept: application/geo+json' \
     'https://api.weather.gov/stations/KNYC/observations?start=2025-06-01T00:00:00Z&end=2025-06-02T00:00:00Z'
```
**Example response** (GeoJSON, trimmed)
```json
{"features":[
  {"properties":{"timestamp":"2025-06-01T12:51:00+00:00",
     "temperature":{"unitCode":"wmoUnit:degC","value":22.8},
     "precipitationLastHour":{"unitCode":"wmoUnit:mm","value":0}}}]}
```
**datavibes mapping** — `http_json`, `select: "$.features[*].properties"`, with a required
`headers.User-Agent`. Contributes today's `temp/precip`; `dedupe` collapses overlap with A.

---

## F. OpenWeatherMap — current conditions + geocoding

Convenience current-weather + city→lat/lon geocoding. Free `appid` (env-var only).

**Endpoints**
```
GET https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={key}&units=metric
GET https://api.openweathermap.org/geo/1.0/direct?q={city},US&limit=1&appid={key}
GET https://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={key}   # optional
```
**Example request**
```bash
curl -G 'https://api.openweathermap.org/data/2.5/weather' \
  --data-urlencode 'lat=40.7789' --data-urlencode 'lon=-73.9692' \
  --data-urlencode 'units=metric' --data-urlencode "appid=$OPENWEATHERMAP_API_KEY"
```
**Example response** (trimmed)
```json
{"name":"New York","coord":{"lat":40.78,"lon":-73.97},
 "main":{"temp":23.4,"temp_min":21.0,"temp_max":25.1,"humidity":61},
 "rain":{"1h":0.0},"dt":1749038400}
```
**datavibes mapping** — `http_json`, `select: "$"`, `params.appid: "${OPENWEATHERMAP_API_KEY}"`.
Secondary/fallback freshness; the pipeline runs without it if the key is absent.

---

## How the sources feed the four preprocessing operations

| Operation (dataset promise) | Fed by | datavibes step/helper |
|---|---|---|
| **Aggregates** | A (daily summaries) | `aggregate` (region×date mean temp, sum precip) |
| **Anomalies** | A minus **B (normals)** | `join` on (station, month, day) → `derive: anomaly(...)` |
| **Rolling averages** | A (daily series) | `derive: rolling_avg(temp_mean_c, 7)` |
| **Correlations** | A (temp + precip series) | `derive: rolling_corr(precip_mm, temp_mean_c, 30)` |
| same-day freshness | E, F | `dedupe` merges with A's latest |

---

## Secrets & config (env-var only, never committed)

| Var | Used by | Required? |
|---|---|---|
| `NCEI_TOKEN` | D (CDO v2) | optional — only if using the token path instead of A |
| `OPENWEATHERMAP_API_KEY` | F | optional — pipeline degrades gracefully without it |
| `DATAVIBES_USER_AGENT` | E (weather.gov) | required for E (set to a contact string) |

A/B/C need **no** secret. The daily cron runs on A+B alone if E/F keys are absent.

---

## Attribution & licensing

- **NOAA/NCEI** data — U.S. Government work, **public domain**; cite "NOAA National Centers
  for Environmental Information".
- **weather.gov** — public domain (NWS); `User-Agent` policy must be honoured.
- **OpenWeatherMap** — free tier under CC-BY-SA 4.0; attribute "Weather data provided by
  OpenWeather".

These strings populate `metadata.attribution` / `metadata.license` in the dataset's
`dataset.yaml`.

---

## Definition of done
- [ ] Every source above resolves to a **built-in** datavibes adapter (`http_json` /
      `http_csv` / `paged_http_json`) or the single S06 bespoke adapter — no scraping.
- [ ] Recorded (VCR-style) fixtures of A, B, E, F responses live in the dataset's tests so
      CI exercises parsing with **zero** live network.
- [ ] The four preprocessing operations each trace to a named source + step in the table above.
- [ ] Secrets are env-var only; the pipeline produces a valid snapshot from A+B with no keys set.
