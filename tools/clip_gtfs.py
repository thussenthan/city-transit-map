"""Clip a huge GTFS zip to one city's extent (and optionally to rail/metro/tram routes) without extracting it.

    python3 tools/clip_gtfs.py BIG.zip CITY --config tools/cities.json --out OUT_DIR [--rail-only]

Streams stop_times.txt out of the zip, keeps only rows whose stop is inside the city's extent, then keeps the
trips/routes/calendars/shapes those rows need.  OUT_DIR is a normal unzipped GTFS folder usable as a feed path.
"""
import argparse, json, os, zipfile
import numpy as np, pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("zip"); ap.add_argument("city"); ap.add_argument("--config", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--rail-only", action="store_true", help="keep only route_type 0,1,2 (+ extended rail/metro/tram codes)")
ap.add_argument("--types", help="comma-separated raw route_type values to keep (overrides --rail-only)")
a = ap.parse_args()
cfg = json.load(open(a.config))[a.city]
os.makedirs(a.out, exist_ok=True)

R, MPP = 6378137.0, 20.0
clon, clat = cfg["center"]; exk, eyk = cfg["ext_km"]
K = np.cos(np.radians(clat)); mxc, myc = R * np.radians(clon), R * np.log(np.tan(np.pi / 4 + np.radians(clat) / 2))
def to_ll(x, y):
    W, H = 2 * exk * 1000 / MPP, 2 * eyk * 1000 / MPP
    mx, my = mxc + (x - W / 2) * MPP / K, myc - (y - H / 2) * MPP / K
    return float(np.degrees(mx / R)), float(np.degrees(2 * np.arctan(np.exp(my / R)) - np.pi / 2))
W0, N0 = to_ll(0, 0); E0, S0 = to_ll(2 * exk * 1000 / MPP, 2 * eyk * 1000 / MPP)
pad = 0.03
print("bbox", S0, W0, N0, E0)

def rail_type(t):
    try: t = int(t)
    except ValueError: return False
    return t in (0, 1, 2, 5, 7, 12) or 100 <= t < 200 or 400 <= t < 500 or 900 <= t < 1000 or t == 1400

z = zipfile.ZipFile(a.zip)
names = {os.path.basename(n): n for n in z.namelist() if n.endswith(".txt")}
def rd(name, **kw): return pd.read_csv(z.open(names[name]), dtype=str, keep_default_na=False, **kw)
def chunks(name, n=1_000_000, **kw): return pd.read_csv(z.open(names[name]), dtype=str, keep_default_na=False, chunksize=n, **kw)

routes = rd("routes.txt")
if a.types: routes = routes[routes.route_type.isin(a.types.split(","))]
elif a.rail_only: routes = routes[routes.route_type.map(rail_type)]
print("routes kept", len(routes), routes.route_type.value_counts().to_dict())
stops = rd("stops.txt")
lon, lat = pd.to_numeric(stops.stop_lon, errors="coerce"), pd.to_numeric(stops.stop_lat, errors="coerce")
sin = stops[(lon > W0 - pad) & (lon < E0 + pad) & (lat > S0 - pad) & (lat < N0 + pad)]
stop_ok = set(sin.stop_id)
print("stops in bbox", len(stop_ok))

trip_parts, trip_ids = [], set()
for ch in chunks("trips.txt"):
    ch = ch[ch.route_id.isin(set(routes.route_id))]
    if len(ch): trip_parts.append(ch)
trips = pd.concat(trip_parts); want = set(trips.trip_id)
print("candidate trips", len(want))

out_st = os.path.join(a.out, "stop_times.txt"); first = True; rows = 0; used_trips = set()
for ch in chunks("stop_times.txt", 2_000_000):
    ch = ch[ch.trip_id.isin(want) & ch.stop_id.isin(stop_ok)]
    if not len(ch): continue
    used_trips |= set(ch.trip_id); rows += len(ch)
    ch.to_csv(out_st, mode="w" if first else "a", header=first, index=False); first = False
print("stop_time rows kept", rows, "trips", len(used_trips))

trips = trips[trips.trip_id.isin(used_trips)]
routes = routes[routes.route_id.isin(set(trips.route_id))]
stops = stops[stops.stop_id.isin(set(pd.read_csv(out_st, dtype=str, usecols=["stop_id"]).stop_id))]
trips.to_csv(os.path.join(a.out, "trips.txt"), index=False); routes.to_csv(os.path.join(a.out, "routes.txt"), index=False)
stops.to_csv(os.path.join(a.out, "stops.txt"), index=False)
svc = set(trips.service_id)
for nm in ("calendar.txt", "calendar_dates.txt"):
    if nm in names:
        df = rd(nm); df[df.service_id.isin(svc)].to_csv(os.path.join(a.out, nm), index=False)
if "agency.txt" in names: rd("agency.txt").to_csv(os.path.join(a.out, "agency.txt"), index=False)
if "frequencies.txt" in names:
    df = rd("frequencies.txt"); df[df.trip_id.isin(used_trips)].to_csv(os.path.join(a.out, "frequencies.txt"), index=False)
if "shapes.txt" in names and trips.get("shape_id") is not None:
    sh = set(trips.shape_id[trips.shape_id != ""]); parts = []
    for ch in chunks("shapes.txt", 2_000_000):
        ch = ch[ch.shape_id.isin(sh)]
        if len(ch): parts.append(ch)
    if parts: pd.concat(parts).to_csv(os.path.join(a.out, "shapes.txt"), index=False); print("shapes kept", len(sh))
print("DONE clip", a.out)
