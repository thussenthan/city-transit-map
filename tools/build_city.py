"""Build one city's data file for the City Transit Map page.

    python3 -I tools/build_city.py CITY --config tools/cities.json --feeds FEEDS_DIR --work WORK_DIR --out data

FEEDS_DIR/<path from config> is a GTFS .zip or an unzipped folder.  Output: OUT/CITY.bin (gzip JSON) and
OUT/CITY.meta.json.  OSM basemap data is fetched from Overpass and cached in WORK_DIR/CITY/.
Everything is drawn in a local pixel space, 1 px = MPP metres, origin top-left of the city's extent box.
"""
import argparse, gzip, json, os, sys, time, urllib.parse, urllib.request, urllib.error, zipfile
from collections import Counter
import numpy as np, pandas as pd
from shapely.geometry import LineString, Polygon, box
from shapely.ops import linemerge, polygonize, unary_union

ap = argparse.ArgumentParser()
ap.add_argument("city"); ap.add_argument("--config", required=True); ap.add_argument("--feeds", required=True)
ap.add_argument("--work", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--date", help="force YYYYMMDD for every feed")
args = ap.parse_args()
CFG = json.load(open(args.config))[args.city]
WORK = os.path.join(args.work, args.city); os.makedirs(WORK, exist_ok=True); os.makedirs(args.out, exist_ok=True)

MPP, U = 20.0, 10                      # metres per px, coordinate units per px in the file
R = 6378137.0
clon, clat = CFG["center"]; exk, eyk = CFG["ext_km"]
WPX, HPX = 2 * exk * 1000 / MPP, 2 * eyk * 1000 / MPP
K = np.cos(np.radians(clat))
mxc, myc = R * np.radians(clon), R * np.log(np.tan(np.pi / 4 + np.radians(clat) / 2))

def to_px(lon, lat):
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    mx, my = R * np.radians(lon), R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    return WPX / 2 + (mx - mxc) * K / MPP, HPX / 2 - (my - myc) * K / MPP

def to_ll(x, y):
    mx, my = mxc + (x - WPX / 2) * MPP / K, myc - (y - HPX / 2) * MPP / K
    return float(np.degrees(mx / R)), float(np.degrees(2 * np.arctan(np.exp(my / R)) - np.pi / 2))

W0, N0 = to_ll(0, 0); E0, S0 = to_ll(WPX, HPX)
BBOX = (S0, W0, N0, E0)                # Overpass order
print(args.city, "bbox S,W,N,E:", [round(v, 3) for v in BBOX], "world px:", round(WPX), "x", round(HPX), flush=True)

def enc(xy):
    q = np.rint(np.asarray(xy) * U).astype(np.int64)
    return np.diff(q, axis=0, prepend=np.zeros((1, 2), np.int64)).ravel().tolist()

def simp(xy, tol):
    xy = np.asarray(xy)
    return xy if len(xy) < 3 else np.asarray(LineString(xy).simplify(tol, preserve_topology=False).coords)

# ----------------------------------------------------------------- basemap
def build_base():
    """Basemap vectors come from tools/fetch_base.py (Overture Maps) as WORK/CITY/base_raw.json."""
    raw = json.load(open(os.path.join(WORK, "base_raw.json")))
    base = {"water": [], "parks": [], "roads": []}
    for r in raw["water"]:
        xy = simp(np.column_stack(to_px([p[0] for p in r], [p[1] for p in r])), 0.25)
        if len(xy) >= 4: base["water"].append(enc(xy))
    for r in raw["parks"]:
        xy = simp(np.column_stack(to_px([p[0] for p in r], [p[1] for p in r])), 0.3)
        if len(xy) >= 4 and Polygon(xy).area > 1.0: base["parks"].append(enc(xy))
    for cls, g in raw["roads"]:
        xy = simp(np.column_stack(to_px([p[0] for p in g], [p[1] for p in g])), 0.3)
        if len(xy) >= 2: base["roads"].append([cls, enc(xy)])
    print("  base:", {k: len(v) for k, v in base.items()}, flush=True)
    return base

# --------------------------------------------------------------------- gtfs
def secs_col(s):
    p = s.str.strip().str.split(":", expand=True)
    return (pd.to_numeric(p[0], errors="coerce") * 3600 + pd.to_numeric(p[1], errors="coerce") * 60
            + pd.to_numeric(p[2], errors="coerce")).to_numpy()

def feed_dir(spec, inner=None):
    """GTFS folder for a feed: an unzipped dir, a .zip, or (inner=...) a .zip nested inside a .zip (Melbourne)."""
    import io
    p = os.path.join(args.feeds, spec)
    if p.endswith(".zip"):
        d = os.path.join(WORK, "gtfs_" + os.path.basename(p)[:-4] + ("_" + inner.replace("/", "_")[:-4] if inner else ""))
        if not os.path.exists(os.path.join(d, "routes.txt")):
            os.makedirs(d, exist_ok=True)
            with zipfile.ZipFile(p) as outer:
                z = zipfile.ZipFile(io.BytesIO(outer.read(inner))) if inner else outer
                for n in z.namelist():
                    if n.endswith(".txt"):
                        open(os.path.join(d, os.path.basename(n)), "wb").write(z.read(n))
        return d
    return p

def csv(d, name, **kw):
    f = os.path.join(d, name)
    return pd.read_csv(f, dtype=str, keep_default_na=False, **kw) if os.path.exists(f) else None

def service_dates(d):
    """service_id -> set(ints yyyymmdd) is too big; return function date -> set(service_id)."""
    cal, cd = csv(d, "calendar.txt"), csv(d, "calendar_dates.txt")
    def active(date):
        on = set()
        if cal is not None:
            dow = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][pd.Timestamp(date).dayofweek]
            on = set(cal[(cal[dow] == "1") & (cal.start_date <= date) & (cal.end_date >= date)].service_id)
        if cd is not None:
            on |= set(cd[(cd.date == date) & (cd.exception_type == "1")].service_id)
            on -= set(cd[(cd.date == date) & (cd.exception_type == "2")].service_id)
        return on
    span = (min(cal.start_date.min() if cal is not None else "99999999", cd.date.min() if cd is not None else "99999999"),
            max(cal.end_date.max() if cal is not None else "0", cd.date.max() if cd is not None else "0"))
    return active, span

def pick_date(d, trips):
    active, span = service_dates(d)
    cands = [(pd.Timestamp("2026-10-20") + pd.Timedelta(days=7 * k)).strftime("%Y%m%d") for k in range(10)]
    counts = [int(trips.service_id.isin(active(c)).sum()) for c in cands]
    if args.date: return args.date, active(args.date), counts
    if max(counts) == 0:                                      # feed is outside the usual window: use its last Tuesday
        t = pd.Timestamp(span[1])
        while t.dayofweek != 1: t -= pd.Timedelta(days=1)
        dt = t.strftime("%Y%m%d"); return dt, active(dt), counts
    best = next(c for c, n in zip(cands, counts) if n >= 0.9 * max(counts))
    return best, active(best), counts

def route_class(rtype):
    try: t = int(rtype)
    except ValueError: return 0
    if t in (0, 1, 5, 7, 12) or 400 <= t < 500 or 900 <= t < 1000 or t == 1400: return 1
    if t == 2 or 100 <= t < 200: return 2
    if t in (4, 6) or 1000 <= t < 1400: return -1              # ferry / gondola: skipped
    return 0

DEFAULT = {0: "6096EB", 1: "E6E6E6", 2: "46E1C8"}
def pick_color(cls, c):
    if cls != 1: return DEFAULT[cls]
    c = (c or "").strip().lstrip("#").upper()
    if len(c) != 6: return DEFAULT[1]
    try: r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError: return DEFAULT[1]
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    if lum < 0.42:                                             # lift dark colours so they read on the dark map
        f = (0.42 - lum) / (1 - lum) + 0.08
        r, g, b = (int(v + (255 - v) * f) for v in (r, g, b))
    return "%02X%02X%02X" % (r, g, b)

def rdp_keep(t, d, tol):
    n = len(t); keep = np.zeros(n, bool); keep[0] = keep[-1] = True; stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1: continue
        dt = t[j] - t[i]
        interp = d[i] + (d[j] - d[i]) * ((t[i + 1:j] - t[i]) / dt) if dt > 0 else np.full(j - i - 1, d[i])
        err = np.abs(d[i + 1:j] - interp); k = int(err.argmax())
        if err[k] > tol:
            m = i + 1 + k; keep[m] = True; stack += [(i, m), (m, j)]
    return keep

def project(cum, seg_a, seg_ab, seg_len, pts):
    prev_seg, prev_d, out = 0, 0.0, []
    for p in pts:
        a, ab, sl = seg_a[prev_seg:], seg_ab[prev_seg:], seg_len[prev_seg:]
        t = np.clip(((p - a) * ab).sum(1) / np.maximum(sl ** 2, 1e-9), 0, 1)
        dd = np.hypot(*(a + ab * t[:, None] - p).T)
        i = int(np.argmax(dd <= dd.min() + 2.0))
        prev_seg += i; prev_d = max(prev_d, cum[prev_seg] + t[i] * sl[i]); out.append(prev_d)
    return np.array(out)

class Router:
    """Snap stop sequences to a network (fetch_base.py graph*.npz): shortest path between consecutive stops.
    allowed: optional {edge class name: cost multiplier} (rail graph) restricting which track a route may use."""
    def __init__(self, npz="graph.npz", allowed=None, snap_px=12.0, strict=True, densify=0, bridge=0):
        from scipy.sparse import csr_matrix
        from scipy.spatial import cKDTree
        z = np.load(os.path.join(WORK, npz))
        u, v, w = z["u"].astype(np.int64), z["v"].astype(np.int64), z["w"].astype(np.float64) / MPP
        names = list(z["classes"]) if "classes" in z else []
        c = z["c"].astype(np.int64) if "c" in z else np.zeros(len(u), np.int64)
        if allowed is not None:
            keep = np.isin(c, [i for i, n in enumerate(names) if n in allowed]); u, v, w, c = u[keep], v[keep], w[keep], c[keep]
        used = np.unique(np.r_[u, v]); remap = -np.ones(len(z["node"]), np.int64); remap[used] = np.arange(len(used))
        u, v = remap[u], remap[v]
        nx, ny = to_px(z["node"][used, 0], z["node"][used, 1]); P = np.column_stack([nx, ny]); n = len(P)
        a, b = np.minimum(u, v), np.maximum(u, v)
        o = np.lexsort((w, b * n + a)); a, b, w, c = a[o], b[o], w[o], c[o]       # keep the lightest of duplicate edges
        first = np.r_[True, (a[1:] != a[:-1]) | (b[1:] != b[:-1])]; a, b, w, c = a[first], b[first], w[first], c[first]
        if densify:                                                            # long straight edges get intermediate nodes, so stops snap beside the track
            d = np.hypot(*(P[b] - P[a]).T); k = np.maximum(1, np.ceil(d / densify).astype(np.int64)); lg = k > 1
            if lg.any():
                la, lb, lk, lw, lc = a[lg], b[lg], k[lg], w[lg], c[lg]; tot = int((lk - 1).sum())
                rep = np.repeat(np.arange(len(la)), lk - 1)
                j = np.arange(tot) - np.repeat(np.cumsum(lk - 1) - (lk - 1), lk - 1) + 1
                tt = (j / lk[rep])[:, None]; newP = P[la[rep]] * (1 - tt) + P[lb[rep]] * tt
                nid = n + np.arange(tot); prev = np.where(j == 1, la[rep], nid - 1); last = n + np.cumsum(lk - 1) - 1
                a = np.concatenate([a[~lg], prev, last]); b = np.concatenate([b[~lg], nid, lb])
                w = np.concatenate([w[~lg], lw[rep] / lk[rep], lw / lk]); c = np.concatenate([c[~lg], lc[rep], lc])
                P = np.vstack([P, newP]); n += tot
        mult = np.array([allowed.get(nm, 1.0) for nm in names])[c] if allowed is not None else np.ones(len(a))
        pri = mult == 1.0                                                      # edges of the route's own track type
        w = w * mult
        if bridge:                                                             # join small disconnected pieces (tunnel portals, data gaps) to the main network
            from scipy.sparse.csgraph import connected_components
            comp = csr_matrix((np.ones(len(a)), (a, b)), shape=(n, n)); nc, lab = connected_components(comp, directed=False)
            if nc > 1:
                main = int(np.argmax(np.bincount(lab))); mnodes = np.flatnonzero(lab == main); small = np.flatnonzero(lab != main)
                dq, iq = cKDTree(P[mnodes]).query(P[small]); best = {}
                for sn, dd_, mi in zip(small, dq, mnodes[iq]):
                    c_ = lab[sn]
                    if dd_ <= bridge and (c_ not in best or dd_ < best[c_][0]): best[c_] = (dd_, sn, mi)
                if best:
                    ba = np.array([x[1] for x in best.values()]); bb = np.array([x[2] for x in best.values()]); bw = np.array([x[0] * 2.0 for x in best.values()])
                    a = np.r_[a, np.minimum(ba, bb)]; b = np.r_[b, np.maximum(ba, bb)]; w = np.r_[w, bw]; pri = np.r_[pri, np.zeros(len(ba), bool)]
        self.P = P
        self.g = csr_matrix((np.r_[w, w], (np.r_[a, b], np.r_[b, a])), shape=(n, n))
        pri_nodes = np.unique(np.r_[a[pri], b[pri]])
        self.tree = cKDTree(self.P); self.cache = {}; self.snap_px = snap_px; self.strict = strict; self.stats = Counter(); self.failed = []
        self.pri_nodes = pri_nodes; self.pri_tree = cKDTree(self.P[pri_nodes]) if len(pri_nodes) else None
        print(f"  router {npz} {sorted(allowed) if allowed else 'all'}: {n} nodes, {len(a)} edges", flush=True)
    def path(self, a, b):
        k = (a, b)
        if k not in self.cache:
            from scipy.sparse.csgraph import dijkstra
            chord = float(np.hypot(*(self.P[a] - self.P[b])))
            dist, pred = dijkstra(self.g, directed=True, indices=a, return_predecessors=True, limit=max(chord * 8.0, 80.0))
            if not np.isfinite(dist[b]):                                  # retry without the limit: detour vs. truly disconnected
                dist, pred = dijkstra(self.g, directed=True, indices=a, return_predecessors=True)
                self.stats["found-after-retry" if np.isfinite(dist[b]) else "disconnected"] += 1
                if not np.isfinite(dist[b]): self.failed.append((a, b))
            if not np.isfinite(dist[b]): self.cache[k] = None
            else:
                p = [b]
                while p[-1] != a: p.append(int(pred[p[-1]]))
                self.cache[k] = self.P[p[::-1]]
        return self.cache[k]
    def route(self, pts, strict=None, snap_px=None):
        strict = self.strict if strict is None else strict; snap = self.snap_px if snap_px is None else snap_px
        d, idx = self.tree.query(pts)
        if self.pri_tree is not None:                                          # prefer the route's own track type when it is near enough
            dp, ip = self.pri_tree.query(pts); use = dp <= snap
            d = np.where(use, dp, d); idx = np.where(use, self.pri_nodes[ip], idx)
        ok = d <= snap                                                         # stop within snap_px of the network
        out = [pts[0]]
        for i in range(1, len(pts)):
            pa = self.path(idx[i - 1], idx[i]) if ok[i - 1] and ok[i] and idx[i - 1] != idx[i] else None
            self.stats["routed" if pa is not None else "same-node" if idx[i - 1] == idx[i] else "far-from-network" if not (ok[i - 1] and ok[i]) else "no-path"] += 1
            if pa is not None: out.extend(pa)
            elif strict and np.hypot(*(pts[i] - pts[i - 1])) > 60.0: return None   # long unroutable jump: skip the trip
            out.append(pts[i])
        out = np.array(out); keep = np.r_[True, np.hypot(*np.diff(out, axis=0).T) > 1e-6]
        return out[keep]

ROUTER = Router(densify=5.0) if CFG.get("route_snap") and os.path.exists(os.path.join(WORK, "graph.npz")) else None

def repair_hops(xy, thresh=60.0):
    """Bus/coach shapes that are just a few far-apart points (a chord across the map): route each long hop along roads.
    Returns None if a long hop cannot be routed, so the caller can drop that trip rather than draw a straight line."""
    d = np.hypot(*np.diff(xy, axis=0).T)
    if ROUTER is None or d.max() <= thresh: return xy
    out = [xy[0]]
    for i in range(1, len(xy)):
        if d[i - 1] > thresh:
            seg = ROUTER.route(np.array([xy[i - 1], xy[i]]), strict=True, snap_px=25.0)
            if seg is None: return None
            out.extend(seg[1:])
        else: out.append(xy[i])
    return np.array(out)
RAIL_ROUTERS = {}
def rail_router(rtype):
    """Track a route type may run on, with a cost penalty for neighbouring track types (outer Tube lines are mapped as
    standard-gauge track in OSM, parts of the Elizabeth line as subway), so a Tube line still prefers subway track."""
    if not (CFG.get("rail_snap") and os.path.exists(os.path.join(WORK, "graph_rail.npz"))): return None
    try: t = int(rtype)
    except ValueError: t = 2
    allowed = ({"subway": 1.0, "standard_gauge": 3.0, "light_rail": 2.0} if t == 1
               else {"tram": 1.0, "light_rail": 1.0, "monorail": 1.0, "funicular": 1.0} if t in (0, 5, 7, 12)
               else {"standard_gauge": 1.0, "narrow_gauge": 1.0, "subway": 3.0, "light_rail": 2.0})
    key = tuple(sorted(allowed.items()))
    if key not in RAIL_ROUTERS: RAIL_ROUTERS[key] = Router("graph_rail.npz", allowed, snap_px=20.0, strict=False, densify=3.0, bridge=20.0)
    return RAIL_ROUTERS[key]

shapes, shape_meta, routes, route_idx, heads, head_idx = [], {}, [], {}, [], {}
veh, T, D = [], [], []
agencies, dates_used, feed_dates = [], [], []
IN = 40.0                                                   # px margin around the world for "inside"

def process_feed(fspec):
    label, spec = fspec["label"], fspec["path"]
    d = feed_dir(spec, fspec.get("inner")); t0 = time.time()
    rts = csv(d, "routes.txt"); trips = csv(d, "trips.txt"); stops = csv(d, "stops.txt")
    if fspec.get("agencies"): rts = rts[rts.agency_id.isin(fspec["agencies"])]      # use only some agencies from a mixed feed
    if fspec.get("route_types"): rts = rts[rts.route_type.isin(fspec["route_types"])]  # ...or only some raw route_type values
    date, on, counts = pick_date(d, trips)
    print(f"  [{label}] date {date} ({counts[0]} trips on first candidate, max {max(counts)})", flush=True)
    dates_used.append(date); feed_dates.append((fspec.get("name") or label, date))
    trips = trips[trips.service_id.isin(on)]
    if "shape_id" not in trips: trips["shape_id"] = ""
    if "trip_headsign" not in trips: trips["trip_headsign"] = ""
    rinfo = {}
    for r in rts.itertuples():
        cls = route_class(getattr(r, "route_type", "3"))
        if cls < 0: continue
        rinfo[r.route_id] = (cls, pick_color(cls, getattr(r, "route_color", "")),
                             getattr(r, "route_short_name", "") or r.route_id, getattr(r, "route_long_name", ""),
                             getattr(r, "route_type", "3"))
    trips = trips[trips.route_id.isin(rinfo)]
    sx, sy = to_px(pd.to_numeric(stops.stop_lon, errors="coerce").values, pd.to_numeric(stops.stop_lat, errors="coerce").values)
    stop_ids = stops.stop_id.values; sidx = {s: i for i, s in enumerate(stop_ids)}
    sxy = np.column_stack([sx, sy])
    s_in = (sx > -IN) & (sx < WPX + IN) & (sy > -IN) & (sy < HPX + IN)
    # frequencies (headway-based feeds)
    freq = csv(d, "frequencies.txt")
    freq_map = {}
    if freq is not None and len(freq):
        for f in freq.itertuples():
            freq_map.setdefault(f.trip_id, []).append((int(secs_col(pd.Series([f.start_time]))[0]),
                                                      int(secs_col(pd.Series([f.end_time]))[0]), max(int(f.headway_secs), 30)))
    # stop_times, chunked and compacted
    tid_code = {t: i for i, t in enumerate(trips.trip_id.values)}
    tcodes, tarr, tdep, tstop, tseq = [], [], [], [], []
    PREF = bool(CFG.get("prefilter"))                         # huge national feeds: drop stop rows outside the extent early
    for ch in pd.read_csv(os.path.join(d, "stop_times.txt"), dtype=str, keep_default_na=False, chunksize=1_500_000,
                          usecols=["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"]):
        code = ch.trip_id.map(tid_code); m = code.notna().to_numpy()
        sid = ch.stop_id.map(sidx).fillna(-1).to_numpy().astype(np.int64)
        m &= sid >= 0
        if PREF: m &= s_in[np.maximum(sid, 0)]
        if not m.any(): continue
        ch = ch[m]; code = code[m]; sid = sid[m]
        arr, dep = secs_col(ch.arrival_time), secs_col(ch.departure_time)
        arr = np.where(np.isnan(arr), dep, arr); dep = np.where(np.isnan(dep), arr, dep)
        tcodes.append(code.to_numpy().astype(np.int32)); tarr.append(arr); tdep.append(dep)
        tstop.append(sid.astype(np.int32)); tseq.append(pd.to_numeric(ch.stop_sequence).to_numpy())
    if not tcodes: print("  no stop_times for active trips"); return
    tc, ta, td, ts, tq = (np.concatenate(x) for x in (tcodes, tarr, tdep, tstop, tseq))
    ok = ts >= 0                                              # untimed stops are interpolated per trip below
    tc, ta, td, ts, tq = tc[ok], ta[ok], td[ok], ts[ok], tq[ok]
    order = np.lexsort((tq, tc)); tc, ta, td, ts = tc[order], ta[order], td[order], ts[order]
    bounds = np.r_[0, np.flatnonzero(np.diff(tc)) + 1, len(tc)]
    print(f"  [{label}] {len(bounds) - 1} trips / {len(tc)} stop times loaded in {time.time() - t0:.0f}s", flush=True)
    # shapes needed
    tinfo = trips.set_index("trip_id")
    need = set(tinfo.shape_id[tinfo.shape_id != ""].unique())
    if fspec.get("snap") == "rail": need = set()               # this feed's shapes are stop-to-stop chords: snap to real track instead
    shp = {}
    sf = os.path.join(d, "shapes.txt")
    if os.path.exists(sf) and need:
        parts = []
        for ch in pd.read_csv(sf, dtype={"shape_id": str}, chunksize=1_500_000, usecols=["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"]):
            ch = ch[ch.shape_id.isin(need)]
            if len(ch): parts.append(ch)
        if parts:
            sh = pd.concat(parts).sort_values(["shape_id", "shape_pt_sequence"])
            for sid, g in sh.groupby("shape_id", sort=False):
                shp[sid] = np.column_stack(to_px(g.shape_pt_lon.values, g.shape_pt_lat.values))
    geo_cache, pat_cache, shape_idx = {}, {}, {}
    codes = trips.trip_id.values
    skipped = made = 0
    for bi in range(len(bounds) - 1):
        a, b = bounds[bi], bounds[bi + 1]
        sidxs = ts[a:b]; inside = s_in[sidxs]
        if inside.sum() < 2: skipped += 1; continue
        first, last = max(int(np.argmax(inside)) - 1, 0), min(len(inside) - int(np.argmax(inside[::-1])), len(inside) - 1)
        sl = slice(a + first, a + last + 1)
        si, arr, dep = ts[sl], ta[sl], td[sl]
        if len(si) < 2: continue
        tid = codes[tc[a]]; info = tinfo.loc[tid]; cls, color, rshort, rlong, rtype = rinfo[info.route_id]
        pkey = (info.shape_id if info.shape_id in shp else None, tuple(si))
        if pkey not in pat_cache:
            routed = False
            if pkey[0] is not None:
                if pkey[0] not in geo_cache:
                    xy = shp[pkey[0]]
                    ins = np.flatnonzero((xy[:, 0] > -IN) & (xy[:, 0] < WPX + IN) & (xy[:, 1] > -IN) & (xy[:, 1] < HPX + IN))
                    if len(ins) >= 2: xy = xy[max(ins[0] - 1, 0): ins[-1] + 2]
                    if ROUTER is not None and cls == 0: xy = repair_hops(xy)
                    geo_cache[pkey[0]] = simp(xy, 0.15) if xy is not None else None
                xy = geo_cache[pkey[0]]
                if xy is None: pat_cache[pkey] = None; continue
                gk = (label, pkey[0])
            else:
                xy = sxy[list(si)]; gk = (label, "stops", pkey[1]); routed = False
                if ROUTER is not None and cls == 0 and len(xy) >= 2:
                    xy = ROUTER.route(xy)
                    if xy is None: pat_cache[pkey] = None; continue
                    xy = simp(xy, 0.15); gk = (label, "road", pkey[1]); routed = True
                elif fspec.get("snap") == "rail" and cls >= 1 and len(xy) >= 2 and rail_router(rtype) is not None:
                    xy = simp(rail_router(rtype).route(xy), 0.15); gk = (label, "track", rtype, pkey[1]); routed = True
            if len(xy) < 2: pat_cache[pkey] = None
            else:
                ab = np.diff(xy, axis=0); sl_ = np.hypot(*ab.T); cum = np.r_[0, np.cumsum(sl_)]
                dist = project(cum, xy[:-1], ab, sl_, sxy[list(si)]) if (pkey[0] is not None or routed) else cum
                pat_cache[pkey] = (gk, xy, dist)
        pc = pat_cache[pkey]
        if pc is None: continue
        gk, xy, dist = pc
        valid = ~np.isnan(arr)
        if valid.sum() < 2: continue
        if not valid.all():                                   # GTFS allows blank times between timepoints: interpolate by distance
            arr = np.where(valid, arr, np.interp(dist, dist[valid], arr[valid]))
            dep = np.where(np.isnan(dep), arr, dep)
        if gk not in shape_idx:
            shape_idx[gk] = len(shapes); shapes.append([cls, color, enc(xy)]); shape_meta[len(shapes) - 1] = cls
        elif cls > shapes[shape_idx[gk]][0]:
            shapes[shape_idx[gk]][0:2] = [cls, color]
        # (t, d) polyline: arrival and departure per stop, then thinned
        tt = np.empty(len(si) * 2); dd = np.empty(len(si) * 2)
        tt[0::2], tt[1::2] = arr, dep; dd[0::2] = dd[1::2] = dist
        tt = np.maximum.accumulate(tt)
        keep = np.ones(len(tt), bool); keep[1:] = (np.diff(tt) != 0) | (np.diff(dd) != 0)
        tt, dd = tt[keep], dd[keep]
        if len(tt) < 2: continue
        kp = rdp_keep(tt, dd, 0.5); tt, dd = tt[kp], dd[kp]
        rk = (label, info.route_id)
        if rk not in route_idx:
            route_idx[rk] = len(routes); routes.append([rshort, rlong, cls, color])
        hs = info.trip_headsign or rlong or ""
        if hs not in head_idx: head_idx[hs] = len(heads); heads.append(hs)
        offs = [0]
        if tid in freq_map:
            offs = []
            for s0, s1, hw in freq_map[tid]:
                offs += [x - tt[0] for x in range(s0, s1, hw)]
        elif freq_map and not tid in freq_map and False: pass
        dq = np.rint(dd * U).astype(np.int64)
        for off in offs:
            ts_i = np.rint(tt + off).astype(np.int64)
            veh.extend([shape_idx[gk], route_idx[rk], head_idx[hs], len(T), len(ts_i)])
            T.extend(np.diff(ts_i, prepend=0).tolist()); D.extend(np.diff(dq, prepend=0).tolist())
            made += 1
    print(f"  [{label}] vehicles made: {made} (trips outside extent skipped: {skipped}), {time.time() - t0:.0f}s", flush=True)

t_start = time.time()
base = build_base()
for fs in CFG["feeds"]:
    try: process_feed(fs)
    except Exception as e:
        import traceback; traceback.print_exc(); print("  feed failed:", fs["label"], flush=True)
for k_, r_ in RAIL_ROUTERS.items():
    print("  rail router", k_, dict(r_.stats), flush=True)
    for a_, b_ in r_.failed[:12]: print("    unroutable", [round(c, 4) for c in to_ll(*r_.P[a_])], "->", [round(c, 4) for c in to_ll(*r_.P[b_])], "chord km %.1f" % (np.hypot(*(r_.P[a_] - r_.P[b_])) * MPP / 1000), flush=True)
if ROUTER is not None: print("  road router", dict(ROUTER.stats), flush=True)
payload = {"id": args.city, "u": U, "base": base, "shapes": shapes, "routes": routes, "heads": heads,
           "veh": veh, "T": T, "D": D, "view": {"w": WPX, "h": HPX},
           "home": {"cx": WPX / 2, "cy": HPX / 2, "w": CFG["home_km"][0] * 1000 / MPP, "h": CFG["home_km"][1] * 1000 / MPP},
           "date": Counter(dates_used).most_common(1)[0][0] if dates_used else "", "dates": dict(feed_dates)}
raw = json.dumps(payload, separators=(",", ":")).encode()
gz = gzip.compress(raw, 9)
open(os.path.join(args.out, args.city + ".bin"), "wb").write(gz)
meta = {"id": args.city, "name": CFG["name"], "sub": CFG.get("sub", ""), "credit": CFG.get("credit", ""),
        "date": payload["date"], "dates": payload["dates"], "vehicles": len(veh) // 5, "bytes": len(gz)}
json.dump(meta, open(os.path.join(args.out, args.city + ".meta.json"), "w"))
print(f"DONE {args.city}: {len(veh) // 5} vehicles, {len(T)} points, raw {len(raw) / 1e6:.1f} MB, gz {len(gz) / 1e6:.2f} MB, {time.time() - t_start:.0f}s", flush=True)
