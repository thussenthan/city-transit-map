"""Fetch basemap vectors (water incl. ocean, parks, major roads) for one city from Overture Maps.

    python3 tools/fetch_base.py CITY --config tools/cities.json --work WORK_DIR [--release 2026-09-23.1]

Needs `duckdb` and `shapely`.  Writes WORK_DIR/CITY/base_raw.json (lon/lat), read by build_city.py.
"""
import argparse, json, os, time
import duckdb, numpy as np
from shapely import wkb
from shapely.geometry import box, Polygon, MultiPolygon, LineString, MultiLineString
from shapely.ops import unary_union

ap = argparse.ArgumentParser()
ap.add_argument("city"); ap.add_argument("--config", required=True); ap.add_argument("--work", required=True)
ap.add_argument("--release", default="2026-09-23.1")
a = ap.parse_args()
cfg = json.load(open(a.config))[a.city]
out_dir = os.path.join(a.work, a.city); os.makedirs(out_dir, exist_ok=True)

# same extent maths as build_city.py
R, MPP = 6378137.0, 20.0
clon, clat = cfg["center"]; exk, eyk = cfg["ext_km"]
K = np.cos(np.radians(clat)); mxc, myc = R * np.radians(clon), R * np.log(np.tan(np.pi / 4 + np.radians(clat) / 2))
def to_ll(x, y, W=2 * exk * 1000 / MPP, H=2 * eyk * 1000 / MPP):
    mx, my = mxc + (x - W / 2) * MPP / K, myc - (y - H / 2) * MPP / K
    return float(np.degrees(mx / R)), float(np.degrees(2 * np.arctan(np.exp(my / R)) - np.pi / 2))
W_, N_ = to_ll(0, 0); E_, S_ = to_ll(2 * exk * 1000 / MPP, 2 * eyk * 1000 / MPP)
bbox = box(W_, S_, E_, N_)
print(a.city, "bbox", [round(v, 3) for v in (S_, W_, N_, E_)], flush=True)

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2'; SET threads=4;")
base = f"s3://overturemaps-us-west-2/release/{a.release}"
where_box = f"bbox.xmin < {E_} AND bbox.xmax > {W_} AND bbox.ymin < {N_} AND bbox.ymax > {S_}"

def q(sql):
    t = time.time(); rows = con.execute(sql).fetchall(); print(f"  {len(rows)} rows, {time.time() - t:.0f}s", flush=True); return rows

def ring_list(g):
    """Polygon(s) -> list of rings [[lon,lat],...] (exteriors and holes; fill with even-odd)."""
    out = []
    for p in (g.geoms if hasattr(g, "geoms") else [g]):
        if p.geom_type != "Polygon" or p.is_empty: continue
        out.append(np.round(np.array(p.exterior.coords), 6).tolist())
        out += [np.round(np.array(i.coords), 6).tolist() for i in p.interiors if Polygon(i).area > 1e-9]
    return out

print("water", flush=True)
rows = q(f"SELECT ST_AsWKB(geometry) FROM read_parquet('{base}/theme=base/type=water/*', hive_partitioning=1) WHERE {where_box}")
polys = []
for (b,) in rows:
    g = wkb.loads(bytes(b))
    if g.geom_type in ("Polygon", "MultiPolygon"):
        g = g.buffer(0).intersection(bbox)
        if not g.is_empty: polys.append(g)
water = ring_list(unary_union(polys)) if polys else []

print("parks", flush=True)
rows = q(f"""SELECT ST_AsWKB(geometry) FROM read_parquet('{base}/theme=base/type=land_use/*', hive_partitioning=1)
             WHERE {where_box} AND subtype IN ('park','recreation','protected','cemetery')""")
parks = []
for (b,) in rows:
    g = wkb.loads(bytes(b))
    if g.geom_type in ("Polygon", "MultiPolygon"):
        g = g.buffer(0).intersection(bbox)
        for p in (g.geoms if hasattr(g, "geoms") else [g]):
            if p.geom_type == "Polygon" and p.area > 2e-8: parks.append(np.round(np.array(p.exterior.coords), 6).tolist())

print("roads", flush=True)
rows = q(f"""SELECT class, ST_AsWKB(geometry) FROM read_parquet('{base}/theme=transportation/type=segment/*', hive_partitioning=1)
             WHERE {where_box} AND subtype = 'road' AND class IN ('motorway','trunk','primary','secondary','tertiary')""")
roads = []
RANK = {"motorway": 0, "trunk": 0, "primary": 1, "secondary": 1, "tertiary": 2}
for cl, b in rows:
    g = wkb.loads(bytes(b))
    for ln in (g.geoms if hasattr(g, "geoms") else [g]):
        if ln.geom_type == "LineString" and len(ln.coords) > 1:
            roads.append([RANK[cl], np.round(np.array(ln.coords), 6).tolist()])
json.dump({"water": water, "parks": parks, "roads": roads}, open(os.path.join(out_dir, "base_raw.json"), "w"))
print(f"DONE {a.city}: water rings {len(water)}, parks {len(parks)}, roads {len(roads)}", flush=True)
