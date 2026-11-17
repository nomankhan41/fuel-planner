"""Import/refresh stations from the CSV (upsert, not drop-and-reload).

Only adds/updates/removes rows; does NOT geocode. Run `geocode_stations` next
(or chain the two in Docker / CI).

    python manage.py load_stations
    python manage.py load_stations --fuel path/to/new-prices.csv
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from services.station_importer import import_fuel_csv
from services.station_index import reset_station_index


class Command(BaseCommand):
    help = "Upsert fuel stations from the CSV (adds, updates, removes)."

    def add_arguments(self, parser):
        parser.add_argument("--fuel", default=Path(settings.BASE_DIR) / "data" / "fuel-prices.csv")

    def handle(self, *args, **opts):
        path = Path(opts["fuel"])
        if not path.exists():
            raise CommandError(f"Fuel CSV not found: {path}")

        result = import_fuel_csv(path)
        reset_station_index()

        self.stdout.write(self.style.SUCCESS(str(result)))
        self.stdout.write("Next: python manage.py geocode_stations")
