"""Find stations along a route and give each one a mile marker."""
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from .geo import cumulative_miles, densify, to_xyz
from .station_index import StationIndex


@dataclass
class Candidate:
    mile: float          # distance from the start, along the route
    price: float
    off_route_miles: float
    row: dict            # station display fields


def stations_along_route(route_coords: np.ndarray, route_miles: float, index: StationIndex,
                         corridor_miles: float) -> list[Candidate]:
    """Stations whose coordinates lie within corridor_miles of the route, sorted by mile marker.

    1. Densify the route to ~1-mile spacing and compute cumulative miles.
    2. Pre-filter stations to the route's bounding box (cheap numpy mask).
    3. One KD-tree query: nearest route point for every remaining station.
    """
    if len(index.rows) == 0:
        return []
    pts = densify(route_coords, 1.0)
    miles = cumulative_miles(pts)
    # Scale our haversine distance to the provider's road distance so markers match the total.
    if miles[-1] > 0 and route_miles > 0:
        miles *= route_miles / miles[-1]

    pad = corridor_miles / 69.0 + 0.05  # degrees; 1 degree latitude ~ 69 miles
    lng_pad = pad / max(np.cos(np.radians(np.abs(pts[:, 0]).max())), 0.2)
    mask = ((index.lat >= pts[:, 0].min() - pad) & (index.lat <= pts[:, 0].max() + pad)
            & (index.lng >= pts[:, 1].min() - lng_pad) & (index.lng <= pts[:, 1].max() + lng_pad))
    cand_idx = np.nonzero(mask)[0]
    if cand_idx.size == 0:
        return []

    tree = cKDTree(to_xyz(pts[:, 0], pts[:, 1]))
    dist, nearest = tree.query(index.xyz[cand_idx], k=1, distance_upper_bound=corridor_miles)
    found = np.isfinite(dist)

    out = [
        Candidate(mile=float(miles[n]), price=float(index.prices[i]), off_route_miles=float(d), row=index.rows[i])
        for i, n, d in zip(cand_idx[found], nearest[found], dist[found])
    ]
    out.sort(key=lambda c: (c.mile, c.price))
    return out
