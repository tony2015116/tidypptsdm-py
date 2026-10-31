"""Command line: ``tidypptsdm run|schedule|unschedule|example|gui``.

Without arguments (e.g. a double click on the exe) the desktop app opens.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._messages import Abort
from ._version import __version__


def _add_monitor_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("monitor settings")
    g.add_argument("--days", type=int, default=7, help="days in the window (default 7)")
    g.add_argument("--end-date", default=None, help="last day, YYYY-MM-DD (default: last full day)")
    g.add_argument("--house-width", type=int, default=1,
                   help="leading characters of the station ID that name the house (default 1)")
    g.add_argument("--low-feed-kg", type=float, default=0.5, help="low feed intake per day, kg (default 0.5)")
    g.add_argument("--max-unidentified-pct", type=float, default=5,
                   help="alert above this %% of unidentified visits (default 5)")
    g.add_argument("--max-feed-drop-pct", type=float, default=30,
                   help="alert when station feed drops more than this %% (default 30)")
    g.add_argument("--iqr-k", type=float, default=1.5, help="Tukey fences for weight outliers (default 1.5)")
    g.add_argument("--station", choices=["nedap", "fire"], default=None, help="station type (default: detect)")
    g.add_argument("--time-zone", default="local",
                   help="convert times with a time zone (e.g. ...T00:34:17Z) to this zone: "
                        "'local' (default, this computer) or a name such as Asia/Shanghai")


def _monitor_kwargs(a: argparse.Namespace) -> dict:
    return dict(days=a.days, end_date=a.end_date, house_width=a.house_width, low_feed_kg=a.low_feed_kg,
                max_unidentified_pct=a.max_unidentified_pct, max_feed_drop_pct=a.max_feed_drop_pct,
                iqr_k=a.iqr_k, station=a.station, time_zone=a.time_zone)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tidypptsdm",
        description="Daily monitoring of pig performance testing stations (NEDAP and FIRE).")
    p.add_argument("--version", action="version", version=f"tidypptsdm {__version__}")
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("run", help="run the monitor and write the report and the tables")
    r.add_argument("data", help="folder (or file) with the station exports")
    r.add_argument("--out", required=True, help="folder for the results; one subfolder per day")
    r.add_argument("--format", choices=["xlsx", "csv"], default="xlsx", help="tables (default xlsx)")
    r.add_argument("--open", action="store_true", help="open the report in the web browser")
    r.add_argument("-q", "--quiet", action="store_true", help="no messages")
    _add_monitor_args(r)

    s = sub.add_parser("schedule", help="run the monitor every day")
    s.add_argument("data", help="folder with the station exports")
    s.add_argument("--out", required=True, help="folder for the results")
    s.add_argument("--time", default="07:30", help="time of the daily run, HH:MM (default 07:30)")
    s.add_argument("--taskname", default="tidypptsdm_monitor")
    s.add_argument("--format", choices=["xlsx", "csv"], default="xlsx")
    s.add_argument("--no-register", action="store_true", help="only write the script")
    _add_monitor_args(s)

    st = sub.add_parser("status", help="state of the daily task and the end of its log")
    st.add_argument("--out", default=None, help="result folder (to show its log)")
    st.add_argument("--taskname", default="tidypptsdm_monitor")

    u = sub.add_parser("unschedule", help="remove the daily task (Windows)")
    u.add_argument("taskname", nargs="?", default="tidypptsdm_monitor")

    e = sub.add_parser("example", help="write the example exports into a folder")
    e.add_argument("folder")
    e.add_argument("--station", choices=["nedap", "fire"], default="nedap")

    sub.add_parser("gui", help="open the desktop app")

    t = sub.add_parser("selftest", help="check that the desktop app can start (writes a report)")
    t.add_argument("--out", default=None, help="folder for the report tidypptsdm-selftest.txt")
    return p


def _ensure_streams(a: argparse.Namespace) -> None:
    """The windowed exe has no console: write the messages to a log file in
    the result folder (scheduled runs) instead of losing them."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    folder = Path(getattr(a, "out", None) or Path.home())
    try:
        folder.mkdir(parents=True, exist_ok=True)
        log = open(folder / "tidypptsdm.log", "a", encoding="utf-8")  # noqa: SIM115
    except OSError:
        return
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from .gui import main as gui_main
        gui_main()
        return 0
    a = build_parser().parse_args(argv)
    _ensure_streams(a)
    try:
        if a.command == "run":
            import datetime

            from ._messages import msg
            from ._schedule import monitor_to_folder
            msg(f"tidypptsdm {__version__}: run started {datetime.datetime.now():%Y-%m-%d %H:%M:%S}", "h1")
            res = monitor_to_folder(a.data, a.out, format=a.format, open=a.open,
                                    verbose=0 if a.quiet else 1, **_monitor_kwargs(a))
            n_danger = int((res["monitor"].alerts["level"] == "danger").sum())
            return 2 if n_danger else 0
        if a.command == "schedule":
            from ._schedule import schedule_monitor
            kw = _monitor_kwargs(a)
            kw.pop("end_date")      # a daily task always ends on the last full day
            schedule_monitor(a.data, a.out, time=a.time, taskname=a.taskname, format=a.format,
                             register=not a.no_register, **kw)
            return 0
        if a.command == "status":
            from ._schedule import task_status
            print(task_status(a.taskname, a.out))
            return 0
        if a.command == "unschedule":
            from ._schedule import unschedule_monitor
            unschedule_monitor(a.taskname)
            return 0
        if a.command == "example":
            from .datasets import write_example
            print(write_example(Path(a.folder), a.station))
            return 0
        if a.command == "selftest":
            from ._tkcheck import diagnose
            ok, lines = diagnose()
            text = "\n".join(lines)
            print(text)
            if a.out:
                Path(a.out).mkdir(parents=True, exist_ok=True)
                (Path(a.out) / "tidypptsdm-selftest.txt").write_text(text + "\n", encoding="utf-8")
            return 0 if ok else 1
        if a.command == "gui":
            from .gui import main as gui_main
            gui_main()
            return 0
        build_parser().print_help()
        return 1
    except Abort as e:
        print(f"x {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
