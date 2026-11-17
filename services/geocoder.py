"""Place resolution: 'City, ST' or 'lat,lng' -> coordinates.

Primary source: OpenRouteService /geocode/search (needs ORS_API_KEY).
Fallback:      local data/us_cities.csv table.
Cache:         every ACCEPTED result lands in the GeocodeCache DB row, so each
               unique place is fetched from the API at most once ever.

Precision rule: the ORS/Pelias geocoder happily returns a coarse hit (the state
itself, the country) when nothing precise matches - "Nowhereville, TX" comes
back as "Texas, USA" with layer=region. We refuse anything that isn't a
specific place (see PRECISE_LAYERS below), and for "City, ST" input we also
check the result's state. Rejected results are NEVER cached, so a later data
update that adds the place can still succeed.
"""
import logging
import re
from dataclasses import dataclass, field

import requests
from django.conf import settings

from . import local_places
from .exceptions import GeocodingServiceError, InvalidInput, PlaceNotFound
from .text import US_STATES, query_key, state_code

log = logging.getLogger("fuel_planner")

_COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_US_BOXES = [(24.0, 49.6, -125.0, -66.5), (51.0, 71.5, -180.0, -129.0), (18.5, 22.5, -161.0, -154.5)]

# Pelias "layer" values that represent a specific, routable place. Anything
# coarser (region, country, macrocounty) is treated as no result.
PRECISE_LAYERS = {
    "venue", "address", "street", "postalcode",
    "neighbourhood", "borough", "localadmin", "locality",
}


@dataclass
class Place:
    label: str
    lat: float
    lng: float
    source: str  # "cache", "ors", "local", "coords"


@dataclass
class Resolver:
    """Resolve several places in one trip and track where each came from."""
    api_calls: int = 0
    sources: list = field(default_factory=list)

    def resolve(self, text: str) -> Place:
        if not isinstance(text, str) or not text.strip():
            raise InvalidInput("Location must be a non-empty string.")

        # 1) Direct coordinates: no API call, no cache row needed.
        m = _COORD_RE.match(text)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if not _in_usa(lat, lng):
                raise InvalidInput(f"Coordinates {lat},{lng} are not inside the USA.")
            p = Place(label=f"{lat:.5f},{lng:.5f}", lat=lat, lng=lng, source="coords")
            self.sources.append(p.source)
            return p

        # 2) DB cache: we may have resolved this exact query before.
        from stations.models import GeocodeCache
        key = query_key(text)
        try:
            row = GeocodeCache.objects.get(query_key=key)
            p = Place(label=row.label, lat=row.lat, lng=row.lng, source="cache")
            self.sources.append(p.source)
            return p
        except GeocodeCache.DoesNotExist:
            pass

        # What state was asked for? Used to reject off-state matches below.
        expected_state = _expected_state(text)

        # 3) External API first (OpenRouteService geocoding).
        if settings.ORS_API_KEY:
            try:
                hit = _ors_search(text, expected_state)
                if hit:
                    label, lat, lng = hit
                    self.api_calls += 1
                    _store_cache(key, label, lat, lng, "ors")
                    p = Place(label=label, lat=lat, lng=lng, source="ors")
                    self.sources.append(p.source)
                    return p
            except RequestError as exc:
                log.warning("geocoder: ORS failed, falling back to local table (%s)", exc)
                self.api_calls += 1
            except NoResult:
                # Nothing precise enough came back; try the local table before giving up.
                self.api_calls += 1

        # 4) Local table fallback.
        hit = local_places.lookup_city(text)
        if hit:
            label, lat, lng = hit
            _store_cache(key, label, lat, lng, "local")
            p = Place(label=label, lat=lat, lng=lng, source="local")
            self.sources.append(p.source)
            return p

        if settings.ORS_API_KEY:
            raise PlaceNotFound(f"Could not find {text!r}.")
        raise PlaceNotFound(f"Could not find {text!r}. Set ORS_API_KEY to enable API geocoding.")


# ---------------------------------------------------------------------------
# OpenRouteService /geocode/search

class RequestError(Exception):
    pass


class NoResult(Exception):
    pass


def _expected_state(text: str):
    """Return the 2-letter state code when input is 'City, ST' / 'City, State', else None."""
    if "," not in text:
        return None
    _city, _, tail = text.rpartition(",")
    return state_code(tail.strip())


def _ors_search(text: str, expected_state):
    """Call ORS geocoding once. Returns (label, lat, lng) only if the result is PRECISE.

    Raises NoResult when the API answered but with nothing specific enough
    (region, country, or wrong state). Never cached.
    """
    url = settings.ORS_GEOCODE_URL
    # size=3 so we can scan a couple of candidates and skip the coarse ones.
    params = {"api_key": settings.ORS_API_KEY, "text": text,
              "boundary.country": "US", "size": 3}
    log.info("geocoding api call provider=ors text=%r", text)
    try:
        resp = requests.get(url, params=params, timeout=settings.ROUTING_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise RequestError(str(exc)) from exc
    if resp.status_code >= 500 or resp.status_code in (403, 429):
        raise RequestError(f"HTTP {resp.status_code}")
    if resp.status_code >= 400:
        raise NoResult(f"HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise RequestError(f"invalid JSON: {exc}") from exc

    for feat in (data.get("features") or []):
        props = feat.get("properties") or {}
        layer = props.get("layer")
        if layer not in PRECISE_LAYERS:
            # Region/country/macrocounty - too coarse, skip.
            continue
        if expected_state and props.get("region_a"):
            if props["region_a"].upper() != expected_state:
                continue
        try:
            lng, lat = feat["geometry"]["coordinates"]
        except (KeyError, TypeError, ValueError):
            continue
        if not _in_usa(lat, lng):
            continue
        label = props.get("label") or text
        return (label, float(lat), float(lng))

    raise NoResult("no precise feature")


def _store_cache(key: str, label: str, lat: float, lng: float, source: str):
    from stations.models import GeocodeCache
    GeocodeCache.objects.update_or_create(
        query_key=key, defaults={"label": label, "lat": lat, "lng": lng, "source": source},
    )


def _in_usa(lat: float, lng: float) -> bool:
    return any(a <= lat <= b and c <= lng <= d for a, b, c, d in _US_BOXES)
