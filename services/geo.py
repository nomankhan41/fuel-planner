"""Small, vectorised geometry helpers (miles)."""
import numpy as np

EARTH_RADIUS_MILES = 3958.8
METERS_PER_MILE = 1609.344


def to_xyz(lat, lng) -> np.ndarray:
    """Lat/lng (degrees) -> 3-D points on a sphere of Earth's radius.

    Straight-line distance between two such points is ~= the surface distance
    for the short distances we care about (< 20 miles), so a KD-tree works.
    """
    lat, lng = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lng, float))
    return EARTH_RADIUS_MILES * np.column_stack(
        (np.cos(lat) * np.cos(lng), np.cos(lat) * np.sin(lng), np.sin(lat))
    )


def haversine_miles(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def densify(coords: np.ndarray, max_step_miles: float = 1.0) -> np.ndarray:
    """Insert points so no segment of the (lat, lng) polyline is longer than max_step_miles.

    Long straight highway segments can have vertices many miles apart; without this
    a station next to the middle of such a segment would look far from the route.
    """
    seg = haversine_miles(coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1])
    parts = [coords[:1]]
    for i, length in enumerate(seg):
        n = int(np.ceil(length / max_step_miles))
        if n > 1:
            t = np.linspace(0, 1, n + 1)[1:, None]
            parts.append(coords[i] + t * (coords[i + 1] - coords[i]))
        else:
            parts.append(coords[i + 1:i + 2])
    return np.vstack(parts)


def cumulative_miles(coords: np.ndarray) -> np.ndarray:
    seg = haversine_miles(coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1])
    return np.concatenate(([0.0], np.cumsum(seg)))


def simplify_for_output(coords: np.ndarray, min_gap_miles: float = 0.5) -> list:
    """Thin the polyline for the JSON response / map (keeps first and last point)."""
    kept, last = [coords[0]], coords[0]
    for p in coords[1:-1]:
        if haversine_miles(last[0], last[1], p[0], p[1]) >= min_gap_miles:
            kept.append(p)
            last = p
    kept.append(coords[-1])
    return [[round(float(lng), 5), round(float(lat), 5)] for lat, lng in kept]  # GeoJSON order
