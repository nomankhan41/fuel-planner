"""US Census batch geocoder response parser + command fallback behaviour."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from services.census_batch import parse_response
from stations.models import Station


SAMPLE_RESPONSE = (
    '1,"123 Main St, Dallas, TX",Match,Exact,"123 MAIN ST, DALLAS, TX, 75201","-96.8089,32.7886",48001,L\n'
    '2,"I-44 EXIT 283, Big Cabin, OK",No_Match\n'
    '3,"500 Elm St, Austin, TX",Match,Non_Exact,"500 ELM ST, AUSTIN, TX","-97.7430,30.2672",48453,R\n'
)


class CensusParserTests(TestCase):
    def test_parse_matches_and_skips_no_match(self):
        out = parse_response(SAMPLE_RESPONSE)
        self.assertEqual(set(out.keys()), {"1", "3"})
        self.assertAlmostEqual(out["1"][0], 32.7886)
        self.assertAlmostEqual(out["1"][1], -96.8089)
        self.assertNotIn("2", out)


class GeocodeCommandTests(TestCase):
    def _make(self, **kw):
        base = dict(address="I-40", city="Albuquerque", state="NM", price=3.0,
                    address_hash="h", lat=None, lng=None, geo_source="")
        base.update(kw)
        return Station.objects.create(**base)

    def test_matched_rows_get_address_coords_unmatched_get_city_centroid(self):
        a = self._make(opis_id=101, name="A")
        b = self._make(opis_id=102, name="B")
        with mock.patch("services.census_batch.geocode_batch",
                        return_value={"101": (35.084, -106.650)}):
            call_command("geocode_stations", stdout=StringIO())
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(a.geo_source, "address")
        self.assertAlmostEqual(a.lat, 35.084)
        self.assertEqual(b.geo_source, "city_centroid")
        self.assertIsNotNone(b.lat)
        self.assertIsNotNone(a.geocoded_at)

    def test_rerun_without_retry_is_noop_when_all_have_coords(self):
        self._make(opis_id=201, name="A", lat=1.0, lng=2.0, geo_source="address",
                   geocoded_at=timezone.now())
        with mock.patch("services.census_batch.geocode_batch") as m:
            call_command("geocode_stations", "--no-retry-fallback", stdout=StringIO())
        m.assert_not_called()

    def test_no_census_flag_skips_api_and_uses_city_centroids(self):
        self._make(opis_id=301, name="A")
        with mock.patch("services.census_batch.geocode_batch") as m:
            call_command("geocode_stations", "--no-census", stdout=StringIO())
        m.assert_not_called()
        s = Station.objects.get(opis_id=301)
        self.assertEqual(s.geo_source, "city_centroid")

    def test_retry_fallback_upgrades_city_centroid_to_address_when_census_matches(self):
        """Default behaviour: previously-city_centroid stations get re-sent to Census.

        A match replaces the centroid with real address coordinates; a non-match
        leaves the centroid in place.
        """
        s = self._make(opis_id=401, name="A", lat=35.084, lng=-106.650,
                       geo_source="city_centroid", geocoded_at=timezone.now())
        t = self._make(opis_id=402, name="B", lat=35.084, lng=-106.650,
                       geo_source="city_centroid", geocoded_at=timezone.now())
        out = StringIO()
        with mock.patch("services.census_batch.geocode_batch",
                        return_value={"401": (35.123, -106.700)}):
            call_command("geocode_stations", stdout=out)
        s.refresh_from_db(); t.refresh_from_db()
        # Matched -> upgraded to address.
        self.assertEqual(s.geo_source, "address")
        self.assertAlmostEqual(s.lat, 35.123)
        # Not matched -> kept the existing centroid; not reset to NULL.
        self.assertEqual(t.geo_source, "city_centroid")
        self.assertAlmostEqual(t.lat, 35.084)
        self.assertIn("upgraded_from_city=1", out.getvalue())

    def test_retry_fallback_off_leaves_city_centroids_alone(self):
        self._make(opis_id=501, name="A", lat=1.0, lng=2.0,
                   geo_source="city_centroid", geocoded_at=timezone.now())
        with mock.patch("services.census_batch.geocode_batch") as m:
            call_command("geocode_stations", "--no-retry-fallback", stdout=StringIO())
        m.assert_not_called()
