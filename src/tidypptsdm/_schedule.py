"""Run the whole monitor into a folder, and schedule it every day."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from ._messages import Abort, local_verbose, msg
from ._monitor import _fmt_date, run_monitor
from ._report import write_monitor_report
from ._tables import write_monitor_tables

MONITOR_ARGS = ("days", "end_date", "house_width", "low_feed_kg", "max_unidentified_pct",
                "max_feed_drop_pct", "iqr_k", "station", "time_zone")


def monitor_to_folder(data, out_dir, format: str = "xlsx", open: bool = False,
                      verbose: int = 1, **monitor_args) -> dict:
    """Run the monitor and write the report and the tables into
    ``out_dir/<last day>/``.

    This is what the command line (``tidypptsdm run``), the desktop app and
    the scheduled task do.

    Args:
        data: Folder or files of exports, or a DataFrame (see
            [run_monitor()][tidypptsdm.run_monitor]).
        out_dir: Folder for the results; one subfolder per day.
        format: Format of the tables, ``"xlsx"`` or ``"csv"``.
        open: Open the report in the web browser when done.
        verbose: 0 (silent), 1 or 2.
        **monitor_args: Arguments of ``run_monitor()`` such as ``days``,
            ``house_width`` or ``low_feed_kg``.

    Returns:
        A dict with ``monitor``, ``folder``, ``report`` and ``tables``.
    """
    bad = sorted(set(monitor_args) - set(MONITOR_ARGS))
    if bad:
        raise Abort(f"Unknown argument(s) {bad}; allowed: {list(MONITOR_ARGS)}.")
    with local_verbose(verbose):
        mon = run_monitor(data, verbose=verbose, **monitor_args)
        folder = Path(out_dir) / _fmt_date(mon.settings["end_date"])
        report = write_monitor_report(mon, folder, open=open, verbose=verbose)
        tables = write_monitor_tables(mon, folder, format=format, verbose=verbose)
        return {"monitor": mon, "folder": folder, "report": report, "tables": tables}


def _command(folder: Path, out_dir: Path, format: str, monitor_args: dict) -> list[str]:
    if getattr(sys, "frozen", False):          # the exe built with PyInstaller
        cmd = [sys.executable, "run"]
    else:
        cmd = [sys.executable, "-m", "tidypptsdm", "run"]
    cmd += [str(folder), "--out", str(out_dir), "--format", format]
    for k, v in monitor_args.items():
        if v is None:
            continue
        cmd += ["--" + k.replace("_", "-"), str(v)]
    return cmd


def schedule_monitor(folder, out_dir, time: str = "07:30", taskname: str = "tidypptsdm_monitor",
                     script_dir=None, format: str = "xlsx", register: bool = True,
                     verbose: int = 1, **monitor_args) -> Path:
    """Run the monitor every day.

    Writes a small script that runs ``tidypptsdm run`` on ``folder`` and
    writes the report and the tables into ``out_dir/<last day>/``, then:

    - on Windows registers it in the Task Scheduler (``schtasks``), to run
      every day at ``time``;
    - on Linux and macOS prints the line to add with ``crontab -e``.

    Args:
        folder: Folder with the station exports.
        out_dir: Folder for the results; one subfolder per day.
        time: Time of the daily run, ``"HH:MM"``. Default ``"07:30"``.
        taskname: Name of the task and of the script: letters, digits,
            ``_`` and ``-``.
        script_dir: Folder for the script. Default ``out_dir``.
        format: ``"xlsx"`` or ``"csv"``.
        register: Register the task (Windows) or print the crontab line.
            With ``False`` only the script is written.
        verbose: 0 (silent) or 1.
        **monitor_args: Arguments of ``run_monitor()`` such as ``days``,
            ``house_width`` or ``low_feed_kg``.

    Returns:
        The path of the script (``.bat`` on Windows, ``.sh`` otherwise).
    """
    with local_verbose(verbose):
        folder, out_dir = Path(folder), Path(out_dir)
        if not folder.is_dir():
            raise Abort(f"Folder not found: {folder}.")
        if not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", str(time)):
            raise Abort(f"`time` must be a time such as '07:30', not {time!r}.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", taskname or ""):
            raise Abort("`taskname` may contain only letters, digits, '_' and '-'.")
        if format not in ("xlsx", "csv"):
            raise Abort("`format` must be 'xlsx' or 'csv'.")
        bad = sorted(set(monitor_args) - set(MONITOR_ARGS))
        if bad:
            raise Abort(f"Unknown argument(s) {bad}; allowed: {list(MONITOR_ARGS)}.")
        out_dir.mkdir(parents=True, exist_ok=True)
        script_dir = Path(script_dir) if script_dir else out_dir
        script_dir.mkdir(parents=True, exist_ok=True)
        cmd = _command(folder.resolve(), out_dir.resolve(), format, monitor_args)
        windows = os.name == "nt"
        script = (script_dir / f"{taskname}{'.bat' if windows else '.sh'}").resolve()
        log = script.with_suffix(".log")
        if windows:
            line = subprocess.list2cmdline(cmd)
            text = ("@echo off\r\nrem Written by tidypptsdm: daily monitor of the testing stations.\r\n"
                    "chcp 65001 >nul\r\n"
                    f'{line} >> "{log}" 2>&1\r\n')
            script.write_text(text, encoding="utf-8")
        else:
            line = " ".join(shlex.quote(c) for c in cmd)
            script.write_text("#!/bin/sh\n# Written by tidypptsdm: daily monitor of the testing stations.\n"
                              f"{line} >> {shlex.quote(str(log))} 2>&1\n", encoding="utf-8")
            script.chmod(0o755)
        msg(f"Monitor script written to {script}", "success")
        if register:
            if windows:
                res = subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/TN", taskname,
                                      "/TR", f'"{script}"', "/ST", time],
                                     capture_output=True, text=True)
                if res.returncode != 0:
                    raise Abort(f"Could not register the task: {(res.stderr or res.stdout).strip()}")
                msg(f"Task '{taskname}' runs every day at {time}. Remove it with "
                    f"unschedule_monitor('{taskname}') or `tidypptsdm unschedule {taskname}`.", "success")
            else:
                hh, mm = (int(x) for x in time.split(":"))
                msg(f"Add this line with `crontab -e` to run the monitor every day at {time}:", "info")
                if verbose:
                    print(f"{mm} {hh} * * * {shlex.quote(str(script))}")
        return script


def unschedule_monitor(taskname: str = "tidypptsdm_monitor", verbose: int = 1) -> None:
    """Remove the daily task registered by ``schedule_monitor()`` (Windows).

    On Linux and macOS, remove the line with ``crontab -e``.
    """
    with local_verbose(verbose):
        if os.name != "nt":
            msg("On Linux and macOS remove the line of the monitor with `crontab -e`.", "info")
            return
        res = subprocess.run(["schtasks", "/Delete", "/F", "/TN", taskname], capture_output=True, text=True)
        if res.returncode != 0:
            raise Abort(f"Could not remove the task: {(res.stderr or res.stdout).strip()}")
        msg(f"Task '{taskname}' removed", "success")
