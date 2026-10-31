"""Daily monitoring tables and alerts: a port of tidypptsdm (R)."""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ._messages import Abort, bullets, local_verbose, msg, plural
from ._prep import is_visits, prep_visits
from ._station import read_station

ACTIVE_DAYS = 14  # a station without visits stays in the tables for 14 days


# ---- helpers ---------------------------------------------------------------------

def natural_order(x) -> list[str]:
    """Stations and pigs in natural order: "2" before "10"."""
    vals = [v for v in pd.unique(pd.Series(list(x), dtype=object)) if v is not None and v == v]
    vals = [str(v) for v in vals]

    def key(v: str):
        digits = re.sub(r"[^0-9.]", "", v)
        try:
            num = float(digits)
            return (0, num, v)
        except ValueError:
            return (1, 0.0, v)

    return sorted(vals, key=key)


def _order_natural(df: pd.DataFrame, cols: list[str], then: list[str] | None = None) -> pd.DataFrame:
    keys = {}
    for c in cols:
        lv = {v: i for i, v in enumerate(natural_order(df[c]))}
        keys[f"__k_{c}"] = df[c].map(lv)
    tmp = df.assign(**keys)
    by = list(keys) + (then or [])
    return tmp.sort_values(by, kind="stable").drop(columns=list(keys)).reset_index(drop=True)


def r_round(x, digits: int):
    """Round like R: to the nearest decimal of the exact binary value; exact
    ties to even. (numpy rounds 0.15 to 0.2, R and this function to 0.1.)"""
    q = Decimal(1).scaleb(-digits)

    def one(v):
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return v
        return float(Decimal(float(v)).quantize(q, rounding=ROUND_HALF_EVEN))

    if isinstance(x, pd.Series):
        return x.map(one).astype(float)
    return one(x)


def _digits_for(col: str) -> int | None:
    if col in ("weight_kg", "last_weight_kg"):
        return 2
    if col.endswith("_kg"):
        return 3
    if col.startswith("pct_"):
        return 1
    if col.endswith("_h"):
        return 2
    if col.endswith("_min"):
        return 1
    return None


def _round_cols(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            d = _digits_for(c)
            if d is not None:
                df[c] = r_round(df[c], d)
    return df


def r_quantile(x: np.ndarray, probs) -> np.ndarray:
    """Quantiles exactly as R's quantile(type = 7), so that values on a
    Tukey fence are classed as in R (numpy interpolates differently)."""
    xs = np.sort(np.asarray(x, dtype=float))
    n = len(xs)
    out = []
    for p in probs:
        index = (n - 1) * p          # 0-based
        lo = int(np.floor(index))
        hi = int(np.ceil(index))
        qs = xs[lo]
        h = index - lo
        if index > lo and xs[hi] != qs:
            qs = (1 - h) * qs + h * xs[hi]
        out.append(qs)
    return np.array(out)


def iqr_outlier(x: np.ndarray, k: float) -> np.ndarray:
    """Tukey fences; fewer than 4 values are never outliers."""
    x = np.asarray(x, dtype=float)
    if len(x) < 4:
        return np.zeros(len(x), dtype=bool)
    q1, q3 = r_quantile(x, [0.25, 0.75])
    r = q3 - q1
    return (x < q1 - k * r) | (x > q3 + k * r)


def _check_whole(x, arg: str, minimum: int = 1) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, float, np.integer, np.floating)) \
            or not np.isfinite(x) or x < minimum or x != round(x):
        raise Abort(f"`{arg}` must be a whole number of at least {minimum}, not {x!r}.")
    return int(x)


def _check_number(x, arg: str, minimum: float = 0) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float, np.integer, np.floating)) \
            or not np.isfinite(x) or x < minimum:
        raise Abort(f"`{arg}` must be a number of at least {minimum:g}, not {x!r}.")
    return float(x)


def _as_day(x, arg: str) -> pd.Timestamp:
    try:
        d = pd.Timestamp(x)
    except (ValueError, TypeError):
        d = pd.NaT
    if d is pd.NaT or pd.isna(d):
        raise Abort(f"`{arg}` must be a date such as '2024-05-25', not {x!r}.")
    return d.normalize()


def _fmt_date(d) -> str:
    return pd.Timestamp(d).strftime("%Y-%m-%d")


# ---- input -------------------------------------------------------------------------

def as_visits(data, station: str | None = None, verbose: int = 1,
              time_zone: str = "local") -> pd.DataFrame:
    """Standard visit table from any input; always a copy."""
    if isinstance(data, (str, Path)) or (isinstance(data, (list, tuple)) and data
                                         and all(isinstance(d, (str, Path)) for d in data)):
        data = read_station(data, station=station, time_zone=time_zone, verbose=verbose)
    if not isinstance(data, pd.DataFrame):
        raise Abort("`data` must be station data: a folder or files of station exports, a raw "
                    "export as a DataFrame (e.g. load_example('nedap')), or the result of "
                    "read_station() or prep_visits().")
    if is_visits(data):
        v = data.copy()
        v.attrs = dict(data.attrs)
    else:
        v = prep_visits(data, station=station, time_zone=time_zone, verbose=verbose)
    v["date"] = pd.to_datetime(v["date"]).dt.normalize()
    v["location"] = v["location"].map(lambda s: None if s is None or s != s else str(s))
    v["responder"] = v["responder"].map(lambda s: None if s is None or s != s else str(s))
    v["identified"] = v["identified"].astype(bool)
    return v


def resolve_end_date(end_date, visits: pd.DataFrame) -> pd.Timestamp:
    """The last day: the last day in the data, or yesterday if that is today."""
    if end_date is None:
        if len(visits) == 0 or visits["date"].isna().all():
            raise Abort("`data` has no visits with a date.")
        last = visits["date"].max()
        today = pd.Timestamp(_dt.date.today())
        if last >= today:
            last = today - pd.Timedelta(days=1)
        return last.normalize()
    return _as_day(end_date, "end_date")


@dataclass
class Window:
    start: pd.Timestamp
    end: pd.Timestamp
    days: int

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.date_range(self.start, self.end, freq="D")


def monitor_window(visits: pd.DataFrame, days, end_date) -> Window:
    days = _check_whole(days, "days")
    end = resolve_end_date(end_date, visits)
    return Window(end - pd.Timedelta(days=days - 1), end, days)


def _window_visits(v: pd.DataFrame, win: Window) -> pd.DataFrame:
    return v[v["location"].notna() & v["date"].notna()
             & (v["date"] >= win.start) & (v["date"] <= win.end)]


def _active_locations(v: pd.DataFrame, start, end) -> list[str]:
    sel = v["location"].notna() & v["date"].notna() \
        & (v["date"] >= start - pd.Timedelta(days=ACTIVE_DAYS)) & (v["date"] <= end)
    return natural_order(v.loc[sel, "location"])


def _grid(**cols) -> pd.DataFrame:
    idx = pd.MultiIndex.from_product(list(cols.values()), names=list(cols))
    return idx.to_frame(index=False)


def _nunique_ident(g: pd.DataFrame) -> int:
    return g.loc[g["identified"], "responder"].nunique()


# ---- stations -------------------------------------------------------------------------

STATION_COLS = ["location", "date", "n_pigs", "n_visits", "n_unidentified",
                "pct_unidentified", "occupation_h", "feed_kg", "feed_per_pig_kg",
                "weight_kg", "pct_weight_outlier"]


def _station_table(v: pd.DataFrame, win: Window, iqr_k: float) -> pd.DataFrame:
    locs = _active_locations(v, win.start, win.end)
    w = _window_visits(v, win)
    grid = _grid(location=locs, date=win.dates)
    if len(w):
        g = w.assign(feed_id=w["feed_intake"].where(w["identified"], 0.0),
                     resp_id=w["responder"].where(w["identified"]),
                     unid=~w["identified"]).groupby(["location", "date"])
        agg = pd.DataFrame({
            "n_pigs": g["resp_id"].nunique(),
            "n_visits": g.size(),
            "n_unidentified": g["unid"].sum(),
            "occupation_h": g["duration"].sum(min_count=0) / 3600,
            "feed_kg": g["feed_intake"].sum(min_count=0) / 1000,
            "feed_identified_kg": g["feed_id"].sum(min_count=0) / 1000,
        }).reset_index()
        res = grid.merge(agg, on=["location", "date"], how="left")
    else:
        res = grid.assign(n_pigs=np.nan, n_visits=np.nan, n_unidentified=np.nan,
                          occupation_h=np.nan, feed_kg=np.nan, feed_identified_kg=np.nan)
    none = res["n_visits"].isna()
    res.loc[none, ["n_pigs", "n_visits", "n_unidentified"]] = 0
    res.loc[none, ["occupation_h", "feed_kg", "feed_identified_kg"]] = 0.0
    for c in ("n_pigs", "n_visits", "n_unidentified"):
        res[c] = res[c].astype(int)
    res["pct_unidentified"] = np.where(res["n_visits"] > 0,
                                       100 * res["n_unidentified"] / res["n_visits"].clip(lower=1), np.nan)
    res["feed_per_pig_kg"] = np.where(res["n_pigs"] > 0,
                                      res["feed_identified_kg"] / res["n_pigs"].clip(lower=1), np.nan)
    wv = w[w["identified"] & w["weight"].notna()].copy()
    res["weight_kg"] = np.nan
    res["pct_weight_outlier"] = np.nan
    if len(wv):
        wv["outlier"] = wv.groupby(["location", "date", "responder"])["weight"] \
            .transform(lambda s: iqr_outlier(s.to_numpy(), iqr_k)).astype(bool)
        out_pct = (wv.groupby(["location", "date"])["outlier"].mean() * 100).rename("pct_weight_outlier")
        wt = (wv[~wv["outlier"]].groupby(["location", "date", "responder"])["weight"].median()
              .groupby(["location", "date"]).mean().rename("weight_kg"))
        key = pd.MultiIndex.from_frame(res[["location", "date"]])
        res["weight_kg"] = wt.reindex(key).to_numpy()
        res["pct_weight_outlier"] = out_pct.reindex(key).to_numpy()
    res = res[STATION_COLS]
    res = _order_natural(res, ["location"], ["date"])
    res = _round_cols(res)
    res.attrs["pptm_table"] = "stations"
    return res


# ---- houses ----------------------------------------------------------------------------

HOUSE_COLS = ["house", "date", "n_stations", "n_pigs", "n_visits", "feed_kg",
              "feed_per_pig_kg", "weight_kg"]


def _house_table(v: pd.DataFrame, win: Window, house_width: int) -> pd.DataFrame:
    locs = _active_locations(v, win.start, win.end)
    st = pd.DataFrame({"location": locs})
    st["house"] = st["location"].str[:house_width]
    n_st = st.groupby("house").size()
    w = _window_visits(v, win)
    w = w[w["location"].isin(locs)].copy()
    w["house"] = w["location"].str[:house_width]
    grid = _grid(house=natural_order(st["house"]), date=win.dates)
    if len(w):
        g = w.assign(feed_id=w["feed_intake"].where(w["identified"], 0.0),
                     resp_id=w["responder"].where(w["identified"])).groupby(["house", "date"])
        agg = pd.DataFrame({
            "n_pigs": g["resp_id"].nunique(),
            "n_visits": g.size(),
            "feed_kg": g["feed_intake"].sum(min_count=0) / 1000,
            "feed_identified_kg": g["feed_id"].sum(min_count=0) / 1000,
        }).reset_index()
        res = grid.merge(agg, on=["house", "date"], how="left")
    else:
        res = grid.assign(n_pigs=np.nan, n_visits=np.nan, feed_kg=np.nan, feed_identified_kg=np.nan)
    none = res["n_visits"].isna()
    res.loc[none, ["n_pigs", "n_visits"]] = 0
    res.loc[none, ["feed_kg", "feed_identified_kg"]] = 0.0
    res["n_pigs"] = res["n_pigs"].astype(int)
    res["n_visits"] = res["n_visits"].astype(int)
    res["feed_per_pig_kg"] = np.where(res["n_pigs"] > 0,
                                      res["feed_identified_kg"] / res["n_pigs"].clip(lower=1), np.nan)
    wv = w[w["identified"] & w["weight"].notna()]
    res["weight_kg"] = np.nan
    if len(wv):
        wt = (wv.groupby(["house", "date", "responder"])["weight"].median()
              .groupby(["house", "date"]).mean())
        res["weight_kg"] = wt.reindex(pd.MultiIndex.from_frame(res[["house", "date"]])).to_numpy()
    res["n_stations"] = res["house"].map(n_st).astype(int)
    res = res[HOUSE_COLS]
    res = _order_natural(res, ["house"], ["date"])
    res = _round_cols(res)
    res.attrs["pptm_table"] = "houses"
    return res


# ---- pigs --------------------------------------------------------------------------------

PIG_COLS = ["location", "responder", "date", "n_visits", "feed_kg", "occupation_min",
            "weight_kg", "status"]


def _pig_table(v: pd.DataFrame, win: Window, low_feed_kg: float) -> pd.DataFrame:
    w = _window_visits(v, win)
    w = w[w["identified"]]
    if len(w) == 0:
        res = pd.DataFrame({c: pd.Series(dtype=t) for c, t in zip(
            PIG_COLS, [object, object, "datetime64[ns]", int, float, float, float, object])})
        res.attrs["pptm_table"] = "pigs"
        return res
    # main station: most visits in the window (ties: first seen)
    cnt = w.groupby(["responder", "location"], sort=False).size().rename("N").reset_index()
    cnt = cnt.sort_values("N", ascending=False, kind="stable")
    main = cnt.drop_duplicates("responder")[["responder", "location"]]
    first = v[v["identified"] & v["date"].notna()].groupby("responder")["date"].min()
    pigs = main.assign(start=main["responder"].map(first).clip(lower=win.start))
    rows = [pd.DataFrame({"responder": r, "location": l, "date": pd.date_range(s, win.end, freq="D")})
            for r, l, s in zip(pigs["responder"], pigs["location"], pigs["start"])]
    grid = pd.concat(rows, ignore_index=True)
    g = w.groupby(["responder", "date"])
    pd_ = pd.DataFrame({
        "n_visits": g.size(),
        "feed_kg": g["feed_intake"].sum(min_count=0) / 1000,
        "occupation_min": g["duration"].sum(min_count=0) / 60,
        "weight_kg": g["weight"].median(),
    }).reset_index()
    res = grid.merge(pd_, on=["responder", "date"], how="left")
    none = res["n_visits"].isna()
    res.loc[none, "n_visits"] = 0
    res.loc[none, ["feed_kg", "occupation_min"]] = 0.0
    res["n_visits"] = res["n_visits"].astype(int)
    res["status"] = np.where(res["n_visits"] == 0, "no_visit",
                             np.where(res["feed_kg"] < low_feed_kg, "low_feed", "ok"))
    res = res[PIG_COLS]
    res = _order_natural(res, ["location", "responder"], ["date"])
    res = _round_cols(res)
    res.attrs["pptm_table"] = "pigs"
    return res


SUMMARY_COLS = ["location", "responder", "days", "no_visit_days", "low_feed_days",
                "mean_feed_kg", "last_feed_kg", "last_visits", "last_weight_kg",
                "days_since_visit", "status"]


def _pig_summary(pigs: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    if len(pigs) == 0:
        return pd.DataFrame({c: pd.Series(dtype=object) for c in SUMMARY_COLS})
    rows = []
    for (loc, resp), g in pigs.groupby(["location", "responder"], sort=False):
        last = g[g["date"] == end]
        seen = g.loc[g["n_visits"] > 0, "date"]
        wts = g["weight_kg"].dropna()
        rows.append({
            "location": loc, "responder": resp, "days": len(g),
            "no_visit_days": int((g["status"] == "no_visit").sum()),
            "low_feed_days": int((g["status"] == "low_feed").sum()),
            "mean_feed_kg": g["feed_kg"].mean(),
            "last_feed_kg": last["feed_kg"].iloc[0] if len(last) else np.nan,
            "last_visits": last["n_visits"].iloc[0] if len(last) else np.nan,
            "last_weight_kg": wts.iloc[-1] if len(wts) else np.nan,
            "days_since_visit": (end - seen.max()).days if len(seen) else np.nan,
            "status": last["status"].iloc[0] if len(last) else None,
        })
    res = pd.DataFrame(rows, columns=SUMMARY_COLS)
    for c in ("last_visits", "days_since_visit"):
        res[c] = res[c].astype("Int64")
    return _round_cols(res)


# ---- hours ----------------------------------------------------------------------------------

HOUR_COLS = ["location", "date", "hour", "n_pigs", "n_visits", "occupation_min", "feed_kg"]


def _hour_table(v: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    locs = _active_locations(v, day, day)
    w = v[v["location"].notna() & v["date"].notna() & (v["date"] == day)].copy()
    grid = _grid(location=locs, hour=list(range(24)))
    if len(w):
        w["hour"] = w["entry_time"].dt.hour
        g = w.assign(resp_id=w["responder"].where(w["identified"])).groupby(["location", "hour"])
        agg = pd.DataFrame({
            "n_pigs": g["resp_id"].nunique(),
            "n_visits": g.size(),
            "occupation_min": g["duration"].sum(min_count=0) / 60,
            "feed_kg": g["feed_intake"].sum(min_count=0) / 1000,
        }).reset_index()
        res = grid.merge(agg, on=["location", "hour"], how="left")
    else:
        res = grid.assign(n_pigs=np.nan, n_visits=np.nan, occupation_min=np.nan, feed_kg=np.nan)
    none = res["n_visits"].isna()
    res.loc[none, ["n_pigs", "n_visits"]] = 0
    res.loc[none, ["occupation_min", "feed_kg"]] = 0.0
    res["n_pigs"] = res["n_pigs"].astype(int)
    res["n_visits"] = res["n_visits"].astype(int)
    res["date"] = day
    res = res[HOUR_COLS]
    res = _order_natural(res, ["location"], ["hour"])
    res = _round_cols(res)
    res.attrs["pptm_table"] = "hours"
    return res


# ---- alerts -------------------------------------------------------------------------------------

ALERT_COLS = ["level", "type", "location", "responder", "value", "message"]
ALERT_TYPES = ["station_down", "unidentified", "feed_drop", "pig_no_visit", "pig_low_feed"]


def _pigs_note(n) -> str:
    if n is None or (isinstance(n, float) and np.isnan(n)) or n == 0:
        return ""
    n = int(n)
    return f" ({n} pig{'' if n == 1 else 's'})"


def _find_alerts(stations: pd.DataFrame, pig_sum: pd.DataFrame, end: pd.Timestamp,
                 low_feed_kg: float, max_unidentified_pct: float,
                 max_feed_drop_pct: float) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    last = stations[stations["date"] == end]
    pigs_at = pig_sum.groupby("location").size() if len(pig_sum) else pd.Series(dtype=int)
    down = last[last["n_visits"] == 0]
    for _, r in down.iterrows():
        rows.append(dict(level="danger", type="station_down", location=r["location"], responder=None,
                         value=0.0, message=f"No visits on {_fmt_date(end)}"
                         + _pigs_note(pigs_at.get(r["location"], 0))))
    un = last[(last["n_visits"] > 0) & (last["pct_unidentified"] > max_unidentified_pct)]
    for _, r in un.iterrows():
        rows.append(dict(level="warning", type="unidentified", location=r["location"], responder=None,
                         value=float(r["pct_unidentified"]),
                         message=f"{r['pct_unidentified']:.1f}% of the visits unidentified "
                                 f"({int(r['n_unidentified'])} of {int(r['n_visits'])})"))
    prev = stations[(stations["date"] < end) & (stations["n_visits"] > 0)] \
        .groupby("location")["feed_kg"].mean()
    for _, r in last.iterrows():
        m = prev.get(r["location"])
        if m is None or not r["n_visits"] > 0 or not m > 0:
            continue
        if r["feed_kg"] < (1 - max_feed_drop_pct / 100) * m:
            rows.append(dict(level="warning", type="feed_drop", location=r["location"], responder=None,
                             value=float(r["feed_kg"]),
                             message=f"Feed intake {r['feed_kg']:.1f} kg, "
                                     f"{100 * (1 - r['feed_kg'] / m):.0f}% below the mean of the "
                                     f"earlier days ({m:.1f} kg)"))
    ps = pig_sum[~pig_sum["location"].isin(set(down["location"]))] if len(pig_sum) else pig_sum
    for _, r in ps.iterrows():
        if r["status"] == "no_visit":
            d = int(r["days_since_visit"])
            wt = r["last_weight_kg"]
            rows.append(dict(level="danger", type="pig_no_visit", location=r["location"],
                             responder=r["responder"], value=float(d),
                             message=f"No visit for {d} day{'' if d == 1 else 's'}"
                             + ("" if pd.isna(wt) else f" (last weight {wt:.1f} kg)")))
        elif r["status"] == "low_feed":
            n = int(r["low_feed_days"])
            rows.append(dict(level="warning", type="pig_low_feed", location=r["location"],
                             responder=r["responder"], value=float(r["last_feed_kg"]),
                             message=f"Ate {r['last_feed_kg']:.2f} kg (below {low_feed_kg:g} kg); "
                                     f"{n} low-feed day{'' if n == 1 else 's'} in the window"))
    out = pd.DataFrame(rows, columns=ALERT_COLS)
    if len(out) == 0:
        out["value"] = out["value"].astype(float)
        return out
    loc_lv = {v: i for i, v in enumerate(natural_order(out["location"]))}
    resp_lv = {v: i for i, v in enumerate(natural_order(out["responder"]))}
    out = out.assign(
        _l=out["level"].map({"danger": 0, "warning": 1}),
        _p=out["responder"].notna().astype(int),
        _s=out["location"].map(loc_lv),
        _t=out["type"].map({t: i for i, t in enumerate(ALERT_TYPES)}),
        _r=out["responder"].map(resp_lv).fillna(1e9),
    ).sort_values(["_l", "_p", "_s", "_t", "_r"], kind="stable")
    return out[ALERT_COLS].reset_index(drop=True)


# ---- the monitor --------------------------------------------------------------------------------

@dataclass
class Monitor:
    """Result of [run_monitor()][tidypptsdm.run_monitor].

    Attributes:
        stations: One row per station and day ([monitor_stations()][tidypptsdm.monitor_stations]).
        houses: One row per house and day.
        pigs: One row per pig and day.
        pig_summary: One row per pig over the window.
        hours: One row per station and hour of the last day.
        alerts: The alerts of the last day.
        visits: The visits of the window.
        settings: The arguments, the window and the station type.
    """

    stations: pd.DataFrame
    houses: pd.DataFrame
    pigs: pd.DataFrame
    pig_summary: pd.DataFrame
    hours: pd.DataFrame
    alerts: pd.DataFrame
    visits: pd.DataFrame
    settings: dict = field(default_factory=dict)

    def summary_lines(self) -> list[tuple[str, str]]:
        s = self.settings
        last = self.stations[self.stations["date"] == s["end_date"]]
        vis = int(last["n_visits"].sum())
        feed = float(last["feed_kg"].sum())
        lines = [("info", f"{plural(len(last), 'station')}, {plural(len(self.pig_summary), 'pig')}; "
                          f"on {_fmt_date(s['end_date'])}: {plural(vis, 'visit')}, {feed:.1f} kg feed")]
        a = self.alerts
        if len(a) == 0:
            lines.append(("success", "No alerts"))
        else:
            n_d = int((a["level"] == "danger").sum())
            lines.append(("warning", f"{plural(len(a), 'alert')}: {n_d} danger, {len(a) - n_d} warning"))
            for _, r in a.head(10).iterrows():
                lab = (f"Station {r['location']}" if r["responder"] is None or r["responder"] != r["responder"]
                       else f"Pig {r['responder']} (station {r['location']})")
                lines.append(("bullet-" + r["level"], f"{lab}: {r['message']}"))
            if len(a) > 10:
                lines.append(("info", f"... and {len(a) - 10} more in .alerts"))
        return lines

    def print_summary(self) -> None:
        for kind, text in self.summary_lines():
            if kind.startswith("bullet-"):
                bullets([(kind[7:], text)])
            else:
                msg(text, kind)

    def __repr__(self) -> str:
        s = self.settings
        out = [f"<Monitor {str(s['station']).upper()}: {_fmt_date(s['start_date'])} to "
               f"{_fmt_date(s['end_date'])} ({s['days']} days)>"]
        sym = {"info": "i", "success": "v", "warning": "!", "bullet-danger": "  x", "bullet-warning": "  !"}
        for kind, text in self.summary_lines():
            out.append(f"{sym.get(kind, 'i')} {text}")
        out.append("Tables: .stations, .houses, .pigs, .pig_summary, .hours, .alerts")
        return "\n".join(out)


def run_monitor(data, days: int = 7, end_date=None, house_width: int = 1,
                low_feed_kg: float = 0.5, max_unidentified_pct: float = 5,
                max_feed_drop_pct: float = 30, iqr_k: float = 1.5,
                station: str | None = None, time_zone: str = "local",
                verbose: int = 1) -> Monitor:
    """Monitor the stations over the last days.

    Prepare the visits once, compute the daily tables of the monitoring
    window (stations, houses, pigs, hours of the last day) and list the
    alerts of the last day.

    Args:
        data: Station data: a folder or files of NEDAP or FIRE exports, a raw
            export as a DataFrame (e.g. ``load_example("nedap")``), or the
            result of [read_station()][tidypptsdm.read_station] or
            [prep_visits()][tidypptsdm.prep_visits].
        days: Number of days in the window, ending on ``end_date``. Default 7.
        end_date: Last day of the window (``"YYYY-MM-DD"`` or a date).
            Default ``None``: the last day in the data, or yesterday when the
            last day is today (an export taken during the day is incomplete).
        house_width: Number of leading characters of the station ID that
            name its house, e.g. 1 for station ``"203"`` in house ``"2"``.
        low_feed_kg: A pig that ate less than this on a day (kg) is
            ``"low_feed"``. Default 0.5.
        max_unidentified_pct: Alert when more than this percentage of the
            visits of a station are unidentified on the last day. Default 5.
        max_feed_drop_pct: Alert when the feed intake of a station on the last
            day is more than this percentage below its mean of the earlier
            days of the window. Default 30.
        iqr_k: Body weights of a pig on a day outside the Tukey fences
            (quartiles -/+ ``iqr_k`` times the interquartile range) are
            outliers. Default 1.5.
        station: ``"nedap"``, ``"fire"`` or ``None`` (detect).
        time_zone: Times written with a time zone (e.g.
            ``2025-01-24T00:34:17Z``) are converted to this time zone before
            the days are counted. ``"local"`` (default): the time zone of this
            computer; or a name such as ``"Asia/Shanghai"``.
        verbose: 0 (silent), 1 (summary) or 2 (details).

    Returns:
        A [Monitor][tidypptsdm.Monitor] with the tables ``stations``,
        ``houses``, ``pigs``, ``pig_summary``, ``hours``, ``alerts``,
        ``visits`` and ``settings``.

    Alerts of the last day:

    | type | level | when |
    |---|---|---|
    | `station_down` | danger | no visit at all on the station |
    | `unidentified` | warning | more than `max_unidentified_pct` % of the visits unidentified |
    | `feed_drop` | warning | feed intake more than `max_feed_drop_pct` % below the station mean of the earlier days |
    | `pig_no_visit` | danger | a pig seen in the window did not visit its station |
    | `pig_low_feed` | warning | a pig ate less than `low_feed_kg` |

    Pigs of a station without any visit get no pig alert: the
    ``station_down`` alert covers them.
    """
    with local_verbose(verbose):
        house_width = _check_whole(house_width, "house_width")
        low_feed_kg = _check_number(low_feed_kg, "low_feed_kg")
        max_unidentified_pct = _check_number(max_unidentified_pct, "max_unidentified_pct")
        max_feed_drop_pct = _check_number(max_feed_drop_pct, "max_feed_drop_pct")
        iqr_k = _check_number(iqr_k, "iqr_k")
        v = as_visits(data, station, verbose, time_zone)
        win = monitor_window(v, days, end_date)
        st_type = v.attrs.get("station") or ""
        msg(f"Monitoring {st_type.upper()} stations: {_fmt_date(win.start)} to "
            f"{_fmt_date(win.end)} ({plural(win.days, 'day')})", "h1")
        w = _window_visits(v, win)
        if len(w) == 0:
            msg(f"No visits between {_fmt_date(win.start)} and {_fmt_date(win.end)}.", "warning")
        stations = _station_table(v, win, iqr_k)
        houses = _house_table(v, win, house_width)
        pigs = _pig_table(v, win, low_feed_kg)
        pig_sum = _pig_summary(pigs, win.end)
        hours = _hour_table(v, win.end)
        alerts = _find_alerts(stations, pig_sum, win.end, low_feed_kg,
                              max_unidentified_pct, max_feed_drop_pct)
        mon = Monitor(stations, houses, pigs, pig_sum, hours, alerts, w.reset_index(drop=True), dict(
            station=st_type, days=win.days, start_date=win.start, end_date=win.end,
            house_width=house_width, low_feed_kg=low_feed_kg,
            max_unidentified_pct=max_unidentified_pct, max_feed_drop_pct=max_feed_drop_pct,
            iqr_k=iqr_k, created=pd.Timestamp.now()))
        mon.print_summary()
        return mon


def monitor_stations(data, days: int = 7, end_date=None, iqr_k: float = 1.5,
                     station: str | None = None, verbose: int = 1) -> pd.DataFrame:
    """Daily table per station.

    One row per station (``location``) and ``date`` of the window, also for
    days without visits: ``n_pigs`` (pigs with an identified visit),
    ``n_visits``, ``n_unidentified``, ``pct_unidentified``, ``occupation_h``
    (hours the station was occupied), ``feed_kg`` (all visits),
    ``feed_per_pig_kg`` (identified feed / ``n_pigs``), ``weight_kg`` (mean
    over the pigs of their daily median weight, outliers excluded) and
    ``pct_weight_outlier`` (recorded weights outside the Tukey fences of the
    pig and day, see ``iqr_k``). Arguments as in
    [run_monitor()][tidypptsdm.run_monitor].
    """
    with local_verbose(verbose):
        iqr_k = _check_number(iqr_k, "iqr_k")
        v = as_visits(data, station, verbose)
        return _station_table(v, monitor_window(v, days, end_date), iqr_k)


def monitor_houses(data, days: int = 7, end_date=None, house_width: int = 1,
                   station: str | None = None, verbose: int = 1) -> pd.DataFrame:
    """Daily table per house.

    Stations are grouped by the first ``house_width`` characters of their
    ID. One row per ``house`` and ``date``: ``n_stations``, ``n_pigs``,
    ``n_visits``, ``feed_kg``, ``feed_per_pig_kg`` and ``weight_kg``.
    """
    with local_verbose(verbose):
        house_width = _check_whole(house_width, "house_width")
        v = as_visits(data, station, verbose)
        return _house_table(v, monitor_window(v, days, end_date), house_width)


def monitor_pigs(data, days: int = 7, end_date=None, low_feed_kg: float = 0.5,
                 station: str | None = None, verbose: int = 1) -> pd.DataFrame:
    """Daily table per pig.

    One row per pig and day, from the first day the pig was seen (or the
    start of the window) to the last day. A day without visit is kept with
    ``status = "no_visit"``. Columns: ``location`` (station with most visits
    in the window), ``responder``, ``date``, ``n_visits``, ``feed_kg``,
    ``occupation_min``, ``weight_kg`` (median of the day) and ``status``
    (``"no_visit"``, ``"low_feed"`` or ``"ok"``).
    """
    with local_verbose(verbose):
        low_feed_kg = _check_number(low_feed_kg, "low_feed_kg")
        v = as_visits(data, station, verbose)
        return _pig_table(v, monitor_window(v, days, end_date), low_feed_kg)


def monitor_hours(data, date=None, station: str | None = None, verbose: int = 1) -> pd.DataFrame:
    """Hourly table per station for one day (default: the last full day).

    One row per station and ``hour`` (0-23, from the entrance time):
    ``date``, ``n_pigs``, ``n_visits``, ``occupation_min`` and ``feed_kg``.
    """
    with local_verbose(verbose):
        v = as_visits(data, station, verbose)
        return _hour_table(v, resolve_end_date(date, v))


# ---- wide tables -----------------------------------------------------------------------------------

ADDITIVE = {"n_visits", "n_unidentified", "occupation_h", "occupation_min", "feed_kg"}


def wide_table(x: pd.DataFrame, value: str) -> pd.DataFrame:
    """One column of a daily table as a wide table.

    Stations, houses or pigs in rows, days (``"MM-DD"``) or hours (``"00"``
    to ``"23"``) in columns, plus ``total`` for counts, kg and time and
    ``mean`` otherwise.

    Args:
        x: A table from ``monitor_stations()``, ``monitor_houses()``,
            ``monitor_pigs()`` or ``monitor_hours()`` (or of a Monitor).
        value: The column to show, e.g. ``"feed_kg"``.
    """
    kind = x.attrs.get("pptm_table") if isinstance(x, pd.DataFrame) else None
    if kind is None:
        raise Abort("`x` must be a table from monitor_stations(), monitor_houses(), "
                    "monitor_pigs() or monitor_hours().")
    ids = {"stations": ["location"], "houses": ["house"], "pigs": ["location", "responder"],
           "hours": ["location"]}[kind]
    col = "hour" if kind == "hours" else "date"
    options = [c for c in x.columns if c not in ids + [col] and pd.api.types.is_numeric_dtype(x[c])]
    if value not in options:
        raise Abort(f"`value` must be one of {options}.")
    d = x[ids + [col, value]].copy()
    if col == "date":
        lab = d[col].dt.strftime("%m-%d")
        if lab.nunique() < d[col].nunique():
            lab = d[col].dt.strftime("%Y-%m-%d")
        levels = list(pd.unique(lab[d[col].sort_values(kind="stable").index]))
    else:
        lab = d[col].map(lambda h: f"{int(h):02d}")
        levels = [f"{h:02d}" for h in range(24)]
    d["__col"] = lab
    res = d.pivot_table(index=ids, columns="__col", values=value, aggfunc="first", dropna=False,
                        observed=True)
    res = res.reindex(columns=levels)
    res.columns.name = None
    res = res.reset_index()
    rows_present = d[ids].drop_duplicates()
    res = rows_present.merge(res, on=ids, how="left")
    if len(levels):
        m = res[levels].astype(float)
        if value in ADDITIVE:
            res["total"] = m.sum(axis=1, min_count=0)
        else:
            res["mean"] = m.mean(axis=1)
    res = _order_natural(res, ids)
    digits = _digits_for(value) or 3
    for c in res.columns:
        if c not in ids and pd.api.types.is_float_dtype(res[c]):
            res[c] = r_round(res[c], digits)
    return res
