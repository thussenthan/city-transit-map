"""Look for vehicles that would teleport: zero-duration hops or implausible speeds in the built data.

    python3 -I tools/check_jumps.py data CITY [CITY ...]
"""
import gzip, json, sys
import numpy as np
folder, cities = sys.argv[1], sys.argv[2:]
print(f"{'city':14s} {'vehicles':>8s}   instant hop (dt=0, >10 m)     >250 km/h on a bus/tram/metro leg")
for city in cities:
    d = json.loads(gzip.decompress(open(f"{folder}/{city}.bin", "rb").read()))
    V = d["veh"]; T = np.array(d["T"], dtype=np.int64); D = np.array(d["D"], dtype=np.int64); st = 6 if "PC" in d else 5
    cls = [s[0] for s in d["shapes"]]
    n = len(V) // st; inst = fast = 0
    for k in range(n):
        off, cnt = V[st * k + 3], V[st * k + 4]
        if cnt < 2: continue
        t = np.cumsum(T[off:off + cnt]); dx = np.diff(np.cumsum(D[off:off + cnt]) / d["u"]); dt = np.diff(t)
        if np.any((dt <= 0) & (dx > 0.5)): inst += 1
        sp = np.where(dt > 0, dx * 20 / np.where(dt > 0, dt, 1), 0)                   # m/s
        if cls[V[st * k]] <= 1 and np.any(sp > 70): fast += 1
    print(f"{city:14s} {n:8d}   {inst:7d} ({100 * inst / n:4.1f}%)                {fast:7d} ({100 * fast / n:4.1f}%)")
