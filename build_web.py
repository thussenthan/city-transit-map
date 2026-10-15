"""Build the interactive page: python3 -I build_web.py GTFS_DIR WORK_DIR TEMPLATE.html OUT.html [YYYYMMDD]

Exports the whole service day (vectors + trips) as gzip+base64 JSON inlined in the HTML.
WORK_DIR must hold water.json / parks.json / roads.json from make_map.py (Overpass cache).
"""
import base64, gzip, json, sys
import numpy as np, pandas as pd
from shapely.geometry import LineString, Polygon

GTFS, WORK, TEMPLATE, OUT = sys.argv[1:5]
DATE = sys.argv[5] if len(sys.argv) > 5 else "20261020"
W, H = 1080, 1920
CENTER, CROP_PX, Z = (-75.185, 40.00), 1650, 12
U = 10                                    # coordinate units per output px

def world_px(lon, lat):
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    n = 512 * 2 ** Z
    return ((lon + 180) / 360 * n,
            (1 - np.log(np.tan(np.radians(lat)) + 1 / np.cos(np.radians(lat))) / np.pi) / 2 * n)
cx, cy = world_px(*CENTER)
ox, oy = cx - CROP_PX / 2, cy - CROP_PX * H / W / 2
scale = W / CROP_PX
def to_out(lon, lat):
    x, y = world_px(lon, lat)
    return (x - ox) * scale, (y - oy) * scale

def enc(xy):
    """(n,2) px array -> delta-coded flat ints in 1/U px."""
    q = np.rint(np.asarray(xy) * U).astype(np.int64)
    d = np.diff(q, axis=0, prepend=np.zeros((1, 2), np.int64))
    return d.ravel().tolist()

def simp(xy, tol):
    if len(xy) < 3: return np.asarray(xy)
    return np.asarray(LineString(xy).simplify(tol, preserve_topology=False).coords)

# ----------------------------------------------------------------- basemap
def rings(el):
    if el["type"] == "way":
        return [[(p["lon"], p["lat"]) for p in el["geometry"]]]
    segs = [[(p["lon"], p["lat"]) for p in m["geometry"]] for m in el.get("members", [])
            if m.get("role") == "outer" and m.get("geometry")]
    out = []
    while segs:
        ring = segs.pop()
        while ring[0] != ring[-1]:
            for i, sg in enumerate(segs):
                if sg[0] == ring[-1]: ring += sg[1:]
                elif sg[-1] == ring[-1]: ring += sg[::-1][1:]
                elif sg[-1] == ring[0]: ring = sg[:-1] + ring
                elif sg[0] == ring[0]: ring = sg[::-1][:-1] + ring
                else: continue
                segs.pop(i); break
            else: break
        out.append(ring)
    return out

def poly_layer(name):
    out = []
    for el in json.load(open(f"{WORK}/{name}.json"))["elements"]:
        for r in rings(el):
            if len(r) < 4: continue
            xy = np.column_stack(to_out([p[0] for p in r], [p[1] for p in r]))
            xy = simp(xy, 0.25)
            if len(xy) >= 4 and Polygon(xy).area > 0.5: out.append(enc(xy))
    return out

base = {"water": poly_layer("water"), "parks": poly_layer("parks"), "roads": []}
for el in json.load(open(f"{WORK}/roads.json"))["elements"]:
    hw = el["tags"]["highway"]
    cls = 0 if hw.startswith(("motorway", "trunk")) else 1 if hw.startswith(("primary", "secondary")) else 2
    xy = np.column_stack(to_out([p["lon"] for p in el["geometry"]], [p["lat"] for p in el["geometry"]]))
    xy = simp(xy, 0.3)
    if len(xy) >= 2: base["roads"].append([cls, enc(xy)])
print("base:", {k: len(v) for k, v in base.items()})

# ------------------------------------------------------------------ transit
def secs(t):
    h, m, s = t.split(":"); return int(h) * 3600 + int(m) * 60 + int(s)

def active_services(d):
    cal = pd.read_csv(f"{d}/calendar.txt", dtype=str); cd = pd.read_csv(f"{d}/calendar_dates.txt", dtype=str)
    dow = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][pd.Timestamp(DATE).dayofweek]
    on = set(cal[(cal[dow] == "1") & (cal.start_date <= DATE) & (cal.end_date >= DATE)].service_id)
    on |= set(cd[(cd.date == DATE) & (cd.exception_type == "1")].service_id)
    return on - set(cd[(cd.date == DATE) & (cd.exception_type == "2")].service_id)

STRONG = {"L1": "0097D6", "B1": "F26100", "B2": "F26100", "B3": "F26100", "M1": "B35CFF"}
def route_class(r):
    if r.route_type == "2": return 2, "46E1C8"
    if r.route_type in ("0", "1"): return 1, STRONG.get(r.route_id) or r.route_color or "FFFFFF"
    return 0, "6096EB"

shapes, shape_idx, shape_cls, routes, route_idx, heads, head_idx = [], {}, {}, [], {}, [], {}
shape_geo = {}                              # shape index -> (pts, cum, seglen)
veh, T, D = [], [], []

def project(pts, cum, seg_a, seg_ab, seg_len, stops):
    prev_seg, prev_d, out = 0, 0.0, []
    for p in stops:
        a, ab, sl = seg_a[prev_seg:], seg_ab[prev_seg:], seg_len[prev_seg:]
        t = np.clip(((p - a) * ab).sum(1) / np.maximum(sl ** 2, 1e-9), 0, 1)
        d = np.hypot(*(a + ab * t[:, None] - p).T)
        i = int(np.argmax(d <= d.min() + 2.0))
        prev_seg += i
        prev_d = max(prev_d, cum[prev_seg] + t[i] * sl[i])
        out.append(prev_d)
    return out

for feed in ("google_bus", "google_rail"):
    d = f"{GTFS}/{feed}"
    rts = pd.read_csv(f"{d}/routes.txt", dtype=str).fillna("")
    trips = pd.read_csv(f"{d}/trips.txt", dtype=str).fillna("")
    trips = trips[trips.service_id.isin(active_services(d))]
    rinfo = {r.route_id: r for r in rts.itertuples()}
    sh = pd.read_csv(f"{d}/shapes.txt", dtype={"shape_id": str}).sort_values(["shape_id", "shape_pt_sequence"])
    stops = pd.read_csv(f"{d}/stops.txt", dtype={"stop_id": str})
    sx, sy = to_out(stops.stop_lon.astype(float).values, stops.stop_lat.astype(float).values)
    stop_xy = dict(zip(stops.stop_id, np.column_stack([sx, sy])))
    st = pd.read_csv(f"{d}/stop_times.txt", dtype=str,
                     usecols=["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"])
    st = st[st.trip_id.isin(trips.trip_id)].copy()
    st["arr"] = st.arrival_time.map(secs); st["dep"] = st.departure_time.map(secs); st["seq"] = st.stop_sequence.astype(int)
    st = st.sort_values(["trip_id", "seq"])
    tinfo = trips.set_index("trip_id")
    shp_groups = {k: g for k, g in sh.groupby("shape_id")}
    cache = {}
    for tid, g in st.groupby("trip_id", sort=False):
        info = tinfo.loc[tid]; r = rinfo[info.route_id]
        cls, color = route_class(r)
        key = (feed, info.shape_id)
        if key not in shape_idx and info.shape_id in shp_groups:
            s = shp_groups[info.shape_id]
            xy = simp(np.column_stack(to_out(s.shape_pt_lon.values, s.shape_pt_lat.values)), 0.12)
            if len(xy) < 2: continue
            shape_idx[key] = len(shapes); shape_cls[key] = (cls, color)
            shapes.append([cls, color, enc(xy)])
            ab = np.diff(xy, axis=0); sl = np.hypot(*ab.T)
            shape_geo[key] = (xy, np.r_[0, np.cumsum(sl)], xy[:-1], ab, sl)
        elif key in shape_idx and cls > shape_cls[key][0]:
            shapes[shape_idx[key]][0:2] = [cls, color]; shape_cls[key] = (cls, color)
        if key not in shape_idx: continue
        pts = np.array([stop_xy[s] for s in g.stop_id])
        ck = (key, tuple(g.stop_id))
        if ck not in cache:
            xy, cum, a, ab, sl = shape_geo[key]
            cache[ck] = project(xy, cum, a, ab, sl, pts)
        dist = cache[ck]
        ts, ds = [], []
        for arr, dep, dd in zip(g.arr.values, g.dep.values, dist):
            ts.append(int(arr)); ds.append(dd)
            if dep != arr: ts.append(int(dep)); ds.append(dd)
        ts = np.maximum.accumulate(np.array(ts)); dq = np.rint(np.array(ds) * U).astype(np.int64)
        if r.route_id not in route_idx:
            route_idx[r.route_id] = len(routes)
            routes.append([r.route_short_name or r.route_id, r.route_long_name, cls, color])
        h = info.trip_headsign
        if h not in head_idx: head_idx[h] = len(heads); heads.append(h)
        veh += [shape_idx[key], route_idx[r.route_id], head_idx[h], len(T), len(ts)]
        T += np.diff(ts, prepend=0).tolist(); D += np.diff(dq, prepend=0).tolist()
    print(feed, "vehicles so far:", len(veh) // 5)

payload = {"date": DATE, "u": U, "base": base, "shapes": shapes, "routes": routes, "heads": heads,
           "veh": veh, "T": T, "D": D, "view": {"w": W, "h": H}}
raw = json.dumps(payload, separators=(",", ":")).encode()
gz = gzip.compress(raw, 9)
print(f"trips {len(veh)//5}, points {len(T)}, raw {len(raw)/1e6:.1f} MB, gz {len(gz)/1e6:.1f} MB")
html = open(TEMPLATE).read().replace("__DATA__", base64.b64encode(gz).decode())
open(OUT, "w").write(html)
print("wrote", OUT, f"{len(html)/1e6:.1f} MB")
