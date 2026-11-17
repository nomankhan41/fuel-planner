"""Optimizer tests: pure Python, no database or network."""
import itertools
import random
from dataclasses import dataclass

from django.test import SimpleTestCase

from services.optimizer import NoStationInRange, plan_fuel_stops

R, MPG = 500.0, 10.0


@dataclass
class S:
    mile: float
    price: float


def simulate(plan, stations, total, start_fuel):
    """Drive the plan and check the tank never runs dry or overflows. Returns final fuel (miles)."""
    buys = {id(s.payload): s.gallons * MPG for s in plan.stops}
    pos, fuel = 0.0, start_fuel
    for st in sorted(stations, key=lambda s: s.mile):
        fuel -= st.mile - pos
        assert fuel >= -1e-6, f"ran dry before mile {st.mile}"
        pos = st.mile
        fuel += buys.get(id(st), 0)
        assert fuel <= R + 1e-6, "tank overflow"
    fuel -= total - pos
    assert fuel >= -1e-6, "ran dry before destination"
    return fuel


def brute_force_cost(stations, total, start_fuel, step=10.0):
    """Exact DP over fuel levels in `step`-mile units (test oracle)."""
    pts = sorted(stations, key=lambda s: s.mile) + [S(total, 0.0)]
    levels = int(R / step)
    INF = float("inf")
    best = [INF] * (levels + 1)
    best[int(start_fuel / step)] = 0.0
    pos = 0.0
    for p in pts:
        d = int(round((p.mile - pos) / step))
        moved = [INF] * (levels + 1)
        for f in range(levels + 1):
            if best[f] < INF and f - d >= 0:
                moved[f - d] = min(moved[f - d], best[f])
        if p.price == 0.0 and p.mile == total:
            return min(moved)
        # buy any amount here
        for f in range(levels + 1):
            for g in range(f + 1, levels + 1):
                moved[g] = min(moved[g], moved[f] + (g - f) * step / MPG * p.price)
        best, pos = moved, p.mile
    return INF


class OptimizerTests(SimpleTestCase):
    def test_short_trip_with_full_tank_needs_no_stop(self):
        plan = plan_fuel_stops([S(100, 3.0)], 300, R, MPG, start_fuel_miles=R)
        self.assertEqual(plan.stops, [])
        self.assertEqual(plan.total_cost, 0)

    def test_empty_tank_short_trip_buys_exactly_trip_fuel(self):
        stations = [S(0, 3.0), S(100, 2.0)]
        plan = plan_fuel_stops(stations, 300, R, MPG)
        # buy 100 miles at 3.00, then 200 miles at the cheaper 2.00
        self.assertEqual([(s.mile, round(s.gallons, 2)) for s in plan.stops], [(0, 10.0), (100, 20.0)])
        self.assertAlmostEqual(plan.total_cost, 10 * 3.0 + 20 * 2.0)

    def test_fills_up_when_current_station_is_cheapest_in_range(self):
        stations = [S(0, 2.0), S(400, 4.0), S(700, 3.0)]
        plan = plan_fuel_stops(stations, 900, R, MPG)
        self.assertAlmostEqual(plan.stops[0].gallons, 50.0)  # full tank at the cheap station
        self.assertAlmostEqual(plan.total_gallons, 90.0)
        simulate(plan, stations, 900, 0)

    def test_cheaper_station_just_out_of_range_is_not_used_directly(self):
        stations = [S(0, 3.0), S(450, 3.5), S(510, 1.0)]
        plan = plan_fuel_stops(stations, 800, R, MPG)
        miles = [s.mile for s in plan.stops]
        self.assertIn(450, miles)  # must stop at 450 to get to the cheap one at 510
        self.assertIn(510, miles)
        simulate(plan, stations, 800, 0)

    def test_unreachable_gap_raises(self):
        with self.assertRaises(NoStationInRange) as ctx:
            plan_fuel_stops([S(0, 3.0), S(100, 3.0), S(700, 3.0)], 900, R, MPG)
        self.assertEqual(ctx.exception.mile, 100)

    def test_empty_tank_without_station_at_start_raises(self):
        with self.assertRaises(NoStationInRange):
            plan_fuel_stops([S(5, 3.0)], 100, R, MPG)

    def test_total_gallons_equal_distance_over_mpg_when_starting_empty(self):
        stations = [S(0, 3.2)] + [S(m, p) for m, p in zip(range(150, 2800, 150), itertools.cycle([3.1, 3.6, 2.9, 3.4]))]
        plan = plan_fuel_stops(stations, 2800, R, MPG)
        self.assertAlmostEqual(plan.total_gallons, 280.0)
        self.assertAlmostEqual(simulate(plan, stations, 2800, 0), 0.0)

    def test_stop_penalty_skips_stops_that_save_pennies(self):
        stations = [S(0, 3.00), S(20, 2.99), S(300, 3.50), S(450, 3.10)]
        cheapest = plan_fuel_stops(stations, 600, R, MPG)
        practical = plan_fuel_stops(stations, 600, R, MPG, stop_penalty=5)
        self.assertGreater(len(cheapest.stops), len(practical.stops))
        self.assertLess(practical.total_cost - cheapest.total_cost, 5)  # gave up < $5 per skipped stop
        simulate(practical, stations, 600, 0)

    def test_matches_exact_dp_on_random_routes(self):
        rng = random.Random(7)
        for _ in range(40):
            total = rng.randrange(300, 1600, 10)
            stations = [S(0, round(rng.uniform(2.7, 4.5), 2))]
            stations += [S(m, round(rng.uniform(2.7, 4.5), 2))
                         for m in sorted(rng.sample(range(10, total, 10), k=min(12, total // 10 - 1)))]
            try:
                plan = plan_fuel_stops(stations, total, R, MPG)
            except NoStationInRange:
                continue
            simulate(plan, stations, total, 0)
            self.assertAlmostEqual(plan.total_cost, brute_force_cost(stations, total, 0), places=6)
