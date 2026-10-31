"""Standard visit table: a port of ``prep_visits()`` of tidypptsda."""

from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from ._messages import Abort, local_verbose, msg, plural
from ._station import (STATION_REQUIRED, apply_format, as_station_format,
                       builtin_format, check_station, detect_station)

VISIT_COLS = ["responder", "identified", "location", "date", "entry_time",
              "duration", "feed_intake", "weight"]

DURATION_MAX = 3600      # s; longest plausible visit (midnight crossings)
MISREAD_MAX_VISITS = 2   # runs of at most this many visits at another station


def is_visits(data) -> bool:
    """True for the result of prep_visits()."""
    return isinstance(data, pd.DataFrame) and set(VISIT_COLS) <= set(data.columns)


def prep_visits(data: pd.DataFrame, station: str | None = None, format=None,
                duration_max: float = DURATION_MAX,
                misread_max_visits: int = MISREAD_MAX_VISITS,
                verbose: int = 1) -> pd.DataFrame:
    """Prepare a standard visit table from NEDAP or FIRE data.

    Args:
        data: The result of [read_station()][tidypptsdm.read_station], or a
            raw export already in Python (e.g.
            [load_example("nedap")][tidypptsdm.load_example]).
        station: ``"nedap"``, ``"fire"`` or ``None``: taken from
            ``data.attrs["station"]`` or detected from the column names.
        format: Station format for raw data whose columns differ from the
            usual export (see [station_format()][tidypptsdm.station_format]).
        duration_max: Longest plausible visit, s. A FIRE visit whose exit
            clock time is before its entry is a midnight crossing when the
            corrected duration is not longer than this. Default 3600.
        misread_max_visits: A pig's run of at most this many consecutive
            visits at another station, inside its visits at its own station,
            is a transponder misread: these visits become unidentified.
            Default 2.
        verbose: 0 (silent), 1 (summary) or 2 (details).

    Returns:
        A DataFrame, one row per visit, ordered by ``location`` and
        ``entry_time``: ``responder`` (``None`` for unidentified visits),
        ``responder_raw``, ``identified``, ``location``, ``date``,
        ``seq_days``, ``seq_in_day``, ``seq_in_location``, ``entry_time``,
        ``exit_time``, ``duration`` (s), ``feed_intake`` (g), ``weight`` (kg,
        ``NaN`` when not recorded), ``trough_in``, ``trough_out``, ``topup``
        (g, FIRE only) and ``source_file`` when present.
        ``attrs["station"]`` holds the station type and ``attrs["stations"]``
        one row per pig with its station history.

    Body weights of 0 or below mean no weight was recorded. Rows without an
    entry time and exact duplicates are dropped.
    """
    with local_verbose(verbose):
        if not isinstance(data, pd.DataFrame):
            raise Abort("`data` must be a DataFrame.")
        standard = bool(data.attrs.get("ppt_standard"))
        if station is None:
            station = data.attrs.get("station")
        if standard:
            if station is None:
                raise Abort("`data` has no station type; set `station`.")
            station = check_station(station)
            missing = [c for c in STATION_REQUIRED[station] if c not in data.columns]
            if missing:
                raise Abort(f"`data` is missing column(s) {missing}. Read the files with read_station().")
            dt = data.copy()
        else:
            if format is not None:
                if station is None:
                    raise Abort("Set `station` when `format` is given.")
                station = check_station(station)
                fmt = as_station_format(format, station)
            else:
                station = detect_station(data) if station is None else check_station(station)
                fmt = builtin_format(station)
            src = data["source_file"].to_numpy() if "source_file" in data.columns else None
            dt = apply_format(data, fmt, station)
            if src is not None:
                dt["source_file"] = src

        msg(f"Preparing {station.upper()} visits", "h1")
        n_raw = len(dt)
        dt, n_cross = _finish_standard(dt, duration_max)

        n_zero = int((dt["weight"].notna() & (dt["weight"] <= 0)).sum())
        dt.loc[dt["weight"] <= 0, "weight"] = np.nan

        n_no_time = int(dt["entry_time"].isna().sum())
        dt = dt[dt["entry_time"].notna()]

        n_before = len(dt)
        dt = dt.drop_duplicates().reset_index(drop=True)
        n_dup = n_before - len(dt)

        n_unid = int((~dt["identified"]).sum())
        if n_raw:
            msg(f"Visits read: {n_raw:,}; unidentified (kept): {n_unid:,} ({100 * n_unid / n_raw:.1f}%)"
                + (f"; body weight 0 set to NA: {n_zero:,}" if n_zero else "")
                + (f"; crossing midnight: {n_cross:,}" if station == "fire" or n_cross else ""), "info")
        if n_no_time:
            msg(f"{n_no_time:,} rows without entry time dropped", "warning")
        if n_dup:
            msg(f"{n_dup:,} duplicated rows dropped", "warning")

        dt, stations = _resolve_transfers(dt, misread_max_visits)

        dt = dt.sort_values(["location", "entry_time"], kind="stable").reset_index(drop=True)
        dt["date"] = dt["entry_time"].dt.normalize()
        if len(dt):
            dt["seq_days"] = ((dt["date"] - dt["date"].min()).dt.days + 1).astype(int)
        else:
            dt["seq_days"] = pd.Series(dtype=int)
        dt["seq_in_location"] = dt.groupby(["location", "date"], sort=False).cumcount() + 1
        ident = dt["identified"]
        seq = pd.Series(np.nan, index=dt.index)
        seq[ident] = dt[ident].groupby(["responder", "date"], sort=False).cumcount() + 1
        dt["seq_in_day"] = seq.astype("Int64")

        cols = ["responder", "responder_raw", "identified", "breed", "location",
                "date", "seq_days", "seq_in_day", "seq_in_location", "entry_time",
                "exit_time", "duration", "feed_intake", "weight", "trough_in",
                "trough_out", "topup", "source_file"]
        dt = dt[[c for c in cols if c in dt.columns]]
        dt.attrs["station"] = station
        dt.attrs["stations"] = stations
        n_pigs = dt.loc[dt["identified"], "responder"].nunique()
        n_days = int(dt["seq_days"].max()) if len(dt) else 0
        msg(f"{plural(n_pigs, 'pig')} at {plural(dt['location'].nunique(), 'station')}, "
            f"{len(dt):,} visits over {plural(n_days, 'day')}", "success")
        return dt


def _finish_standard(dt: pd.DataFrame, duration_max: float) -> tuple[pd.DataFrame, int]:
    out = dt.rename(columns={"responder": "responder_raw"}).copy()
    out["responder_raw"] = out["responder_raw"].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v))
    out["location"] = out["location"].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v))
    entry = out["entry_time"]
    exit_ = out["exit_time"].copy()
    dur = pd.to_numeric(out["duration"], errors="coerce").astype(float)
    need = dur.isna() & exit_.notna() & entry.notna()
    one_day = pd.Timedelta(days=1)
    crossing = need & (exit_ < entry) & (((exit_ + one_day) - entry).dt.total_seconds() <= duration_max)
    exit_[crossing] = exit_[crossing] + one_day
    dur[need] = (exit_[need] - entry[need]).dt.total_seconds()
    out["exit_time"] = exit_
    out["duration"] = dur
    fill = out["exit_time"].isna() & out["entry_time"].notna() & out["duration"].notna()
    out.loc[fill, "exit_time"] = out.loc[fill, "entry_time"] + pd.to_timedelta(out.loc[fill, "duration"], unit="s")
    raw = out["responder_raw"].map(lambda v: v.strip() if isinstance(v, str) else None)
    num = pd.to_numeric(raw, errors="coerce")
    unidentified = raw.isna() | (raw == "") | (num == 0)
    out["identified"] = ~unidentified
    out["responder"] = raw.where(out["identified"], None)
    return out, int(crossing.sum())


def misread_runs(loc: list, max_visits: int) -> np.ndarray:
    """Which visits to keep, given the station of each visit in time order.

    Runs of at most `max_visits` visits are misreads. The shortest run (ties:
    the station with fewer visits) is dropped first, so that the runs around
    it join, until every run is longer than `max_visits` or one run is left.
    """
    keep = np.ones(len(loc), dtype=bool)
    if max_visits < 1:
        return keep
    loc = list(loc)
    while True:
        idx = np.flatnonzero(keep)
        vals, lens = _rle([loc[i] for i in idx])
        if len(lens) <= 1:
            break
        cand = [j for j, n in enumerate(lens) if n <= max_visits]
        if not cand:
            break
        total = Counter(loc[i] for i in idx)
        j = sorted(cand, key=lambda c: (lens[c], total[vals[c]]))[0]
        end = sum(lens[: j + 1])
        keep[idx[end - lens[j]: end]] = False
    return keep


def _rle(x: list) -> tuple[list, list]:
    vals, lens = [], []
    for v in x:
        if vals and vals[-1] == v:
            lens[-1] += 1
        else:
            vals.append(v)
            lens.append(1)
    return vals, lens


def _resolve_transfers(dt: pd.DataFrame, max_visits: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    ident = dt[dt["identified"]]
    n_loc = ident.groupby("responder")["location"].nunique()
    multi = list(n_loc.index[n_loc > 1])
    rows = []
    misread_idx: list[int] = []
    for r, g in ident.groupby("responder", sort=False):
        g = g.sort_values("entry_time", kind="stable")
        n_mis = 0
        if r in multi:
            keep = misread_runs(list(g["location"]), max_visits)
            n_mis = int((~keep).sum())
            misread_idx.extend(g.index[~keep])
            g = g[keep]
        vals, lens = _rle(list(g["location"]))
        counts = Counter(g["location"])
        rows.append({
            "responder": r,
            "location_path": ">".join(vals),
            "main_location": max(counts, key=lambda k: (counts[k], -sorted(counts).index(k))),
            "n_locations": len(counts),
            "n_transfers": len(vals) - 1,
            "transfer": len(vals) > 1,
            "misreads": n_mis,
        })
    if misread_idx:
        dt.loc[misread_idx, "identified"] = False
        dt.loc[misread_idx, "responder"] = None
    stations = pd.DataFrame(rows, columns=["responder", "location_path", "main_location",
                                           "n_locations", "n_transfers", "transfer", "misreads"])
    if stations.empty:
        return dt, stations
    stations = stations.sort_values(["main_location", "responder"], kind="stable").reset_index(drop=True)
    if not multi:
        msg("No pig was seen at more than one station", "info")
    else:
        n_tr = int(stations["transfer"].sum())
        n_mr = int((stations["misreads"] > 0).sum())
        msg(f"{plural(len(multi), 'pig')} seen at several stations: {n_tr} moved between stations, "
            f"{n_mr} with misreads ({len(misread_idx)} visits kept as unidentified)", "warning")
        for _, s in stations[stations["responder"].isin(multi)].iterrows():
            msg(f"{s['responder']}: {s['location_path']}"
                + (f", {s['misreads']} misreads" if s["misreads"] else ""), "info", level=2)
        many = stations[stations["n_transfers"] > 3]
        for _, s in many.iterrows():
            msg(f"Pig {s['responder']} moves {s['n_transfers']} times between stations "
                f"({s['location_path']}). Are these stations in the same pen?", "warning")
    return dt, stations
