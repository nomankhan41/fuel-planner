"""One-off: build data/us_cities.csv from GeoNames (cities500) + US ZIP-code centroids.

The generated CSV is committed, so you never need to run this to use the API.
To rebuild:  pip install geonamescache zipcodes
             python tools/build_us_cities.py data/us_cities.csv
Data: GeoNames (CC BY 4.0, geonames.org) via geonamescache; US ZIP data via `zipcodes`.
"""
import csv
import json
import os
import re
import sys
from collections import defaultdict
import geonamescache, zipcodes

PRE = {"st": "saint", "ste": "sainte", "ft": "fort", "mt": "mount"}
def key(s):
    w = re.sub(r"[^\w\s]", " ", s.lower()).split()
    if w and w[0] in PRE: w[0] = PRE[w[0]]
    return "".join(w)

out = {}
# 1) ZIP centroids averaged per (city, state) -- covers tiny places
acc = defaultdict(lambda: [0.0, 0.0, 0, ""])
for z in zipcodes.list_all():
    if not z["active"] or z["zip_code_type"] == "MILITARY" or not z["lat"]: continue
    for name in [z["city"]] + z.get("acceptable_cities", []):
        a = acc[(key(name), z["state"])]
        a[0] += float(z["lat"]); a[1] += float(z["long"]); a[2] += 1; a[3] = a[3] or name.title()
for (k, st), (la, lo, n, name) in acc.items():
    out[(k, st)] = (name, st, round(la / n, 5), round(lo / n, 5), 0)
# 2) GeoNames populated places override (true town centre + population)
p = os.path.dirname(geonamescache.__file__) + "/data/cities500.json"
best = {}
for c in json.load(open(p)).values():
    if c["countrycode"] != "US": continue
    k = (key(c["name"]), c["admin1code"])
    if k not in best or c["population"] > best[k][4]:
        best[k] = (c["name"], c["admin1code"], round(c["latitude"], 5), round(c["longitude"], 5), c["population"])
out.update(best)
with open(sys.argv[1], "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["city", "state", "lat", "lng", "population"])
    for v in sorted(out.values(), key=lambda r: (r[1], r[0])): w.writerow(v)
print(len(out), "places")
