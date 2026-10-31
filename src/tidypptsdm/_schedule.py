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


def _python_no_console() -> str:
    """pythonw.exe next to python.exe, so a scheduled run opens no window."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w) if os.name == "nt" and w.exists() else str(exe)


def _command(folder: Path, out_dir: Path, format: str, monitor_args: dict,
             no_console: bool = False) -> list[str]:
    if getattr(sys, "frozen", False):          # the exe built with PyInstaller
        cmd = [sys.executable, "run"]
    else:
        py = _python_no_console() if no_console else sys.executable
        cmd = [py, "-m", "tidypptsdm", "run"]
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
            # a script to run the monitor by hand; the task itself starts the
            # program directly (no console window, no code page issues)
            line = subprocess.list2cmdline(cmd)
            text = ("@echo off\r\nrem Written by tidypptsdm: run the daily monitor by hand.\r\n"
                    f'{line} >> "{log}" 2>&1\r\n')
            try:
                script.write_bytes(text.encode("mbcs"))      # the code page cmd.exe reads
            except (UnicodeEncodeError, LookupError):
                script.write_text("@echo off\r\nchcp 65001 >nul\r\n" + text.split("\r\n", 1)[1],
                                  encoding="utf-8")
        else:
            line = " ".join(shlex.quote(c) for c in cmd)
            script.write_text("#!/bin/sh\n# Written by tidypptsdm: daily monitor of the testing stations.\n"
                              f"{line} >> {shlex.quote(str(log))} 2>&1\n", encoding="utf-8")
            script.chmod(0o755)
        msg(f"Monitor script written to {script}", "success")
        if register:
            if windows:
                task_cmd = _command(folder.resolve(), out_dir.resolve(), format, monitor_args,
                                    no_console=True)
                _register_windows_task(taskname, time, task_cmd, out_dir.resolve())
                msg(f"Task '{taskname}' runs every day at {time}, also on battery; if the computer "
                    f"is off or asleep at that time, it runs as soon as it is on again. "
                    f"Each run writes to {out_dir.resolve() / 'tidypptsdm.log'}. Remove it with "
                    f"`tidypptsdm unschedule {taskname}`.", "success")
            else:
                hh, mm = (int(x) for x in time.split(":"))
                msg(f"Add this line with `crontab -e` to run the monitor every day at {time}:", "info")
                if verbose:
                    print(f"{mm} {hh} * * * {shlex.quote(str(script))}")
        return script


def _xml(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _task_xml(time: str, cmd: list[str], workdir: Path) -> str:
    """Task Scheduler definition: daily, also on battery, catch up a missed
    run, at most 2 hours, for the current user while logged on."""
    import datetime as _d
    start = _d.datetime.now().strftime("%Y-%m-%d") + f"T{time}:00"
    user = os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")
    args = subprocess.list2cmdline(cmd[1:])
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>tidypptsdm: daily monitor of the testing stations</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{_xml(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_xml(cmd[0])}</Command>
      <Arguments>{_xml(args)}</Arguments>
      <WorkingDirectory>{_xml(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _schtasks(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _register_windows_task(taskname: str, time: str, cmd: list[str], workdir: Path) -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "task.xml"
        xml.write_text(_task_xml(time, cmd, workdir), encoding="utf-16")
        res = _schtasks(["/Create", "/F", "/TN", taskname, "/XML", str(xml)])
    if res.returncode != 0:
        raise Abort(f"Could not register the task: {(res.stderr or res.stdout).strip()}")


def task_status(taskname: str = "tidypptsdm_monitor", out_dir=None, lines: int = 15) -> str:
    """State of the daily task (Windows) and the end of its log, as text.

    Shows the next and last run time and the result of the last run as
    Windows reports them (0 = success), and the last lines of
    ``out_dir/tidypptsdm.log``.
    """
    parts = []
    if os.name == "nt":
        res = _schtasks(["/Query", "/TN", taskname, "/V", "/FO", "LIST"])
        if res.returncode != 0:
            parts.append(f"No task '{taskname}': {(res.stderr or res.stdout).strip()}")
        else:
            parts.append(res.stdout.strip())
    else:
        parts.append("Scheduled with cron: see `crontab -l`.")
    if out_dir:
        log = Path(out_dir) / "tidypptsdm.log"
        if log.exists():
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
            parts.append(f"--- last lines of {log} ---\n" + "\n".join(tail))
        else:
            parts.append(f"No log yet: {log} (the task has not run yet).")
    return "\n\n".join(parts)


def run_task_now(taskname: str = "tidypptsdm_monitor") -> None:
    """Start the daily task now (Windows), to check that it works."""
    if os.name != "nt":
        raise Abort("Only on Windows; elsewhere run the script written by schedule_monitor().")
    res = _schtasks(["/Run", "/TN", taskname])
    if res.returncode != 0:
        raise Abort(f"Could not start the task: {(res.stderr or res.stdout).strip()}")


def unschedule_monitor(taskname: str = "tidypptsdm_monitor", verbose: int = 1) -> None:
    """Remove the daily task registered by ``schedule_monitor()`` (Windows).

    On Linux and macOS, remove the line with ``crontab -e``.
    """
    with local_verbose(verbose):
        if os.name != "nt":
            msg("On Linux and macOS remove the line of the monitor with `crontab -e`.", "info")
            return
        res = _schtasks(["/Delete", "/F", "/TN", taskname])
        if res.returncode != 0:
            raise Abort(f"Could not remove the task: {(res.stderr or res.stdout).strip()}")
        msg(f"Task '{taskname}' removed", "success")
