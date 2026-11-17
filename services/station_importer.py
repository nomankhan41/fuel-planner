"""Incremental station importer.

Reads the fuel-prices CSV and upserts into the Station table:
  - add new stations
  - update changed prices / addresses
  - delete stations no longer in the CSV
  - do NOT touch lat/lng, geo_source or geocoded_at for unchanged addresses

A follow-up `geocode_stations` command fills in coordinates for new /
address-changed stations.
"""
import csv
from dataclasses import dataclass
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from .text import US_STATES, address_hash
from stations.models import Station


@dataclass
class ImportResult:
    rows_in_csv: int = 0
    non_us_dropped: int = 0
    duplicates_collapsed: int = 0
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0

    def __str__(self):
        return (f"rows={self.rows_in_csv} non_us_dropped={self.non_us_dropped} "
                f"duplicates_collapsed={self.duplicates_collapsed} added={self.added} "
                f"updated={self.updated} removed={self.removed} unchanged={self.unchanged}")


def import_fuel_csv(path: Path) -> ImportResult:
    """Upsert stations from the CSV. Idempotent: safe to run on every refresh."""
    result = ImportResult()
    cheapest = {}  # opis_id -> cleaned row with the lowest price
    with open(path, newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            result.rows_in_csv += 1
            row = {k.strip(): (v or "").strip() for k, v in raw.items()}
            if row["State"] not in US_STATES:
                result.non_us_dropped += 1
                continue
            sid = int(row["OPIS Truckstop ID"])
            price = float(row["Retail Price"])
            if sid not in cheapest or price < cheapest[sid]["price"]:
                row["price"] = price
                cheapest[sid] = row
    result.duplicates_collapsed = result.rows_in_csv - result.non_us_dropped - len(cheapest)

    existing = {s.opis_id: s for s in Station.objects.all()}
    seen_ids = set()

    with transaction.atomic():
        for sid, r in cheapest.items():
            seen_ids.add(sid)
            new_hash = address_hash(r["Address"], r["City"], r["State"])
            if sid in existing:
                s = existing[sid]
                changed = False
                for field, value in (("name", r["Truckstop Name"]), ("address", r["Address"]),
                                     ("city", r["City"]), ("state", r["State"]), ("price", r["price"])):
                    if getattr(s, field) != value:
                        setattr(s, field, value)
                        changed = True
                if s.address_hash != new_hash:
                    # Address moved -> coordinates are stale, clear them so the next
                    # geocode run picks this station up again.
                    s.address_hash = new_hash
                    s.lat = s.lng = None
                    s.geo_source = ""
                    s.geocoded_at = None
                    changed = True
                if changed:
                    s.save()
                    result.updated += 1
                else:
                    result.unchanged += 1
            else:
                Station.objects.create(
                    opis_id=sid, name=r["Truckstop Name"], address=r["Address"],
                    city=r["City"], state=r["State"], price=r["price"],
                    address_hash=new_hash,
                )
                result.added += 1

        stale_ids = set(existing) - seen_ids
        if stale_ids:
            Station.objects.filter(opis_id__in=stale_ids).delete()
            result.removed = len(stale_ids)

    return result
