"""Scan every feed's raw shapes for long straight hops (chords) inside each city's extent.

    python3 -I tools/scan_chords.py --config tools/cities.json --feeds FEEDS_DIR --work WORK_DIR [CITY ...]

A real road/track shape has a vertex every ~50-200 m; a chord across a city is one hop of many km.
Prints, per feed: shapes inside the extent, how many contain a hop > HOP_KM, and the routes involved.
"""
import argparse, io, json, os, zipfile
import numpy as np, pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("cities", nargs="*"); ap.add_argument("--config", required=True); ap.add_argument("--feeds", required=True)
ap.add_argument("--hop-km", type=float, default=3.0)
a = ap.parse_args()
CFG = json.load(open(a.config))
R, MPP = 6378137.0, 20.0

def bbox(cfg):
    clon, clat = cfg["center"]; exk, eyk = cfg["ext_km"]
    dlat = eyk * 1000 / 111320; dlon = exk * 1000 / (111320 * np.cos(np.radians(clat)))
    return clon - dlon, clat - dlat, clon + dlon, clat + dlat

def open_member(path, name, inner=None):
    p = os.path.join(a.feeds, path)
    if os.path.isdir(p):
        f = os.path.join(p, name); return open(f, "rb") if os.path.exists(f) else None
    z = zipfile.ZipFile(p)
    if inner: z = zipfile.ZipFile(io.BytesIO(z.read(inner)))
    names = {os.path.basename(n): n for n in z.namelist()}
    return z.open(names[name]) if name in names else None

for city, cfg in CFG.items():
    if a.cities and city not in a.cities: continue
    W, S, E, N = bbox(cfg)
    for fs in cfg["feeds"]:
        f = open_member(fs["path"], "shapes.txt", fs.get("inner"))
        if f is None:
            print(f"{city:14s} {fs['label']:8s} no shapes.txt (stop-to-stop / snapped)"); continue
        best, inside = {}, {}
        prev = None
        for ch in pd.read_csv(f, dtype={"shape_id": str}, chunksize=2_000_000, usecols=["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"]):
            ch = ch.sort_values(["shape_id", "shape_pt_sequence"], kind="stable") if not ch.shape_id.is_monotonic_increasing else ch
            if prev is not None: ch = pd.concat([prev, ch])
            prev = ch.iloc[[-1]]
            la, lo = ch.shape_pt_lat.values, ch.shape_pt_lon.values
            hop = np.r_[0, np.hypot((la[1:] - la[:-1]) * 111320, (lo[1:] - lo[:-1]) * 111320 * np.cos(np.radians(la[1:])))]
            same = np.r_[False, ch.shape_id.values[1:] == ch.shape_id.values[:-1]]
            hop = np.where(same, hop, 0)
            ins = (lo > W) & (lo < E) & (la > S) & (la < N)
            g = pd.DataFrame({"s": ch.shape_id.values, "hop": hop, "ins": ins}).groupby("s").agg(hop=("hop", "max"), ins=("ins", "max"))
            for s, r in g.iterrows():
                best[s] = max(best.get(s, 0), r.hop); inside[s] = inside.get(s, False) or bool(r.ins)
        shp = pd.Series(best)[[s for s, v in inside.items() if v]]
        bad = shp[shp > a.hop_km * 1000]
        line = f"{city:14s} {fs['label']:8s} shapes in extent {len(shp):6d}   with a >{a.hop_km:g} km hop: {len(bad):5d} ({100 * len(bad) / max(1, len(shp)):.1f}%)"
        t = open_member(fs["path"], "trips.txt", fs.get("inner")); r = open_member(fs["path"], "routes.txt", fs.get("inner"))
        if len(bad) and t is not None and r is not None:
            tr = pd.read_csv(t, dtype=str, keep_default_na=False, usecols=lambda c: c in ("route_id", "shape_id")).drop_duplicates()
            rt = pd.read_csv(r, dtype=str, keep_default_na=False)
            m = tr[tr.shape_id.isin(bad.index)].merge(rt[["route_id", "route_type", "route_short_name"]], on="route_id")
            line += f"   routes: {m.route_id.nunique()}  types {m.route_type.value_counts().to_dict()}  e.g. {list(m.route_short_name.unique()[:6])}"
        print(line, flush=True)
