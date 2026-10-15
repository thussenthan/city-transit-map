"""Write data/cities.json (tab order = tools/cities.json order) from the per-city *.meta.json files.

    python3 -I tools/make_manifest.py tools/cities.json data
"""
import json, os, sys
cfg, out = sys.argv[1:3]
conf = json.load(open(cfg)); order = list(conf)
manifest = []
for cid in order:
    p = os.path.join(out, cid + ".meta.json")
    if os.path.exists(p) and os.path.exists(os.path.join(out, cid + ".bin")):
        meta = json.load(open(p)); meta["tz"] = conf[cid].get("tz", ""); manifest.append(meta)
json.dump(manifest, open(os.path.join(out, "cities.json"), "w"), ensure_ascii=False, indent=1)
print("manifest:", [m["id"] for m in manifest])
