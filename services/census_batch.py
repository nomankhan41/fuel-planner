"""US Census Geocoder (free, no key) - batch address → lat/lng.

Endpoint: https://geocoding.geo.census.gov/geocoder/locations/addressbatch
Accepts up to 10,000 rows per POST as a CSV (id,street,city,state,zip).
Returns a CSV; "Match" rows contain "lng,lat" in a single field.

This runs ONCE per data import, not per request, so it's fine that it's slow.
"""
import csv
import io
import logging

import requests
from django.conf import settings

log = logging.getLogger("fuel_planner")


def geocode_batch(rows):
    """Send one batch POST to the Census geocoder.

    `rows`: iterable of (id, street, city, state) tuples; id must round-trip
            back to the caller so matched coordinates can be assigned.
    Returns: dict[id] = (lat, lng) for every matched row (unmatched ids omitted).
    """
    payload = io.StringIO()
    writer = csv.writer(payload)
    count = 0
    for sid, street, city, state in rows:
        # Census is picky about commas inside the street field, so strip them.
        writer.writerow([sid, (street or "").replace(",", " "), city, state, ""])
        count += 1
    if count == 0:
        return {}
    log.info("census batch call rows=%d", count)
    resp = requests.post(
        settings.CENSUS_BATCH_URL,
        files={"addressFile": ("addrs.csv", payload.getvalue(), "text/csv")},
        data={"benchmark": "Public_AR_Current"},
        timeout=settings.CENSUS_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return parse_response(resp.text)


def parse_response(text: str) -> dict:
    """Parse the Census CSV reply. Returns dict[id] -> (lat, lng) for matched rows only."""
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 6:
            continue
        sid, _addr, status = row[0], row[1], row[2]
        if status != "Match":
            continue
        # Column 5 holds "longitude,latitude".
        coords = row[5]
        if "," not in coords:
            continue
        try:
            lng_s, lat_s = coords.split(",", 1)
            out[sid] = (float(lat_s), float(lng_s))
        except ValueError:
            continue
    return out
