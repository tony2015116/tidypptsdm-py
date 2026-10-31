"""Test data for the exe build: the NEDAP example copied to more stations.

    python packaging/many_stations.py <folder> <stations>
"""
import sys
from pathlib import Path

import pandas as pd

import tidypptsdm as tp

out, n = Path(sys.argv[1]), int(sys.argv[2])
raw = tp.load_example("nedap")
parts = []
for k in range(n // 2):
    d = raw.copy()
    d["location"] = (pd.to_numeric(d["location"]) + 100 * k).astype(int).astype(str)
    r = pd.to_numeric(d["responder"], errors="coerce")
    ok = r.notna() & (r != 0)
    d.loc[ok, "responder"] = (r[ok].astype("int64") + k * 10**7).astype(str)
    parts.append(d)
out.mkdir(parents=True, exist_ok=True)
pd.concat(parts).to_csv(out / "nedap_many.csv", index=False)
print(f"{n} stations written to {out}")
