"""Station upsert importer tests."""
import tempfile
from pathlib import Path

from django.test import TestCase
from django.utils import timezone

from services.station_importer import import_fuel_csv
from stations.models import Station

HEADER = "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"


def write_csv(rows):
    d = tempfile.mkdtemp()
    p = Path(d) / "fuel.csv"
    p.write_text(HEADER + "".join(rows))
    return p


class ImporterTests(TestCase):
    def test_initial_import(self):
        csv = write_csv([
            "1,A STOP,I-40 EX 1,Amarillo,TX,1,3.20\n",
            "1,A DUP,I-40 EX 1,Amarillo,TX,1,3.50\n",       # same id, costlier - dropped
            "2,CANADA,HWY 1,Toronto,ON,1,2.00\n",            # non-US - dropped
            "3,B STOP,I-44,St. Louis,MO,1,3.00\n",
        ])
        r = import_fuel_csv(csv)
        self.assertEqual(r.rows_in_csv, 4)
        self.assertEqual(r.non_us_dropped, 1)
        self.assertEqual(r.duplicates_collapsed, 1)
        self.assertEqual(r.added, 2)
        self.assertEqual(Station.objects.count(), 2)
        self.assertAlmostEqual(Station.objects.get(opis_id=1).price, 3.20)

    def test_rerun_detects_updates_and_unchanged(self):
        csv1 = write_csv(["1,A,I-40 EX 1,Amarillo,TX,1,3.20\n",
                          "3,B,I-44,St. Louis,MO,1,3.00\n"])
        import_fuel_csv(csv1)
        # mark one station as geocoded so we can check it isn't disturbed
        s1 = Station.objects.get(opis_id=1)
        s1.lat, s1.lng, s1.geo_source, s1.geocoded_at = 35.2, -101.8, "address", timezone.now()
        s1.save()
        old_h = s1.address_hash

        csv2 = write_csv(["1,A,I-40 EX 1,Amarillo,TX,1,3.10\n",   # price changed only
                          "3,B,I-44,St. Louis,MO,1,3.00\n"])      # unchanged
        r = import_fuel_csv(csv2)
        self.assertEqual(r.added, 0)
        self.assertEqual(r.updated, 1)
        self.assertEqual(r.unchanged, 1)

        s1 = Station.objects.get(opis_id=1)
        self.assertAlmostEqual(s1.price, 3.10)
        self.assertEqual(s1.address_hash, old_h)
        # Address unchanged -> coords preserved (no re-geocode needed).
        self.assertEqual(s1.lat, 35.2)
        self.assertEqual(s1.geo_source, "address")

    def test_address_change_clears_coords_for_regeocode(self):
        csv1 = write_csv(["1,A,OLD ADDRESS,Amarillo,TX,1,3.20\n"])
        import_fuel_csv(csv1)
        s = Station.objects.get(opis_id=1)
        s.lat, s.lng, s.geo_source = 1.0, 2.0, "address"
        s.save()

        csv2 = write_csv(["1,A,NEW ADDRESS,Amarillo,TX,1,3.20\n"])
        r = import_fuel_csv(csv2)
        self.assertEqual(r.updated, 1)

        s = Station.objects.get(opis_id=1)
        self.assertIsNone(s.lat)
        self.assertEqual(s.geo_source, "")

    def test_removed_stations_are_deleted(self):
        csv1 = write_csv(["1,A,I-40,Amarillo,TX,1,3.00\n",
                          "2,B,I-44,St. Louis,MO,1,3.00\n"])
        import_fuel_csv(csv1)
        csv2 = write_csv(["1,A,I-40,Amarillo,TX,1,3.00\n"])
        r = import_fuel_csv(csv2)
        self.assertEqual(r.removed, 1)
        self.assertFalse(Station.objects.filter(opis_id=2).exists())
