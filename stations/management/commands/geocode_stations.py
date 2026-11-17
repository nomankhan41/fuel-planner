"""Attach coordinates to stations that still need them.

Two-phase strategy, run on every refresh:
  1. Try the free US Census Batch Geocoder with the station's street address
     (one POST, up to 10,000 rows, no API key).
  2. Fall back to the station's city/state centroid for anything the Census
     geocoder could not match. Most truck-stop CSV rows look like
     "I-44, EXIT 283 & US-69" which Census returns as No_Match.

By default (when Census is enabled) the command ALSO re-sends stations
previously marked geo_source="city_centroid" so that running it after the
Docker --no-census build actually upgrades those approximations to real
street-level coordinates. Pass --no-retry-fallback to keep them as-is.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from services import census_batch, local_places
from services.station_index import reset_station_index
from stations.models import Station


class Command(BaseCommand):
    help = "Geocode stations that still need (or deserve better) coordinates."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=5000,
                            help="Rows per Census batch request (max 10000).")
        parser.add_argument("--no-census", action="store_true",
                            help="Skip Census; use city centroids only (offline / tests).")
        parser.add_argument("--no-retry-fallback", action="store_true",
                            help="Do NOT re-send existing city_centroid stations to Census.")

    def handle(self, *args, **opts):
        no_census = opts["no_census"]
        retry_fallback = not opts["no_retry_fallback"] and not no_census

        # Rows that still have no coordinates always go.
        needing = list(Station.objects.filter(lat__isnull=True))

        # Rows previously placed at a city centroid: optionally retry with Census
        # to try for a more precise fix.
        retry = (list(Station.objects.filter(geo_source="city_centroid"))
                 if retry_fallback else [])

        pending = needing + retry
        if not pending:
            self.stdout.write(self.style.SUCCESS("All stations have coordinates; nothing to do."))
            return

        matched, city_fallback, upgraded, no_match = 0, 0, 0, 0
        batch = int(opts["batch_size"])
        addr_hits = {}

        if not no_census:
            for i in range(0, len(pending), batch):
                chunk = pending[i:i + batch]
                rows = [(str(s.opis_id), s.address, s.city, s.state) for s in chunk]
                try:
                    hits = census_batch.geocode_batch(rows)
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(
                        f"Census batch failed ({exc}); city centroids for this chunk."
                    ))
                    hits = {}
                addr_hits.update(hits)

        now = timezone.now()
        to_update = []
        for s in pending:
            was_city = (s.geo_source == "city_centroid")
            hit = addr_hits.get(str(s.opis_id))
            if hit:
                s.lat, s.lng = hit
                s.geo_source = "address"
                matched += 1
                if was_city:
                    upgraded += 1
            elif was_city:
                # Already had a city-centroid; keep it (nothing better available).
                continue
            else:
                city_hit = local_places.lookup_city_coords(s.city, s.state)
                if city_hit:
                    s.lat, s.lng = city_hit
                    s.geo_source = "city_centroid"
                    city_fallback += 1
                else:
                    no_match += 1
                    continue
            s.geocoded_at = now
            to_update.append(s)

        Station.objects.bulk_update(
            to_update, ["lat", "lng", "geo_source", "geocoded_at"], batch_size=500
        )
        reset_station_index()

        parts = [f"pending={len(pending)}", f"matched_by_address={matched}",
                 f"city_centroid_fallback={city_fallback}", f"no_match={no_match}"]
        if retry_fallback:
            parts.append(f"upgraded_from_city={upgraded}")
        self.stdout.write(self.style.SUCCESS(" ".join(parts)))
