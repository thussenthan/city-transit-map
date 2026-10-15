"""Philadelphia: every scheduled SEPTA vehicle over 20 minutes of the timetable.

Usage: python3 -I make_map.py GTFS_DIR WORK_DIR OUT.mp4 [YYYYMMDD] [HH:MM]
GTFS_DIR holds google_bus/ and google_rail/ (SEPTA gtfs_public.zip, unzipped).
"""
import io, math, os, subprocess, sys, urllib.parse, urllib.request
import numpy as np, pandas as pd
from PIL import Image, ImageDraw, ImageFont

GTFS, WORK, OUT = sys.argv[1:4]
DATE = sys.argv[4] if len(sys.argv) > 4 else "20261020"      # a Tuesday
START = sys.argv[5] if len(sys.argv) > 5 else "08:00"
WINDOW_S = 20 * 60
W, H = 1080, 1920
FPS, SECS = 30, 10
SS = 2                                   # supersampling for lines/dots
CENTER = (-75.185, 40.00)               # lon, lat
CROP_PX = 1650                           # width in z12@2x world pixels (~22 km)
Z = 12
os.makedirs(WORK, exist_ok=True)

# ---------------------------------------------------------------- projection
def world_px(lon, lat):
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    n = 512 * 2 ** Z
    x = (lon + 180) / 360 * n
    y = (1 - np.log(np.tan(np.radians(lat)) + 1 / np.cos(np.radians(lat))) / np.pi) / 2 * n
    return x, y

cx, cy = world_px(*CENTER)
crop_h = CROP_PX * H / W
ox, oy = cx - CROP_PX / 2, cy - crop_h / 2
scale = W / CROP_PX

def to_out(lon, lat):
    x, y = world_px(lon, lat)
    return (x - ox) * scale, (y - oy) * scale

# ------------------------------------------------------------------ basemap
import json
BBOX = (39.78, -75.36, 40.20, -74.90)        # S, W, N, E  (Overpass order)

def overpass(name, body):
    path = os.path.join(WORK, name)
    if not os.path.exists(path):
        q = f"[out:json][timeout:180];({body});out geom;"
        req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                                     data=urllib.parse.urlencode({"data": q}).encode(),
                                     headers={"User-Agent": "philly-transit-map/1.0"})
        import time
        for wait in (0, 30, 60, 120, 180):
            time.sleep(wait)
            try:
                data = urllib.request.urlopen(req, timeout=240).read()
                json.loads(data); open(path, "wb").write(data); break
            except (urllib.error.URLError, ValueError) as e:
                print("overpass", e, "- retrying", flush=True)
        else:
            raise SystemExit("Overpass unavailable")
    return json.load(open(path))["elements"]

def rings(el):
    """Closed rings (lists of (lon, lat)) from a way or a multipolygon relation."""
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
            else:
                break
        out.append(ring)
    return out

def basemap():
    path = os.path.join(WORK, "base.png")
    if os.path.exists(path):
        return Image.open(path).convert("RGB")
    bb = "%s,%s,%s,%s" % BBOX
    water = overpass("water.json", f'way["natural"="water"]({bb});way["waterway"="riverbank"]({bb});'
                                   f'rel["natural"="water"]({bb});rel["waterway"="riverbank"]({bb});')
    parks = overpass("parks.json", f'way["leisure"~"park|golf_course|nature_reserve"]({bb});'
                                   f'way["landuse"~"cemetery|recreation_ground"]({bb});'
                                   f'rel["leisure"~"park|golf_course|nature_reserve"]({bb});')
    roads = overpass("roads.json", f'way["highway"~"^(motorway|trunk|primary|secondary|tertiary)(_link)?$"]({bb});')
    img = Image.new("RGB", (W * SS, H * SS), (30, 30, 33))
    d = ImageDraw.Draw(img)
    xy = lambda pts: [tuple(p * SS) for p in np.column_stack(to_out([q[0] for q in pts], [q[1] for q in pts]))]
    for el in parks:
        for r in rings(el):
            if len(r) > 2: d.polygon(xy(r), fill=(34, 38, 35))
    for el in roads:
        hw = el["tags"]["highway"]
        major = hw.startswith(("motorway", "trunk"))
        col = (62, 62, 68) if major else ((52, 52, 57) if hw.startswith(("primary", "secondary")) else (43, 43, 47))
        wd = (4 if major else 3 if hw.startswith(("primary", "secondary")) else 2)
        d.line(xy([(p["lon"], p["lat"]) for p in el["geometry"]]), fill=col, width=wd, joint="curve")
    for el in water:
        for r in rings(el):
            if len(r) > 2: d.polygon(xy(r), fill=(11, 11, 13))
    img = img.resize((W, H), Image.LANCZOS)
    img.save(path)
    return img

# --------------------------------------------------------------------- data
def secs(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)

def active_services(d):
    cal = pd.read_csv(f"{d}/calendar.txt", dtype=str)
    cd = pd.read_csv(f"{d}/calendar_dates.txt", dtype=str)
    dow = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][
        pd.Timestamp(DATE).dayofweek]
    on = set(cal[(cal[dow] == "1") & (cal.start_date <= DATE) & (cal.end_date >= DATE)].service_id)
    on |= set(cd[(cd.date == DATE) & (cd.exception_type == "1")].service_id)
    on -= set(cd[(cd.date == DATE) & (cd.exception_type == "2")].service_id)
    return on

# colour / style by mode (RGBA); drawn back to front
STRONG = {"L1": "0097D6", "B1": "F26100", "B2": "F26100", "B3": "F26100", "M1": "B35CFF"}
def style(route):
    rid, rtype, color = route.route_id, route.route_type, route.route_color
    if rtype == "2":
        return 1, (70, 225, 200, 230), 3.0, 3.2           # Regional Rail
    if rtype in ("0", "1"):
        c = STRONG.get(rid) or color or "FFFFFF"
        rgb = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
        return 2, rgb + (255,), 3.6, 3.4                   # subway / trolley
    return 0, (96, 150, 235, 165), 1.0, 1.3                # bus / trolleybus

def load(feed):
    d = f"{GTFS}/{feed}"
    routes = pd.read_csv(f"{d}/routes.txt", dtype=str)
    trips = pd.read_csv(f"{d}/trips.txt", dtype=str)
    trips = trips[trips.service_id.isin(active_services(d))]
    shapes = pd.read_csv(f"{d}/shapes.txt", dtype={"shape_id": str})
    stops = pd.read_csv(f"{d}/stops.txt", dtype={"stop_id": str})
    st = pd.read_csv(f"{d}/stop_times.txt", dtype=str,
                     usecols=["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"])
    return routes, trips, shapes, stops, st

t0 = secs(START + ":00")
t1 = t0 + WINDOW_S

shape_xy, shape_style, vehicles = {}, {}, []
for feed in ("google_bus", "google_rail"):
    routes, trips, shapes, stops, st = load(feed)
    print(feed, "active trips:", len(trips))
    rstyle = {r.route_id: style(r) for r in routes.itertuples()}
    trips["style"] = trips.route_id.map(rstyle)
    # shapes in output-pixel space
    shapes = shapes.sort_values(["shape_id", "shape_pt_sequence"])
    for sid, g in shapes[shapes.shape_id.isin(trips.shape_id.dropna().unique())].groupby("shape_id"):
        x, y = to_out(g.shape_pt_lon.values, g.shape_pt_lat.values)
        shape_xy[(feed, sid)] = np.column_stack([x, y])
    for r in trips.itertuples():
        shape_style.setdefault((feed, r.shape_id), r.style)
        if r.style[0] > shape_style[(feed, r.shape_id)][0]:
            shape_style[(feed, r.shape_id)] = r.style
    # stop positions
    sx, sy = to_out(stops.stop_lon.astype(float).values, stops.stop_lat.astype(float).values)
    stop_xy = dict(zip(stops.stop_id, zip(sx, sy)))
    # only trips overlapping the window
    st = st[st.trip_id.isin(trips.trip_id)].copy()
    st["arr"] = st.arrival_time.map(secs); st["dep"] = st.departure_time.map(secs)
    st["seq"] = st.stop_sequence.astype(int)
    st = st.sort_values(["trip_id", "seq"])
    span = st.groupby("trip_id").agg(a=("arr", "min"), b=("dep", "max"))
    keep = span[(span.b >= t0) & (span.a <= t1)].index
    st = st[st.trip_id.isin(keep)]
    tinfo = trips.set_index("trip_id")
    cache = {}
    for tid, g in st.groupby("trip_id"):
        info = tinfo.loc[tid]
        pts = np.array([stop_xy[s] for s in g.stop_id])
        times = np.empty(len(g) * 2); times[0::2] = g.arr.values; times[1::2] = g.dep.values
        times = np.maximum.accumulate(times)
        shp = shape_xy.get((feed, info.shape_id))
        if shp is not None and len(shp) > 1:
            key = (feed, info.shape_id, tuple(g.stop_id))
            if key not in cache:
                cum = np.r_[0, np.cumsum(np.hypot(*np.diff(shp, axis=0).T))]
                prev, dists = 0, []
                for p in pts:
                    d = np.hypot(*(shp[prev:] - p).T)
                    j = prev + int(np.argmax(d <= d.min() + 4))     # first near-best pass
                    dists.append(cum[j]); prev = j
                cache[key] = (cum, np.maximum.accumulate(np.array(dists)))
            cum, dists = cache[key]
            vd = np.repeat(dists, 2)
            vehicles.append((times, vd, shp, cum, info.style[2]))
        else:                                                      # straight-line fallback
            seg = np.r_[0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
            vehicles.append((times, np.repeat(seg, 2), pts, seg, info.style[2]))
print("vehicles in window:", len(vehicles))

# ------------------------------------------------------------------ drawing
base = basemap()
lines = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
ld = ImageDraw.Draw(lines)
order = sorted(shape_xy, key=lambda k: shape_style.get(k, (0,))[0])
for k in order:
    z, rgba, width, _ = shape_style.get(k, (0, (96, 150, 235, 165), 1.0, 1.3))
    ld.line([tuple(p) for p in (shape_xy[k] * SS)], fill=rgba, width=max(1, round(width * SS / 2)),
            joint="curve")
lines = lines.resize((W, H), Image.LANCZOS)
base = Image.alpha_composite(base.convert("RGBA"), lines)

fnt = lambda s, i=0: ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", s, index=i)
ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
od.text((44, 40), "Philadelphia", font=fnt(92), fill=(255, 255, 255, 255))
od.text((46, 152), "SEPTA public transport", font=fnt(46), fill=(255, 255, 255, 170))
od.text((46, 214), "every scheduled vehicle · 20 minutes of the timetable",
        font=fnt(30), fill=(255, 255, 255, 110))
od.text((W // 2, H - 34), "basemap © OpenStreetMap contributors · data: SEPTA GTFS",
        font=fnt(22), fill=(255, 255, 255, 80), anchor="mm")
base = Image.alpha_composite(base, ov)

def positions(t):
    out = []
    for times, vd, shp, cum, r in vehicles:
        if t < times[0] or t > times[-1]:
            continue
        d = np.interp(t, times, vd)
        out.append((np.interp(d, cum, shp[:, 0]), np.interp(d, cum, shp[:, 1]), r))
    return out

ff = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
     "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
     "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
clock = fnt(60)
for f in range(FPS * SECS):
    t = t0 + WINDOW_S * f / (FPS * SECS)
    dots = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    for x, y, r in positions(t):
        x, y, rr = x * SS, y * SS, r * SS
        if r > 3:                                                 # soft glow on rail
            dd.ellipse([x - rr * 1.9, y - rr * 1.9, x + rr * 1.9, y + rr * 1.9], fill=(255, 255, 255, 40))
        dd.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(255, 255, 255, 255))
    frame = Image.alpha_composite(base, dots.resize((W, H), Image.BOX))
    hh, mm = int(t // 3600), int(t % 3600 // 60)
    ImageDraw.Draw(frame).text((W - 44, 44), f"{hh:02d}:{mm:02d}", font=clock,
                               fill=(255, 255, 255, 255), anchor="ra")
    ff.stdin.write(frame.convert("RGB").tobytes())
    if f % 30 == 0:
        print("frame", f, flush=True)
ff.stdin.close(); ff.wait()
print("wrote", OUT)
