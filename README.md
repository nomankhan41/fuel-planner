# Fuel Planner API

A Django REST API that takes a **start** and a **finish** location in the USA and returns:

- the driving **route** (GeoJSON) and a **map link**,
- the **cost-optimal fuel stops** for a vehicle with a **500-mile range**,
- the **total fuel cost** at **10 miles per gallon**.

It is designed around one firm rule from the assessment: **as few calls to free third-party APIs as possible**. A cold trip needs at most **3 external calls** (up to 2 for geocoding the start and finish, 1 for the driving route). A trip whose places have already been seen needs **1 call**. A repeat of an identical trip needs **0 calls**.

---

## Table of contents

- [Quick start](#quick-start)
- [How a request is answered](#how-a-request-is-answered)
- [External API budget](#external-api-budget)
- [External APIs used](#external-apis-used)
- [API reference](#api-reference)
- [Data pipeline](#data-pipeline)
- [Refreshing station data](#refreshing-station-data)
- [Fuel-stop optimization](#fuel-stop-optimization)
- [Project layout](#project-layout)
- [Configuration (.env)](#configuration-env)
- [Tests](#tests)
- [Docker](#docker)
- [Design rules (what the code holds itself to)](#design-rules-what-the-code-holds-itself-to)
- [Trade-offs and known limits](#trade-offs-and-known-limits)
- [Data credits](#data-credits)

---

## Quick start

```bash
# 1. Install
python -m venv .venv
.venv\Scripts\activate       # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

# 2. Configure. The defaults work with ZERO signup -- routing uses OSRM's public
#    demo server. If you want an OpenRouteService key (faster, dedicated), paste
#    it into .env next to ORS_API_KEY=.
cp .env.example .env

# 3. Database + station data
python manage.py migrate
python manage.py load_stations          # upsert ~6,600 US stations from the CSV
python manage.py geocode_stations       # fill in coordinates (US Census + city fallback)

# 4. Run
python manage.py runserver
```

Then:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/route/ \
     -H "Content-Type: application/json" \
     -d '{"start": "New York, NY", "finish": "Los Angeles, CA"}'
```

Open the `map_url` from the response in a browser to see the route and numbered fuel stops.

- **Tests:** `python manage.py test` (34 tests, all mocked, no network needed)
- **Docker:** `docker compose up --build`
- **Postman:** import `postman/fuel_planner.postman_collection.json`

Stack: Django 6.1.3 (latest stable), Django REST Framework, NumPy/SciPy. Routing via **OSRM (Open Source Routing Machine)** by default — a free C++ routing engine built on OpenStreetMap data, running on its public demo server with no API key required. **OpenRouteService** is supported as a drop-in alternative when a (free) API key is set. Geocoding via OpenRouteService (optional) with a local US cities table as the always-on fallback. US Census batch geocoder (no key) for station street addresses. Leaflet + Esri tiles for the map.

---

## How a request is answered

```
POST /api/v1/route/  {"start": "New York, NY", "finish": "Los Angeles, CA"}
    |
    v  routing/views.py          -> validates input, hands off, keeps no logic
    v  services/planner.py       -> orchestrates the next 6 steps
    |
  [1] resolve 'start' place      -> DB cache? -> ORS /geocode/search -> local fallback
  [2] resolve 'finish' place     -> DB cache? -> ORS /geocode/search -> local fallback
  [3] trip-cache lookup          -> same start+finish+flags seen before? return as-is
  [4] fetch route                -> OSRM (or ORS) directions (THE only call that changes per trip)
  [5] find stations near route   -> KD-tree, 10-mile corridor, mile markers
  [6] optimise purchases         -> dynamic programming over (station, fuel level)
    |
    v  return JSON + map_url, and cache the response for 24 h
```

Every outbound call is funnelled through one module (`services/geocoder.py` for geocoding, `services/routing_client.py` for directions). Steps 1 and 2 are each cached permanently in the DB, step 3 is cached for 24 hours, and the counts appear in the response so you can verify the API budget was respected.

---

## External API budget

The response's `meta` block tells the truth for every request:

```json
"meta": {
  "routing_provider": "osrm",
  "geocoding_calls":  0,
  "routing_calls":    0,
  "cached":           true,
  "place_sources":    ["cache", "cache"],
  "elapsed_ms":       1.2
}
```

| Trip kind                                              | Geocoding calls  | Routing calls | Total external calls |
| ------------------------------------------------------ | :--------------: | :-----------: | :------------------: |
| Cold trip, two fresh places                            |     up to 2      |       1       |       up to 3        |
| Cold trip, one place already seen                      |        1         |       1       |          2           |
| Cold trip, both places already seen (repeat city pair) |        0         |       1       |          1           |
| Repeat of the exact same trip (within 24 h)            |        0         |       0       |        **0**         |
| Coordinates input (`"40.71,-74.00"`)                   | 0 for that input |       1       |         1-2          |

The assessment asks for **1 ideal, 2-3 acceptable** routing calls. We make **exactly 1 routing call per unique trip, ever**, and the full response is cached so a repeat hit is served from disk in a millisecond.

---

## External APIs used

Three free APIs, each chosen for the "no cost, no key needed where possible" rule.

### 1. Routing — OSRM (default) / OpenRouteService (alternative)

**OSRM — Open Source Routing Machine** — https://project-osrm.org — is a free, open-source C++ routing engine built on OpenStreetMap data. Its public demo server at `router.project-osrm.org` needs **no API key**, so a reviewer can clone this repo and run it with zero signup.

**OpenRouteService** — https://openrouteservice.org — is a drop-in alternative. The free tier gives 2,000 requests/day on a dedicated (usually faster) server, and the same key also covers geocoding. Switching is one line in `.env`:

```
ROUTING_PROVIDER=ors
ORS_API_KEY=<your key>
```

Both providers implement the same `services/routing_client.py` interface. Each trip makes exactly **one** call to whichever provider is active.

### 2. Place geocoding — OpenRouteService (optional) with local fallback

Turning `"Dallas, TX"` (or a full address) into coordinates goes through OpenRouteService's `/geocode/search` endpoint when a key is set. Without a key, the local `data/us_cities.csv` table (GeoNames + ZIP centroids, 43,000+ US places) is used instead. Either way, every lookup is cached permanently in a `GeocodeCache` table — each unique query hits the API **at most once in the lifetime of the install**.

### 3. Station street-address geocoding — US Census Batch Geocoder

Run once per data refresh, not per request. **US Census Geocoder** — https://geocoding.geo.census.gov/geocoder — accepts up to 10,000 rows in a single POST and needs **no API key**. Addresses it can't match (highway exits like `"I-44, EXIT 283 & US-69"` usually come back `No_Match`) fall back to the station's city/state centroid from `data/us_cities.csv`.

---

## API reference

### `POST /api/v1/route/` (also `GET ?start=...&finish=...`)

| Field             | Type                  | Notes                                                                                                                                               |
| ----------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `start`           | string                | `"City, ST"`, `"City, State"`, a free-text address, or `"lat,lng"` inside the USA                                                                   |
| `finish`          | string                | same                                                                                                                                                |
| `start_tank_full` | bool, default `false` | `false`: the tank starts empty, so the cost covers **all** fuel for the trip. `true`: the tank starts full and only fuel bought en route is costed. |

**Response (shortened; numbers are illustrative):**

```json
{
  "trip_id": "3f1c...",
  "start": {
    "query": "New York, NY",
    "lat": 40.71427,
    "lng": -74.00597,
    "source": "cache"
  },
  "finish": {
    "query": "Los Angeles, CA",
    "lat": 34.05223,
    "lng": -118.24368,
    "source": "cache"
  },
  "distance_miles": 2789.4,
  "duration_hours": 41.2,
  "assumptions": {
    "max_range_miles": 500,
    "mpg": 10,
    "tank_gallons": 50,
    "start_tank_full": false,
    "corridor_miles": 10,
    "stop_penalty_usd": 5
  },
  "total_gallons": 278.9,
  "total_fuel_cost": 832.15,
  "average_price_on_route": 3.446,
  "savings_vs_average_price": 128.9,
  "fuel_stops": [
    {
      "stop": 1,
      "name": "...",
      "city": "...",
      "state": "NJ",
      "mile_marker": 0.0,
      "price_per_gallon": 3.099,
      "gallons": 50.0,
      "cost": 154.95,
      "lat": 40.85,
      "lng": -73.99,
      "geo_source": "address"
    }
  ],
  "route": { "type": "LineString", "coordinates": [[-74.006, 40.714], "..."] },
  "map_url": "http://127.0.0.1:8000/api/v1/route/3f1c.../map/",
  "meta": {
    "routing_provider": "osrm",
    "geocoding_calls": 0,
    "routing_calls": 1,
    "cached": false,
    "place_sources": ["local", "local"],
    "elapsed_ms": 812.4
  }
}
```

### `GET /api/v1/route/<trip_id>/map/`

A Leaflet page with the route, start/finish markers, and numbered fuel stops. Uses Esri's free World Street Map tiles — no API key. Served from the trip cache, so it costs zero extra calls.

### Errors

| Status | When                                                                  |
| ------ | --------------------------------------------------------------------- |
| 400    | Missing/invalid fields, unknown US state, coordinates outside the USA |
| 404    | A place name could not be resolved by the API or the local table      |
| 422    | No drivable route, or a stretch longer than 500 miles with no station |
| 502    | Routing (or geocoding, with no local fallback) failed entirely        |

---

## Data pipeline

The provided CSV has **no coordinates**, and its addresses are highway exits like `"I-44, EXIT 283 & US-69"`, so every truck stop needs geocoding. We run that offline so per-request work is tiny.

```
data/fuel-prices.csv  ──►  load_stations   ──►  Station rows (no coords yet)
                                                 │
                       geocode_stations  ◄───────┘
                              │
                              ├──► US Census Batch Geocoder (one POST, no key)
                              │       -> street-level coords where the address matches
                              │
                              └──► us_cities.csv fallback
                                      -> city-centroid coords for highway exits etc.
```

| Step                                                        | Rows      |
| ----------------------------------------------------------- | --------- |
| Rows in CSV                                                 | 8,151     |
| Canadian rows dropped (AB, BC, MB, NB, NS, ON, QC, SK, YT)  | 620       |
| Duplicate station IDs collapsed (kept the **lowest** price) | 905       |
| Unique US stations stored                                   | **6,626** |

Each station carries its `geo_source` (`"address"`, `"city_centroid"`, or empty for not-yet-geocoded) so you can tell at a glance how precise each coordinate is.

---

## Refreshing station data

Both commands are **idempotent**: run them on a schedule, in Docker, or after dropping a new CSV in `data/`.

**`python manage.py load_stations`**
Upserts into the Station table:

- adds stations that are new in the CSV,
- updates price/name/address for rows that changed,
- removes stations no longer in the CSV,
- when an _address_ changes, clears the station's coordinates so the next geocode pass redoes it,
- leaves everything else untouched, preserving the `geo_source` and `geocoded_at` metadata for unchanged stations.

Prints counts: `added`, `updated`, `removed`, `unchanged`, plus the CSV cleaning numbers above.

**`python manage.py geocode_stations`**
Looks for stations with no coordinates and tries, in order:

1. One batch POST to the free **US Census Geocoder** (up to 5,000 rows per POST by default; set `--batch-size` up to 10,000). No key needed.
2. For anything Census can't match (most truck-stop CSV rows look like `"I-44, EXIT 283 & US-69"` and come back `No_Match`), falls back to the **city/state centroid** from `data/us_cities.csv`.

**By default, the command also retries stations that previously fell back to a city centroid** (via a second Census pass), so running it on a host with outbound access will upgrade the approximations baked in by the offline Docker build. A re-sent station that still doesn't match keeps its existing centroid.

Flags:

- `--no-census` — skip the Census call entirely and use city centroids only (useful for offline / CI / tests).
- `--no-retry-fallback` — do **not** re-send existing `city_centroid` stations to Census; only geocode stations with no coordinates at all.

Each run prints counts (`matched_by_address`, `city_centroid_fallback`, `no_match`, `upgraded_from_city`) and resets the in-memory station index so new coordinates are picked up by the next request without a restart.

---

## Fuel-stop optimization

A **pure function** in `services/optimizer.py` (no Django, no network — easy to test):

- Fuel is tracked in whole miles of range (0-500).
- For every station in route order and every possible fuel level, we keep the cheapest cost to arrive there. At each station, we may buy any amount; between stations the tank drains by the distance driven.
- Walking back from the destination recovers the exact purchases. This is **O(stations × 501)** with NumPy — a few milliseconds for coast-to-coast.

**Stop penalty** (`STOP_PENALTY_USD`, default $5): a small per-stop "hassle cost" used **only when choosing stops**. It is never added to the reported fuel cost. Without it, the pure optimum will stop to buy 1 gallon to save a cent, which is nonsensical in practice; with it, a coast-to-coast route typically drops several near-zero-gallon stops for a trivial extra cost (example: ~5 fewer stops, under $2 more). Set it to 0 to recover the strict minimum cost.

An **independent reference solver** (exact DP with 10-mile steps, written separately from the production optimizer) validates the planner: on 40 random routes, the two match to 6 decimal places.

---

## Project layout

```
fuel_planner/
├── config/                              Django project (settings, urls, wsgi)
├── stations/
│   ├── models.py                        Station, GeocodeCache
│   └── management/commands/
│       ├── load_stations.py             upsert from CSV
│       └── geocode_stations.py          Census batch + city fallback
├── routing/                             views, serializers, URLs, Leaflet template
├── services/                            business logic (pure Python, no Django or network)
│   ├── geocoder.py                      ORS geocode + DB cache + local fallback
│   ├── local_places.py                  us_cities.csv fallback lookup
│   ├── routing_client.py                the only code that calls the directions API (OSRM or ORS)
│   ├── station_index.py                 in-memory stations + KD-tree
│   ├── station_importer.py              upsert logic
│   ├── census_batch.py                  US Census batch geocoder client + parser
│   ├── corridor.py                      stations near the route + mile markers
│   ├── optimizer.py                     dynamic programming
│   ├── planner.py                       orchestrates a single request
│   ├── geo.py                           distance / densify / simplify helpers
│   ├── text.py                          city-name normalisation, address hashing
│   └── exceptions.py                    domain errors with HTTP status codes
├── tests/                               34 tests, all mocked
├── data/
│   ├── fuel-prices.csv                  assessment data
│   └── us_cities.csv                    GeoNames + US ZIP centroids (fallback only)
├── tools/build_us_cities.py             one-off: rebuild data/us_cities.csv
├── postman/fuel_planner.postman_collection.json
├── Dockerfile  docker-compose.yml
├── requirements.txt  .env.example  .dockerignore  .gitignore
└── manage.py  README.md
```

---

## Configuration (.env)

| Variable                  | Default                            | Notes                                                                                                                                                                                                                                                                                                             |
| ------------------------- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ORS_API_KEY`             | –                                  | Free at openrouteservice.org; the one key covers directions **and** geocoding                                                                                                                                                                                                                                     |
| `ROUTING_PROVIDER`        | `ors` if a key is set, else `osrm` | **`osrm`**: Open Source Routing Machine (free C++ engine, OpenStreetMap data, public demo server, no API key needed). **`ors`**: OpenRouteService (dedicated server, free tier of 2,000 req/day, API key required). Both implement the same `services/routing_client.py` interface — switching is just this line. |
| `DJANGO_DEBUG`            | `False`                            | `.env.example` sets it to `true` for local dev                                                                                                                                                                                                                                                                    |
| `DJANGO_SECRET_KEY`       | throwaway dev key                  | Set this in production                                                                                                                                                                                                                                                                                            |
| `REDIS_URL`               | –                                  | Optional; when set, trip cache goes to Redis instead of the on-disk file cache                                                                                                                                                                                                                                    |
| `MAX_RANGE_MILES` / `MPG` | 500 / 10                           | Assessment values                                                                                                                                                                                                                                                                                                 |
| `CORRIDOR_MILES`          | 10                                 | Max distance from the route a station may sit                                                                                                                                                                                                                                                                     |
| `STOP_PENALTY_USD`        | 5                                  | 0 = pure cheapest                                                                                                                                                                                                                                                                                                 |
| `CACHE_SECONDS`           | 86400                              | Trip cache TTL                                                                                                                                                                                                                                                                                                    |

Caching: the default backend is **FileBasedCache** at `BASE_DIR/.cache`. This works across any number of gunicorn workers, survives restarts, and keeps the `map_url` valid no matter which worker rendered the trip. Set `REDIS_URL` to switch to Redis for production scale.

---

## Tests

34 tests, all **mocked**, no network needed:

```bash
python manage.py test
```

- **Optimizer** (`test_optimizer.py`): edge cases (short/long trips, empty tank, unreachable gaps, stop-penalty behaviour) + "DP matches an independent reference solver on 40 random routes".
- **Geocoder** (`test_geocoder.py`): first lookup calls the API once and stores it; second lookup makes 0 calls; variants ("St. Louis" vs "Saint Louis", different casing/spacing) collapse to one cache row; API failure falls back to the local table; coordinate input makes zero calls; **coarse API results (region/country-level) are rejected, wrong-state matches are rejected**, and rejected results are never cached.
- **Importer** (`test_importer.py`): initial import counts correctly; a re-run detects `added`/`updated`/`unchanged`; a changed address clears coords so geocoding reruns; removed stations are deleted.
- **Census parser / geocode command** (`test_census_parser.py`): matched rows get address coords, unmatched rows fall through to city centroids, re-run is a no-op; `--retry-fallback` (default) upgrades previously-city-centroid stations when Census matches; `--no-retry-fallback` leaves them alone.
- **API** (`test_api.py`): cold request counts 1 routing call + N geocoding calls, repeat is fully cached (`routing_calls=0`, `geocoding_calls=0`); map page works; error codes correct; **invalid JSON from the provider returns 502, not 500**.

---

## Docker

```bash
docker compose up --build
```

The image runs `migrate`, `load_stations`, and `geocode_stations --no-census` at build time so the container starts ready. Gunicorn runs one worker with four threads so the file-based cache stays internally consistent — scale out by setting `REDIS_URL` and raising the worker count in `Dockerfile`. After the stack is up, run `docker compose exec api python manage.py geocode_stations` to pull real street-level coordinates from the US Census (its `--retry-fallback` is on by default and will upgrade the city-centroid approximations baked in at build time).

---

## Design rules (what the code holds itself to)

- Views contain **no business logic**; they validate input and call `services/`.
- At most **one external routing call** per trip request; never inside a loop; the one caller is `services/routing_client.py`.
- All outbound calls are reported in `meta` so the budget can be verified from outside.
- Station data loads once per process (`services/station_index.py`); the DB is **not** touched during a route request.
- The optimizer is a **pure function**; tested without Django or network.
- Tunables live in `settings.FUEL_PLANNER` (env-overridable): range 500 mi, 10 mpg, corridor 10 mi, stop penalty $5.
- Validate all input; return clear 4xx errors (400/404/422) and 502 only when a provider breaks.
- Round numbers only when building the response.
- Every function gets a docstring and a test.
- No secrets in Git; `.env.example` stays current.

---

## Trade-offs and known limits

- **City-centroid fallback**: when the US Census geocoder can't match a highway-exit address, the station takes its city/state centroid. Good enough for a 10-mile corridor and 500-mile hops, and the `geo_source` field tells callers which coordinates are precise and which are approximate.
- **Detour distance** to reach a station is **not added** to the trip. The corridor is tight enough (10 mi) that this is usually under 2% of the trip.
- **USA only**: Canadian rows are excluded, and user input must resolve to a US place or US coordinates.
- **SQLite** is fine for 6,626 stations; swap in Postgres when there's more or when you want concurrent writes.
- **In-memory stations**: on a multi-process deploy, each worker loads its own copy (~500 KB). Fine until you have dozens of workers.
- **OSRM public demo server** is shared and sometimes slow; swap `ROUTING_PROVIDER=ors` with a free OpenRouteService key for a dedicated endpoint.

---

## Data credits

- **Fuel prices**: provided assessment file (`data/fuel-prices.csv`).
- **Routing (default)**: [OSRM — Open Source Routing Machine](https://project-osrm.org/) — free, open-source routing engine built on OpenStreetMap data. Public demo server at `router.project-osrm.org`, no API key required.
- **Routing + place geocoding (alternative)**: [OpenRouteService](https://openrouteservice.org/) (free tier, 2,000 requests/day).
- **Street-address geocoding**: [US Census Geocoder](https://geocoding.geo.census.gov/geocoder/) (free, no key).
- **City-centroid fallback**: [GeoNames](https://www.geonames.org/) (CC BY 4.0) + US ZIP data via the `zipcodes` Python package, pre-built into `data/us_cities.csv` by `tools/build_us_cities.py`.
- **Map tiles**: © [Esri](https://www.esri.com/) World Street Map (free for light use).
- **Map library**: [Leaflet](https://leafletjs.com/) 1.9.4.
