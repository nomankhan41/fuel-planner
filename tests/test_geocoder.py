"""Geocoder tests - all mocked, no network."""
from unittest import mock

from django.test import TestCase, override_settings

from services.geocoder import Resolver
from stations.models import GeocodeCache


def _feature(label, lng, lat, layer="locality", region_a=None):
    props = {"label": label, "layer": layer}
    if region_a:
        props["region_a"] = region_a
    return {"geometry": {"coordinates": [lng, lat]}, "properties": props}


def ors_reply(*features):
    def _fake_get(url, params=None, **kw):
        m = mock.Mock(status_code=200)
        m.json.return_value = {"features": list(features)}
        return m
    return _fake_get


@override_settings(ORS_API_KEY="test-key")
class GeocoderCacheTests(TestCase):
    def test_first_call_hits_api_second_call_hits_cache(self):
        fake = ors_reply(_feature("Dallas, Texas, USA", -96.80667, 32.78306,
                                  layer="locality", region_a="TX"))
        with mock.patch("services.geocoder.requests.get", side_effect=fake) as m:
            r1 = Resolver()
            p1 = r1.resolve("Dallas, TX")
            self.assertEqual(p1.source, "ors")
            self.assertEqual(r1.api_calls, 1)
            self.assertEqual(m.call_count, 1)

            r2 = Resolver()
            p2 = r2.resolve("Dallas, TX")
            self.assertEqual(p2.source, "cache")
            self.assertEqual(r2.api_calls, 0)
            self.assertEqual(m.call_count, 1)

        self.assertEqual(GeocodeCache.objects.filter(source="ors").count(), 1)

    def test_query_variants_collapse_to_one_cache_row(self):
        fake = ors_reply(_feature("Dallas, Texas, USA", -96.80667, 32.78306,
                                  layer="locality", region_a="TX"))
        with mock.patch("services.geocoder.requests.get", side_effect=fake):
            Resolver().resolve("Dallas, TX")
            Resolver().resolve(" dallas , tx ")
            Resolver().resolve("Dallas, Texas")
        self.assertEqual(GeocodeCache.objects.count(), 1)

    def test_falls_back_to_local_when_api_fails(self):
        import requests as req
        with mock.patch("services.geocoder.requests.get",
                        side_effect=req.ConnectionError("boom")):
            r = Resolver()
            p = r.resolve("Albuquerque, NM")
        self.assertEqual(p.source, "local")
        self.assertEqual(r.api_calls, 1)
        self.assertEqual(GeocodeCache.objects.filter(query_key="albuquerque, nm",
                                                     source="local").count(), 1)

    def test_coords_input_makes_zero_api_calls(self):
        r = Resolver()
        p = r.resolve("32.78,-96.80")
        self.assertEqual(p.source, "coords")
        self.assertEqual(r.api_calls, 0)
        self.assertEqual(GeocodeCache.objects.count(), 0)

    def test_region_level_reply_is_rejected_and_404s(self):
        """ORS returning 'Texas, USA' (layer=region) for 'Nowhereville, TX' must NOT be
        accepted or cached; the resolver falls back to the local table, finds nothing, 404s.
        """
        from services.exceptions import PlaceNotFound
        fake = ors_reply(_feature("Texas, USA", -99.0, 31.5, layer="region", region_a="TX"))
        with mock.patch("services.geocoder.requests.get", side_effect=fake) as m:
            with self.assertRaises(PlaceNotFound):
                Resolver().resolve("Nowhereville, TX")
            self.assertEqual(m.call_count, 1)
        # Never cached a rejected result.
        self.assertEqual(GeocodeCache.objects.count(), 0)

    def test_wrong_state_match_is_rejected(self):
        """Asked 'Springfield, IL' but the API returned a Springfield in MA: reject."""
        from services.exceptions import PlaceNotFound
        fake = ors_reply(_feature("Springfield, Massachusetts, USA", -72.6, 42.1,
                                  layer="locality", region_a="MA"))
        with mock.patch("services.geocoder.requests.get", side_effect=fake):
            with self.assertRaises(PlaceNotFound):
                Resolver().resolve("Springfieldxyz, IL")
        self.assertEqual(GeocodeCache.objects.count(), 0)

    def test_precise_result_after_coarse_one_in_same_reply_is_used(self):
        """First feature is region-level, second is precise: pick the precise one."""
        fake = ors_reply(
            _feature("Texas, USA", -99.0, 31.5, layer="region", region_a="TX"),
            _feature("Austin, Texas, USA", -97.7431, 30.2672,
                     layer="locality", region_a="TX"),
        )
        with mock.patch("services.geocoder.requests.get", side_effect=fake):
            p = Resolver().resolve("Austin, TX")
        self.assertEqual(p.source, "ors")
        self.assertAlmostEqual(p.lat, 30.2672)


class LocalOnlyGeocoderTests(TestCase):
    def test_no_api_key_uses_local_only(self):
        p = Resolver().resolve("Dallas, TX")
        self.assertEqual(p.source, "local")
