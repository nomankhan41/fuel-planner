"""All stations with coordinates held in memory as numpy arrays, loaded once per process."""
import threading
from dataclasses import dataclass

import numpy as np

from .geo import to_xyz

_lock = threading.Lock()
_index = None


@dataclass
class StationIndex:
    ids: np.ndarray
    prices: np.ndarray
    lat: np.ndarray
    lng: np.ndarray
    xyz: np.ndarray
    rows: list


def get_station_index() -> StationIndex:
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                _index = _build()
    return _index


def reset_station_index():
    """Call after `load_stations` or `geocode_stations` changes the table."""
    global _index
    with _lock:
        _index = None


def _build() -> StationIndex:
    from stations.models import Station

    rows = list(
        Station.objects.filter(lat__isnull=False, lng__isnull=False)
        .values("id", "opis_id", "name", "address", "city", "state", "price", "lat", "lng", "geo_source")
    )
    lat = np.array([r["lat"] for r in rows], dtype=float)
    lng = np.array([r["lng"] for r in rows], dtype=float)
    return StationIndex(
        ids=np.array([r["id"] for r in rows], dtype=int),
        prices=np.array([r["price"] for r in rows], dtype=float),
        lat=lat,
        lng=lng,
        xyz=to_xyz(lat, lng) if rows else np.empty((0, 3)),
        rows=rows,
    )
