"""The only place that talks to the external routing API: 1 HTTP call per route."""
import logging
from dataclasses import dataclass

import numpy as np
import requests
from django.conf import settings

from .exceptions import RouteNotFound, RoutingServiceError
from .geo import METERS_PER_MILE

log = logging.getLogger("fuel_planner")


@dataclass
class Route:
    coords: np.ndarray       # (n, 2) as (lat, lng)
    distance_miles: float
    duration_hours: float
    provider: str


def fetch_route(start_lat, start_lng, end_lat, end_lng) -> Route:
    provider = settings.ROUTING_PROVIDER
    log.info("routing api call provider=%s", provider)
    if provider == "ors":
        return _ors(start_lat, start_lng, end_lat, end_lng)
    if provider == "osrm":
        return _osrm(start_lat, start_lng, end_lat, end_lng)
    raise RoutingServiceError(f"Unknown ROUTING_PROVIDER {provider!r}")


def _ors(slat, slng, elat, elng) -> Route:
    if not settings.ORS_API_KEY:
        raise RoutingServiceError("ORS_API_KEY is not set.")
    body = {"coordinates": [[slng, slat], [elng, elat]], "instructions": False}
    headers = {"Authorization": settings.ORS_API_KEY, "Content-Type": "application/json"}
    data = _request("post", settings.ORS_URL, json=body, headers=headers)
    features = data.get("features") or []
    if not features:
        raise RouteNotFound("No drivable route found between these locations.")
    feat = features[0]
    summary = feat.get("properties", {}).get("summary", {})
    lnglat = np.asarray(feat["geometry"]["coordinates"], dtype=float)
    return Route(lnglat[:, ::-1], summary.get("distance", 0) / METERS_PER_MILE,
                 summary.get("duration", 0) / 3600, "openrouteservice")


def _osrm(slat, slng, elat, elng) -> Route:
    url = f"{settings.OSRM_URL}/{slng},{slat};{elng},{elat}"
    data = _request("get", url, params={"overview": "full", "geometries": "geojson", "steps": "false"})
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RouteNotFound("No drivable route found between these locations.")
    r = data["routes"][0]
    lnglat = np.asarray(r["geometry"]["coordinates"], dtype=float)
    return Route(lnglat[:, ::-1], r["distance"] / METERS_PER_MILE, r["duration"] / 3600, "osrm")


def _request(method, url, **kwargs) -> dict:
    try:
        resp = requests.request(method, url, timeout=settings.ROUTING_TIMEOUT_SECONDS, **kwargs)
    except requests.RequestException as exc:
        raise RoutingServiceError(f"Routing service unreachable: {exc}") from exc
    if resp.status_code == 404:
        raise RouteNotFound("No drivable route found between these locations.")
    if resp.status_code >= 400:
        raise RoutingServiceError(f"Routing service error {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise RoutingServiceError(f"Routing service returned invalid JSON: {exc}") from exc
