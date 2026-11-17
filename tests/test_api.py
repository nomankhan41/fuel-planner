"""API + corridor tests with the routing API mocked (no network)."""
from unittest import mock

import numpy as np
from django.core.cache import cache
from django.test import TestCase, override_settings

from services.geo import haversine_miles
from services.routing_client import Route
from services.station_index import reset_station_index
from stations.models import Station

WAYPOINTS = np.array([[35.4676, -97.5164], [35.222, -101.8313], [35.0844, -106.6504]])


def fake_route(*_args, **_kwargs):
    seg = haversine_miles(WAYPOINTS[:-1, 0], WAYPOINTS[:-1, 1], WAYPOINTS[1:, 0], WAYPOINTS[1:, 1])
    return Route(WAYPOINTS.copy(), float(seg.sum()), 8.0, "mock")


def add_station(i, lat, lng, price, city="Town"):
    return Station.objects.create(
        opis_id=i, name=f"Stop {i}", address="I-40", city=city, state="TX",
        price=price, lat=lat, lng=lng, geo_source="address", address_hash=str(i),
    )


class TripApiTests(TestCase):
    def setUp(self):
        cache.clear()
        reset_station_index()
        add_station(1, 35.47, -97.52, 3.40, "Oklahoma City")
        add_station(2, 35.30, -99.60, 2.90)
        add_station(3, 35.22, -101.83, 3.10, "Amarillo")
        add_station(4, 35.10, -104.70, 3.60)
        add_station(5, 40.00, -100.00, 1.00)  # far off route

    def tearDown(self):
        reset_station_index()

    @mock.patch("services.routing_client.fetch_route", side_effect=fake_route)
    def test_cold_then_cached_counts_calls_separately(self, fetch):
        body = {"start": "Oklahoma City, OK", "finish": "Albuquerque, NM"}
        r1 = self.client.post("/api/v1/route/", body, content_type="application/json")
        self.assertEqual(r1.status_code, 200, r1.content)
        data = r1.json()
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(data["meta"]["routing_calls"], 1)
        self.assertFalse(data["meta"]["cached"])
        names = [s["name"] for s in data["fuel_stops"]]
        self.assertNotIn("Stop 5", names)
        self.assertIn("Stop 2", names)

        r2 = self.client.post("/api/v1/route/", body, content_type="application/json")
        self.assertEqual(fetch.call_count, 1)  # cache hit
        data2 = r2.json()
        self.assertTrue(data2["meta"]["cached"])
        self.assertEqual(data2["meta"]["routing_calls"], 0)
        # Place lookups also cache-hit second time -> 0 geocoding API calls too.
        self.assertEqual(data2["meta"]["geocoding_calls"], 0)

        page = self.client.get(f"/api/v1/route/{data['trip_id']}/map/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "leaflet")

    @mock.patch("services.routing_client.fetch_route", side_effect=fake_route)
    def test_get_with_query_params(self, _fetch):
        r = self.client.get("/api/v1/route/", {"start": "Oklahoma City, OK",
                                               "finish": "Albuquerque, NM", "start_tank_full": "true"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["assumptions"]["start_tank_full"])

    def test_missing_field_is_400(self):
        r = self.client.post("/api/v1/route/", {"start": "Dallas, TX"}, content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_unknown_city_is_404(self):
        r = self.client.post("/api/v1/route/", {"start": "Nowhereville, TX", "finish": "Dallas, TX"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 404)

    def test_coordinates_outside_usa_are_400(self):
        r = self.client.post("/api/v1/route/", {"start": "51.5,-0.12", "finish": "Dallas, TX"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_unknown_map_is_404(self):
        self.assertEqual(self.client.get("/api/v1/route/doesnotexist/map/").status_code, 404)


@override_settings(ROUTING_PROVIDER="osrm")
class RoutingClientErrorTests(TestCase):
    def test_invalid_json_from_provider_returns_502(self):
        import requests
        reset_station_index()
        bad = mock.Mock(status_code=200)
        bad.json.side_effect = ValueError("no json")
        with mock.patch("services.routing_client.requests.request", return_value=bad):
            r = self.client.post("/api/v1/route/",
                                 {"start": "Dallas, TX", "finish": "Houston, TX"},
                                 content_type="application/json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["error"], "routing_service_error")
