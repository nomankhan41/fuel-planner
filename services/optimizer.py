"""Cheapest fuel plan along a fixed route.

Pure function: no Django, no network, easy to unit-test.

Method: dynamic programming over (station, fuel in tank).
Fuel is tracked in whole miles of range (0..500). Driving the route in order, for every
station and every possible fuel level we keep the cheapest cost to be there. At each
station we may buy any amount (or nothing); between stations the tank drains by the
distance driven. Walking back from the destination gives the purchases.

`stop_penalty` is a small fixed "hassle" cost per stop. It is used only to choose stops,
so the planner won't stop to buy 1 gallon to save 2 cents, and it is never added to the
reported fuel cost. With stop_penalty=0 the result is the pure minimum fuel cost.

Cost: O(stations x 501) using numpy - a few milliseconds for a coast-to-coast route.
"""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Stop:
    mile: float
    price: float
    gallons: float
    payload: object = None

    @property
    def cost(self) -> float:
        return self.gallons * self.price


@dataclass
class FuelPlan:
    stops: list = field(default_factory=list)

    @property
    def total_gallons(self) -> float:
        return sum(s.gallons for s in self.stops)

    @property
    def total_cost(self) -> float:
        return sum(s.cost for s in self.stops)


class NoStationInRange(Exception):
    def __init__(self, mile: float):
        super().__init__(f"No fuel station reachable after mile {mile:.0f}.")
        self.mile = mile


def plan_fuel_stops(stations, total_miles: float, max_range: float, mpg: float,
                    start_fuel_miles: float = 0.0, stop_penalty: float = 0.0) -> FuelPlan:
    """Return the cheapest purchases to drive `total_miles`.

    stations: objects with `.mile` (distance from start along the route) and `.price` (USD/gal).
    start_fuel_miles: fuel in the tank at the start, in miles of range (0 = empty).
                      With an empty tank there must be a station at mile 0.
    stop_penalty: USD-equivalent cost of making a stop (affects choice only).
    """
    cap = int(round(max_range))
    total = int(round(total_miles))
    pts = sorted((s for s in stations if 0 <= round(s.mile) < total), key=lambda s: (round(s.mile), s.price))
    if not pts:
        if start_fuel_miles >= total:
            return FuelPlan()
        raise NoStationInRange(0.0)

    miles = np.array([int(round(s.mile)) for s in pts])
    levels = np.arange(cap + 1)
    INF = np.inf

    # cost to arrive at the first station with f miles of fuel
    cur = np.full(cap + 1, INF)
    arrive = int(round(min(start_fuel_miles, max_range))) - miles[0]
    if arrive < 0:
        raise NoStationInRange(0.0)
    cur[arrive] = 0.0

    bought_from = np.full((len(pts), cap + 1), -1, dtype=np.int32)  # -1 = no purchase at this level
    for i, s in enumerate(pts):
        p = s.price / mpg  # dollars per mile of range
        # buy: after[g] = min_{f<g} cur[f] + (g - f) * p + penalty
        vals = cur - levels * p
        run_min = np.minimum.accumulate(vals)
        run_arg = np.maximum.accumulate(np.where(vals == run_min, levels, 0))
        buy_cost = np.full(cap + 1, INF)
        buy_cost[1:] = run_min[:-1] + levels[1:] * p + stop_penalty
        buy = buy_cost < cur
        bought_from[i, 1:][buy[1:]] = run_arg[:-1][buy[1:]]
        after = np.where(buy, buy_cost, cur)

        # drive to the next station (or the destination)
        nxt_mile = miles[i + 1] if i + 1 < len(pts) else total
        d = nxt_mile - miles[i]
        cur = np.full(cap + 1, INF)
        if d <= cap:
            cur[: cap + 1 - d] = after[d:]
        if not np.isfinite(cur).any():
            raise NoStationInRange(float(miles[i]))

    # cheapest arrival at the destination, then walk back to recover purchases
    f = int(np.argmin(cur))
    stops = []
    for i in range(len(pts) - 1, -1, -1):
        nxt_mile = miles[i + 1] if i + 1 < len(pts) else total
        g = f + (nxt_mile - miles[i])            # fuel when leaving station i
        src = bought_from[i, g]
        if src >= 0:
            stops.append(Stop(pts[i].mile, pts[i].price, (g - src) / mpg, pts[i]))
            f = int(src)
        else:
            f = g
    stops.reverse()
    return FuelPlan(stops)
