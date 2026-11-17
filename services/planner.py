"""Orchestrates one trip request: places -> route (1 API call, cached) -> stations -> optimizer."""
import hashlib
import logging
import time
from dataclasses import replace

from django.conf import settings
from django.core.cache import cache

from . import routing_client
from .corridor import stations_along_route
from .exceptions import UnreachableRoute
from .geo import simplify_for_output
from .geocoder import Resolver
from .optimizer import NoStationInRange, plan_fuel_stops
from .station_index import get_station_index

log = logging.getLogger("fuel_planner")


def trip_id(start, finish, start_tank_full: bool) -> str:
    raw = f"{start.lat:.5f},{start.lng:.5f}|{finish.lat:.5f},{finish.lng:.5f}|{int(start_tank_full)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def plan_trip(start: str, finish: str, start_tank_full: bool = False) -> dict:
    """Plan a trip end-to-end. Returns a dict ready to serialise to JSON."""
    t0 = time.perf_counter()
    cfg = settings.FUEL_PLANNER

    # Step 1: resolve places (0-2 geocoding API calls, cache-aware).
    resolver = Resolver()
    start_p = resolver.resolve(start)
    finish_p = resolver.resolve(finish)

    # Step 2: trip cache - full response served without touching routing or optimizer.
    tid = trip_id(start_p, finish_p, start_tank_full)
    cached = cache.get(f"trip:{tid}")
    if cached:
        result = dict(cached)
        result["meta"] = {**cached["meta"], "cached": True,
                          "geocoding_calls": resolver.api_calls, "routing_calls": 0,
                          "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
        return result

    # Step 3: the ONE external routing API call.
    route = routing_client.fetch_route(start_p.lat, start_p.lng, finish_p.lat, finish_p.lng)

    # Step 4-5: find stations along the route, run the optimizer.
    candidates = stations_along_route(route.coords, route.distance_miles,
                                      get_station_index(), cfg["CORRIDOR_MILES"])
    if start_tank_full:
        usable, start_fuel = candidates, cfg["MAX_RANGE_MILES"]
    else:
        usable, start_fuel = _start_at_cheapest_nearby(candidates, cfg["CORRIDOR_MILES"]), 0.0

    try:
        plan = plan_fuel_stops(usable, route.distance_miles, cfg["MAX_RANGE_MILES"],
                               cfg["MPG"], start_fuel, cfg["STOP_PENALTY_USD"])
    except NoStationInRange as exc:
        if exc.mile == 0 and not start_tank_full:
            msg = "No fuel station near the start location; try start_tank_full=true."
        else:
            msg = (f"No fuel station within {cfg['MAX_RANGE_MILES']:.0f} miles after mile "
                   f"{exc.mile:.0f} of this route.")
        raise UnreachableRoute(msg) from exc

    result = _build_response(tid, start_p, finish_p, route, candidates, plan, start_tank_full, cfg)
    result["meta"]["geocoding_calls"] = resolver.api_calls
    result["meta"]["routing_calls"] = 1
    result["meta"]["cached"] = False
    result["meta"]["place_sources"] = resolver.sources
    result["meta"]["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    cache.set(f"trip:{tid}", result, cfg["CACHE_SECONDS"])
    log.info("trip %s -> %s miles=%.0f stops=%d routing_calls=1 geocoding_calls=%d %.0fms",
             start_p.label, finish_p.label, route.distance_miles, len(plan.stops),
             resolver.api_calls, result["meta"]["elapsed_ms"])
    return result


def get_cached_trip(tid: str):
    return cache.get(f"trip:{tid}")


def _start_at_cheapest_nearby(candidates, radius):
    near = [c for c in candidates if c.mile <= radius]
    if not near:
        return candidates
    first = min(near, key=lambda c: (c.price, c.mile))
    rest = [c for c in candidates if c is not first]
    return [replace(first, mile=0.0)] + rest


def _build_response(tid, start, finish, route, candidates, plan, start_tank_full, cfg):
    mpg = cfg["MPG"]
    stops = []
    for i, s in enumerate(plan.stops, 1):
        r = s.payload.row
        stops.append({
            "stop": i,
            "name": r["name"],
            "address": r["address"],
            "city": r["city"],
            "state": r["state"],
            "geo_source": r.get("geo_source", ""),
            "lat": r["lat"],
            "lng": r["lng"],
            "mile_marker": round(s.mile, 1),
            "price_per_gallon": round(s.price, 3),
            "gallons": round(s.gallons, 2),
            "cost": round(s.cost, 2),
        })

    avg_price = sum(c.price for c in candidates) / len(candidates) if candidates else None
    total_gallons = plan.total_gallons
    baseline = total_gallons * avg_price if avg_price else None
    return {
        "trip_id": tid,
        "start": {"query": start.label, "lat": start.lat, "lng": start.lng, "source": start.source},
        "finish": {"query": finish.label, "lat": finish.lat, "lng": finish.lng, "source": finish.source},
        "distance_miles": round(route.distance_miles, 1),
        "duration_hours": round(route.duration_hours, 1),
        "assumptions": {
            "max_range_miles": cfg["MAX_RANGE_MILES"],
            "mpg": mpg,
            "tank_gallons": cfg["MAX_RANGE_MILES"] / mpg,
            "start_tank_full": start_tank_full,
            "corridor_miles": cfg["CORRIDOR_MILES"],
            "stop_penalty_usd": cfg["STOP_PENALTY_USD"],
        },
        "total_gallons": round(total_gallons, 2),
        "total_fuel_cost": round(plan.total_cost, 2),
        "average_price_on_route": round(avg_price, 3) if avg_price else None,
        "savings_vs_average_price": round(baseline - plan.total_cost, 2) if baseline else None,
        "stations_considered": len(candidates),
        "fuel_stops": stops,
        "route": {"type": "LineString", "coordinates": simplify_for_output(route.coords)},
        "meta": {"routing_provider": route.provider},
    }
