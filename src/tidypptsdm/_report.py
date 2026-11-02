"""Offline HTML report to browse station by station (same page as the R package)."""

from __future__ import annotations

import html
import json
import os
import sys
import webbrowser
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

from ._version import __version__
from ._messages import Abort, local_verbose, msg, plural
from ._monitor import Monitor, _fmt_date
from ._plots import _pick_locations, plot_monitor, save_monitor_plots

REPORT_PLOTS = ("trend", "intake", "weight", "hours")
MAX_WORKERS = 8           # more processes add memory but little speed
MIN_PARALLEL = 6          # fewer stations: starting the processes costs more than it saves


# ---- drawing the plots, one station at a time or on several cores -------------------------

def _draw_station(mon: Monitor, loc: str, img: Path, dpi: int) -> list[tuple]:
    plots = []
    for kind in REPORT_PLOTS:
        plots += plot_monitor(mon, kind, [loc])
    sv = save_monitor_plots(plots, img, dpi=dpi, verbose=0)
    return [(r.location, r.type, Path(r.file).name, bool(r.saved)) for r in sv.itertuples()]


def _draw_chunk(mon: Monitor, locs: list[str], img: Path, dpi: int, zh: bool = False) -> list[tuple]:
    from ._plots import set_language
    set_language(zh)  # a worker process starts in English
    out = []
    for loc in locs:
        out += _draw_station(mon, loc, img, dpi)
    return out


def _subset(mon: Monitor, locs: list[str]) -> Monitor:
    """The rows the plots of these stations need (sent to a worker process)."""
    keep = set(locs)

    def f(d: pd.DataFrame) -> pd.DataFrame:
        return d[d["location"].isin(keep)] if "location" in d.columns else d.iloc[:0]

    return Monitor(stations=f(mon.stations), houses=mon.houses.iloc[:0], pigs=f(mon.pigs),
                   pig_summary=f(mon.pig_summary), hours=f(mon.hours), alerts=f(mon.alerts),
                   visits=f(mon.visits), settings=mon.settings)


def _n_workers(workers: int | None, n_locs: int) -> int:
    if workers is None:
        if n_locs < MIN_PARALLEL:
            return 1
        cpus = os.process_cpu_count() if hasattr(os, "process_cpu_count") else os.cpu_count()
        workers = min(MAX_WORKERS, cpus or 1)
    return max(1, min(int(workers), n_locs))


@contextmanager
def _no_main_rerun():
    """New processes on Windows and macOS start by running the main script
    again. A script without ``if __name__ == "__main__":`` would then read
    the data again. The workers only need tidypptsdm, so hide the script
    while they start (the exe and ``python -m`` are not affected)."""
    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None)
    hide = (main is not None and path is not None and getattr(main, "__spec__", None) is None
            and not getattr(sys, "frozen", False))
    if hide:
        del main.__file__
    try:
        yield
    finally:
        if hide:
            main.__file__ = path


def _draw_all(mon: Monitor, locs: list[str], img: Path, dpi: int, workers: int,
              progress, zh: bool = False) -> list[tuple]:
    if workers > 1:
        # round robin, so that every chunk has stations from all houses
        chunks = [locs[i::workers * 3] for i in range(min(len(locs), workers * 3))]
        rows, done = [], set()
        ex = None
        try:
            with _no_main_rerun():  # the processes start while the jobs are handed out
                ex = ProcessPoolExecutor(max_workers=workers)
                futures = {ex.submit(_draw_chunk, _subset(mon, c), c, img, dpi, zh): c for c in chunks}
            for fut in as_completed(futures):
                rows += fut.result()
                done.update(futures[fut])
                progress(len(done))
            return rows
        except Exception as e:  # noqa: BLE001 - fall back to one process
            msg(f"Drawing on {workers} cores failed ({type(e).__name__}: {e}); "
                "drawing the other stations one at a time.", "warning")
        finally:
            if ex is not None:
                ex.shutdown(wait=True, cancel_futures=True)
        locs = [l for l in locs if l not in done]
        out = rows
    else:
        out, done = [], set()
    if not locs:
        return out
    from ._plots import set_language
    set_language(zh)
    try:
        for loc in locs:
            out += _draw_station(mon, loc, img, dpi)
            done.add(loc)
            progress(len(done))
    finally:
        if zh:
            set_language(False)
    return out


STATUS_LABEL = {"ok": "ok", "low_feed": "low feed", "no_visit": "no visit",
                "danger": "danger", "warning": "warning"}


def _esc(x) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)) or x is pd.NA:
        return ""
    return html.escape(str(x), quote=True)


def _num(x, digits: int = 0) -> str:
    if x is None or x is pd.NA or (isinstance(x, (float, np.floating)) and np.isnan(x)):
        return ""
    return f"{float(x):,.{digits}f}"


def _tag(s) -> str:
    return f'<span class="tag s-{s}">{_esc(STATUS_LABEL.get(s, s))}</span>'


def _table(head: str, rows: list[str]) -> str:
    return ('<div class="scroll"><table class="pigs"><thead><tr>' + head + "</tr></thead><tbody>"
            + "\n".join(rows) + "</tbody></table></div>")


def _link(loc: str, page_of: dict, text: str | None = None, pig: str | None = None) -> str:
    p = page_of[loc]
    extra = f' data-pig="{_esc(pig)}"' if pig else ""
    return f'<a href="#p-{p}" data-page="{p}"{extra}>{_esc(text if text is not None else loc)}</a>'


def _alerts_html(a: pd.DataFrame, page_of: dict, link: bool = True) -> str:
    if len(a) == 0:
        return '<p class="muted">None.</p>'
    rows = []
    for _, r in a.iterrows():
        pig = r["responder"] if isinstance(r["responder"], str) else None
        st = _link(r["location"], page_of) if link else _esc(r["location"])
        pg = "" if pig is None else (_link(r["location"], page_of, pig, pig) if link else _esc(pig))
        rows.append(f'<tr><td>{_tag(r["level"])}</td><td class="id">{st}</td><td class="id">{pg}</td>'
                    f'<td>{_esc(r["type"].replace("_", " "))}</td><td class="note">{_esc(r["message"])}</td></tr>')
    return _table("<th>Level</th><th>Station</th><th>Pig</th><th>Alert</th><th>Detail</th>", rows)


STATION_HEAD = (
    '<th>Station</th><th class="n">Pigs</th><th class="n">Visits</th>'
    '<th class="n">Unidentified<br><small>%</small></th>'
    '<th class="n">Occupation<br><small>h</small></th>'
    '<th class="n">Feed<br><small>kg</small></th>'
    '<th class="n">Feed per pig<br><small>kg</small></th>'
    '<th class="n">Weight<br><small>kg</small></th>'
    '<th class="n">Weight outliers<br><small>%</small></th>'
    '<th class="n">Alerts</th>')


def _station_rows(last: pd.DataFrame, page_of: dict, n_alerts: dict) -> list[str]:
    rows = []
    for _, r in last.iterrows():
        na = n_alerts.get(r["location"], 0)
        down = ' class="s-down"' if r["n_visits"] == 0 else ""
        rows.append(
            f'<tr{down}><td class="id">{_link(r["location"], page_of)}</td>'
            f'<td class="n">{_num(r["n_pigs"])}</td><td class="n">{_num(r["n_visits"])}</td>'
            f'<td class="n">{_num(r["pct_unidentified"], 1)}</td><td class="n">{_num(r["occupation_h"], 1)}</td>'
            f'<td class="n">{_num(r["feed_kg"], 1)}</td><td class="n">{_num(r["feed_per_pig_kg"], 2)}</td>'
            f'<td class="n">{_num(r["weight_kg"], 1)}</td><td class="n">{_num(r["pct_weight_outlier"], 1)}</td>'
            f'<td class="n{" warn" if na > 0 else ""}">{na}</td></tr>')
    return rows


def _pig_table(d: pd.DataFrame) -> str:
    if len(d) == 0:
        return '<p class="muted">No identified pig in the window.</p>'
    rows = []
    for _, r in d.iterrows():
        pid = _esc(r["responder"])
        rows.append(
            f'<tr id="pig-{pid}"><td class="id">{pid}</td><td>{_tag(r["status"])}</td>'
            f'<td class="n">{_num(r["last_visits"])}</td><td class="n">{_num(r["last_feed_kg"], 2)}</td>'
            f'<td class="n">{_num(r["mean_feed_kg"], 2)}</td>'
            f'<td class="n{" warn" if r["low_feed_days"] > 0 else ""}">{int(r["low_feed_days"])}</td>'
            f'<td class="n{" warn" if r["no_visit_days"] > 0 else ""}">{int(r["no_visit_days"])}</td>'
            f'<td class="n">{_num(r["days_since_visit"])}</td><td class="n">{_num(r["last_weight_kg"], 1)}</td></tr>')
    return _table(
        '<th>Pig</th><th>Status</th><th class="n">Visits</th>'
        '<th class="n">Feed<br><small>kg</small></th>'
        '<th class="n">Mean feed<br><small>kg/d</small></th>'
        '<th class="n">Low-feed<br><small>days</small></th>'
        '<th class="n">No-visit<br><small>days</small></th>'
        '<th class="n">Days since<br><small>visit</small></th>'
        '<th class="n">Weight<br><small>kg</small></th>', rows)


def _card(label: str, value, sub: str = "") -> str:
    return (f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div>'
            f'<div class="sub">{sub}</div></div>')


def monitor_title(mon: Monitor) -> str:
    s = mon.settings
    st = f"{str(s['station']).upper()} station monitor".strip()
    return f"{st}, {_fmt_date(s['start_date'])} to {_fmt_date(s['end_date'])}"


def _monitor_html(mon: Monitor, locs: list[str], files: dict, title: str) -> str:
    s = mon.settings
    end = s["end_date"]
    page_of = {l: i + 1 for i, l in enumerate(locs)}
    last = mon.stations[(mon.stations["date"] == end) & mon.stations["location"].isin(locs)]
    last = last.set_index("location").loc[locs].reset_index()
    a = mon.alerts[mon.alerts["location"].isin(locs)]
    n_alerts = a.groupby("location").size().to_dict()
    ps = mon.pig_summary[mon.pig_summary["location"].isin(locs)]
    recording = set(last.loc[last["n_visits"] > 0, "location"])
    ps_rec = ps[ps["location"].isin(recording)]

    n_down = int((last["n_visits"] == 0).sum())
    vis = int(last["n_visits"].sum())
    unid = int(last["n_unidentified"].sum())
    feed = float(last["feed_kg"].sum())
    np_total = int(last["n_pigs"].sum())
    per_pig = (float((last["feed_per_pig_kg"].fillna(0) * last["n_pigs"]).sum()) / np_total
               if np_total > 0 else np.nan)
    cards = ('<div class="cards">'
             + _card("Stations", len(locs), f'<span class="warn">{n_down} without visits</span>'
                     if n_down else "all recording")
             + _card("Pigs", len(ps), f"{int((ps_rec['status'] == 'no_visit').sum())} no visit &middot; "
                     f"{int((ps_rec['status'] == 'low_feed').sum())} low feed"
                     + (" (recording stations)" if n_down else ""))
             + _card("Visits", _num(vis), f"{_num(100 * unid / vis if vis else np.nan, 1)}% unidentified")
             + _card("Feed intake", f"{_num(feed, 1)} kg", f"{_num(per_pig, 2)} kg per pig")
             + _card("Alerts", len(a), f"{int((a['level'] == 'danger').sum())} danger &middot; "
                     f"{int((a['level'] == 'warning').sum())} warning")
             + "</div>")
    hw = s["house_width"]
    settings = {
        "Window": f"{_fmt_date(s['start_date'])} to {_fmt_date(end)} ({s['days']} days)",
        "Low feed": f"below {s['low_feed_kg']:g} kg per day",
        "Unidentified visits": f"alert above {s['max_unidentified_pct']:g}%",
        "Feed drop": f"alert more than {s['max_feed_drop_pct']:g}% below the mean of the earlier days",
        "Weight outliers": f"Tukey fences, k = {s['iqr_k']:g}",
        "House": f"first {hw} character{'s' if hw > 1 else ''} of the station ID",
        "Package": f"tidypptsdm {__version__} (Python)",
    }
    settings_html = ('<dl class="settings">'
                     + "".join(f"<dt>{k}</dt><dd>{_esc(v)}</dd>" for k, v in settings.items()) + "</dl>")
    hl = mon.houses[mon.houses["date"] == end]
    house_html = _table(
        '<th>House</th><th class="n">Stations</th><th class="n">Pigs</th>'
        '<th class="n">Visits</th><th class="n">Feed<br><small>kg</small></th>'
        '<th class="n">Feed per pig<br><small>kg</small></th><th class="n">Weight<br><small>kg</small></th>',
        [f'<tr><td class="id">{_esc(r["house"])}</td><td class="n">{r["n_stations"]}</td>'
         f'<td class="n">{r["n_pigs"]}</td><td class="n">{_num(r["n_visits"])}</td>'
         f'<td class="n">{_num(r["feed_kg"], 1)}</td><td class="n">{_num(r["feed_per_pig_kg"], 2)}</td>'
         f'<td class="n">{_num(r["weight_kg"], 1)}</td></tr>' for _, r in hl.iterrows()])
    d_end = _fmt_date(end)
    alert_count = f' <span class="count">{len(a)}</span>' if len(a) else ""
    note = s.get("stale_note") or ""
    stale = (f'<p class="lead"><span class="tag s-warning">old data</span> <span class="warn">'
             f'{_esc(note)}</span></p>') if note else ""
    overview = ('<section class="page" id="p-0" data-title="Overview">'
                f'<h1>Overview</h1><p class="lead">Last day: {d_end}</p>{stale}{cards}'
                f"<h2>Alerts{alert_count}</h2>"
                + _alerts_html(a, page_of)
                + f"<h2>Stations on {d_end}</h2>" + _table(STATION_HEAD, _station_rows(last, page_of, n_alerts))
                + f"<h2>Houses on {d_end}</h2>" + house_html
                + "<h2>Settings</h2>" + settings_html + "</section>")

    def fig(loc: str, kind: str, cap: str) -> str:
        f = files.get((loc, kind))
        if not f:
            return ""
        src = "img/" + quote(f)
        return (f'<figure><a href="{src}" target="_blank" title="Open the full-size plot">'
                f'<img loading="lazy" src="{src}" alt="{_esc(cap)}"></a><figcaption>{cap}</figcaption></figure>')

    pages = []
    for l in locs:
        b = last[last["location"] == l].iloc[0]
        al = a[a["location"] == l]
        sub = (f"{plural(int(b['n_pigs']), 'pig')} &middot; {_num(b['n_visits'])} visits &middot; "
               f"{_num(b['feed_kg'], 1)} kg feed on {d_end}"
               + (' &middot; <span class="warn">no visits</span>' if b["n_visits"] == 0 else ""))
        pages.append(
            f'<section class="page" id="p-{page_of[l]}" data-title="Station {_esc(l)}" hidden>'
            f'<h1>Station {_esc(l)}</h1><p class="lead">{sub}</p>'
            + (f'<h2>Alerts <span class="count">{len(al)}</span></h2>' + _alerts_html(al, page_of, False)
               if len(al) else "")
            + fig(l, "trend", "Daily trend over the window, with the body weight of the pigs "
                              "(band: lightest to heaviest); red: days without visits")
            + fig(l, "intake", "Feed intake per pig and day: share of the station (top) and kg (bottom); "
                               "pigs without visit or with low feed on the last day are marked in the legend")
            + "<h2>Pigs</h2>" + _pig_table(ps[ps["location"] == l])
            + fig(l, "weight", "Recorded body weights per day")
            + fig(l, "hours", f"Visits, occupation and feed intake per hour of {d_end}")
            + "</section>")

    nav = '<a href="#p-0" data-page="0" class="nav-item">Overview</a>' + "".join(
        f'<a href="#p-{page_of[l]}" data-page="{page_of[l]}" class="nav-item">Station {_esc(l)}'
        + (f' <span class="badge" title="alerts">{n_alerts[l]}</span>' if n_alerts.get(l) else "")
        + "</a>" for l in locs)
    pig_map = json.dumps({str(r): page_of[l] for r, l in zip(ps["responder"], ps["location"])},
                         ensure_ascii=False)
    tpl = (resources.files("tidypptsdm") / "templates" / "report.html").read_text(encoding="utf-8")
    repl = {"{{TITLE}}": _esc(title), "{{NAV}}": nav, "{{PAGES}}": "\n".join([overview] + pages),
            "{{PIGS}}": pig_map, "{{DATE}}": pd.Timestamp.today().strftime("%Y-%m-%d")}
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    return tpl


def write_monitor_report(mon: Monitor, path, title: str | None = None, locations=None,
                         dpi: int = 150, open: bool = False, workers: int | None = None,
                         progress=None, verbose: int = 1) -> Path:
    """Write an HTML report to browse station by station.

    Writes ``index.html`` and the plots (``img/``) into ``path``. Open
    ``index.html`` in a web browser: the first page is an overview of the
    last day (stations, pigs, visits, feed intake, the alerts, a table of all
    stations and houses, the settings), then one page per station with its
    alerts, the plots ``trend``, ``intake``, ``weight`` and ``hours`` and a
    table of its pigs. Turn the pages with the arrow keys; type a pig ID to
    jump to its station. The folder works offline.

    Args:
        mon: Result of [run_monitor()][tidypptsdm.run_monitor].
        path: Folder to write to (created if needed).
        title: Title of the report. Default: station type and window.
        locations: Stations to include. Default ``None``: all.
        dpi: Resolution of the plots. Default 150.
        open: Open the report in the web browser when done.
        workers: Number of processes that draw the plots at the same time.
            Default ``None``: one per CPU core (at most 8) when there are 6
            stations or more, otherwise 1. ``1`` draws one station at a time.
        progress: A function called as ``progress(done, total)`` after the
            plots of each station (e.g. for a progress bar).
        verbose: 0 (silent) or 1.

    Returns:
        The path of ``index.html``.
    """
    with local_verbose(verbose):
        if not isinstance(mon, Monitor):
            raise Abort("`mon` must be the result of run_monitor().")
        if not path:
            raise Abort("`path` must be a folder name.")
        path = Path(path)
        locs = _pick_locations(mon, locations)
        img = path / "img"
        img.mkdir(parents=True, exist_ok=True)
        n_workers = _n_workers(workers, len(locs))
        step = max(1, len(locs) // 10)
        shown = [0]

        def show(n: int) -> None:
            if progress is not None:
                progress(n, len(locs))
            if len(locs) > 10 and (n - shown[0] >= step or n == len(locs)):
                shown[0] = n
                msg(f"Plots: {n} of {len(locs)} stations", "info")

        if n_workers > 1 and len(locs) > 10:
            msg(f"Drawing the plots on {n_workers} cores", "info")
        rows = _draw_all(mon, locs, img, dpi, n_workers, show)
        files = {(l, t): f for l, t, f, ok in rows if ok}
        n_bad = sum(not ok for *_, ok in rows)
        if n_bad:
            msg(f"{n_bad} plot(s) could not be saved.", "warning")
        out = path / "index.html"
        out.write_text(_monitor_html(mon, locs, files, title or monitor_title(mon)), encoding="utf-8")
        msg(f"Report of {plural(len(locs), 'station')} written to {out}", "success")
        if open:
            webbrowser.open(out.resolve().as_uri())
        return out
