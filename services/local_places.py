"""Local fallback place lookup (used when the geocoding API is unreachable).

Reads data/us_cities.csv (GeoNames + ZIP centroids), kept as a *fallback* so a brief
ORS outage doesn't take the whole API down. The primary place source is now the API.
"""
import csv
from functools import lru_cache

from django.conf import settings

from .text import US_STATES, city_key, state_code

CITIES_CSV = settings.BASE_DIR / "data" / "us_cities.csv"


@lru_cache(maxsize=1)
def _city_table() -> dict:
    table = {}
    with open(CITIES_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            table[(city_key(row["city"]), row["state"])] = (
                row["city"], float(row["lat"]), float(row["lng"]),
            )
    return table


def lookup_city(text: str):
    """Return (label, lat, lng) for 'City, ST' / 'City, State' or None if unknown."""
    if "," not in text:
        return None
    city, _, tail = text.rpartition(",")
    code = state_code(tail)
    if not code or not city.strip():
        return None
    hit = _city_table().get((city_key(city), code))
    if not hit:
        return None
    name, lat, lng = hit
    return (f"{name}, {code}", lat, lng)


def lookup_city_coords(city: str, state: str):
    """For the station importer's city-centroid fallback."""
    hit = _city_table().get((city_key(city), state))
    return (hit[1], hit[2]) if hit else None


def known_states_label(code: str) -> str:
    return US_STATES.get(code, code)
