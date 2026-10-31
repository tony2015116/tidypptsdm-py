"""The Python results must equal those of the R package on the example data.

The reference tables in tests/fixtures were written by tidypptsdm (R) 1.1.0.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import tidypptsdm as tp
from tidypptsdm._monitor import _digits_for

FX = Path(__file__).parent / "fixtures"
TABLES = ["stations", "houses", "pigs", "pig_summary", "hours", "alerts"]
TEXT = {"location", "responder", "house", "status", "level", "type", "message"}


def read_ref(name):
    ref = pd.read_csv(FX / name, dtype={c: str for c in TEXT}, keep_default_na=True)
    if "date" in ref.columns:
        ref["date"] = pd.to_datetime(ref["date"])
    return ref


def assert_same(py: pd.DataFrame, ref: pd.DataFrame, name: str):
    assert list(py.columns) == list(ref.columns), name
    assert len(py) == len(ref), f"{name}: {len(py)} rows, R has {len(ref)}"
    py = py.reset_index(drop=True)
    for c in ref.columns:
        a, b = py[c], ref[c]
        if c in TEXT:
            a = a.map(lambda v: "" if v is None or v != v else str(v))
            b = b.map(lambda v: "" if v is None or v != v else str(v))
            bad = a != b
            assert not bad.any(), f"{name}.{c}: {a[bad].head(3).tolist()} vs R {b[bad].head(3).tolist()}"
        elif c == "date":
            assert (a.dt.normalize() == b).all(), f"{name}.{c}"
        else:
            a = pd.to_numeric(a, errors="coerce").to_numpy(float)
            b = pd.to_numeric(b, errors="coerce").to_numpy(float)
            # at most one unit of the last rounded decimal (sums of floats in a
            # different order can fall on either side of a rounding boundary)
            d = _digits_for(c)
            tol = 1.01 * 10.0 ** -(d if d is not None else 3) if d is not None or not np.allclose(a, np.round(a), equal_nan=True) else 0.0
            ok = np.isclose(a, b, atol=max(tol, 1e-9), rtol=0, equal_nan=True)
            assert ok.all(), f"{name}.{c}: rows {np.flatnonzero(~ok)[:5]}: {a[~ok][:5]} vs R {b[~ok][:5]}"


@pytest.fixture(scope="module", params=["nedap", "fire"])
def visits(request):
    return request.param, tp.prep_visits(tp.load_example(request.param), verbose=0)


def test_visits_equal_r(visits):
    st, v = visits
    ref = pd.read_csv(FX / f"{st}_visits.csv.gz", dtype={"responder": str, "location": str})
    assert len(v) == len(ref)
    assert (v["responder"].fillna("") == ref["responder"].fillna("")).all()
    assert (v["location"] == ref["location"]).all()
    assert (v["identified"] == ref["identified"]).all()
    assert (v["entry_time"].dt.strftime("%Y-%m-%d %H:%M:%S") == ref["entry_time"]).all()
    assert (v["exit_time"].dt.strftime("%Y-%m-%d %H:%M:%S") == ref["exit_time"]).all()
    for c in ("duration", "feed_intake", "weight"):
        assert np.allclose(v[c].to_numpy(float), ref[c].to_numpy(float), equal_nan=True, atol=1e-6), c


@pytest.mark.parametrize("tag", ["d7", "d21"])
def test_tables_equal_r(visits, tag):
    st, v = visits
    if tag == "d7":
        mon = tp.run_monitor(v, days=7, verbose=0)
    else:
        mon = tp.run_monitor(v, days=21, end_date=v["date"].max() - pd.Timedelta(days=10), verbose=0)
    for t in TABLES:
        assert_same(getattr(mon, t), read_ref(f"{st}_{tag}_{t}.csv"), f"{st}_{tag}_{t}")


def test_spoiled_alerts_equal_r():
    v = tp.prep_visits(tp.load_example("nedap"), verbose=0)
    end = v["date"].max()
    pig = (FX / "spoiled_pig.txt").read_text().strip()
    keep = ~((v["location"] == "102") & (v["date"] == end)) & \
        ~((v["responder"] == pig) & (v["date"] >= end - pd.Timedelta(days=1)))
    mon = tp.run_monitor(v[keep], days=7, verbose=0)
    assert_same(mon.alerts, read_ref("spoiled_alerts.csv"), "spoiled_alerts")
    assert_same(mon.stations, read_ref("spoiled_stations.csv"), "spoiled_stations")


def test_wide_tables_equal_r():
    mon = tp.run_monitor(tp.load_example("nedap"), days=7, verbose=0)
    for value, x, name in [("feed_kg", mon.stations, "nedap_d7_wide_feed.csv"),
                           ("feed_kg", mon.pigs, "nedap_d7_wide_pigfeed.csv")]:
        w = tp.wide_table(x, value)
        ref = pd.read_csv(FX / name, dtype={"location": str, "responder": str})
        assert list(w.columns) == list(ref.columns)
        assert_same(w, ref, name)
