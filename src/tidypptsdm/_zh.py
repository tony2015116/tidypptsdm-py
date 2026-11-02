"""The run as the desktop app and the scheduled task show it, in Chinese.

The command line and the Python functions keep the English messages, as in
the R package. The desktop app and the daily task write five steps (each
with its time), then a conclusion; errors say what to do. A log file in the
result folder keeps the runs, with the full error report for the maintainer.
"""

from __future__ import annotations

import datetime as _dt
import re
import time
import traceback
from pathlib import Path

from ._messages import Abort, capture
from ._version import __version__

LOG_NAME = "tidypptsdm.log"
LOG_MAX_BYTES = 1_000_000   # then the log is moved to tidypptsdm.log.1 (the one before is dropped)
MAX_LISTED = 10             # danger alerts listed one by one; the rest are counted
RULE = "━"
STEPS = ("读取数据", "整理数据", "计算监控", "作图", "写出结果")
NUM = "①②③④⑤"
# share of the progress bar at the start of each step (reading and plotting take longest)
START = (0.0, 0.25, 0.35, 0.45, 0.95)


# ---- where the lines go -------------------------------------------------------------------

class Sink:
    """Receives the lines of a run. ``tag``: head, step, ok, warn, bad or None."""

    def line(self, text: str, tag: str | None = None) -> None:
        raise NotImplementedError

    def progress(self, text: str, fraction: float) -> None:
        """A line that the next line replaces (only shown in the app)."""

    def detail(self, text: str) -> None:
        """Only for the log file (e.g. the full error report)."""


class FileSink(Sink):
    def __init__(self, stream):
        self.stream = stream

    def _write(self, text: str) -> None:
        if self.stream is None:
            return
        try:
            self.stream.write(text + "\n")
            self.stream.flush()
        except (OSError, ValueError, UnicodeError):
            pass

    def line(self, text: str, tag: str | None = None) -> None:
        self._write(text)

    def detail(self, text: str) -> None:
        self._write(text.rstrip("\n"))


class TeeSink(Sink):
    def __init__(self, *sinks: Sink):
        self.sinks = [s for s in sinks if s is not None]

    def line(self, text: str, tag: str | None = None) -> None:
        for s in self.sinks:
            s.line(text, tag)

    def progress(self, text: str, fraction: float) -> None:
        for s in self.sinks:
            s.progress(text, fraction)

    def detail(self, text: str) -> None:
        for s in self.sinks:
            s.detail(text)


class ListSink(Sink):
    """Collects the lines (for tests)."""

    def __init__(self):
        self.lines: list[tuple[str, str | None]] = []
        self.details: list[str] = []
        self.progresses: list[tuple[str, float]] = []

    def line(self, text: str, tag: str | None = None) -> None:
        self.lines.append((text, tag))

    def progress(self, text: str, fraction: float) -> None:
        self.progresses.append((text, fraction))

    def detail(self, text: str) -> None:
        self.details.append(text)

    @property
    def text(self) -> str:
        return "\n".join(t for t, _ in self.lines)


def open_log(folder):
    """Open ``folder/tidypptsdm.log`` to append (UTF-8). A log larger than
    1 MB is first renamed to ``tidypptsdm.log.1``. None if not possible."""
    try:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / LOG_NAME
        if log.exists() and log.stat().st_size > LOG_MAX_BYTES:
            log.replace(log.with_name(LOG_NAME + ".1"))
        return open(log, "a", encoding="utf-8")  # noqa: SIM115 - closed by the caller
    except OSError:
        return None


# ---- formatting -----------------------------------------------------------------------------

def _n(x, unit: str = "") -> str:
    """``9,794 条``, ``19.1 万条``."""
    x = int(x)
    return f"{x / 1e4:.1f} 万{unit}" if x >= 10000 else f"{x:,} {unit}".rstrip()


def _secs(s: float) -> str:
    if s < 1:
        return "不到 1 秒"
    s = round(s)
    return f"{s} 秒" if s < 60 else f"{s // 60} 分 {s % 60} 秒"


def _date(d) -> str:
    return f"{d:%Y-%m-%d}"


def _ids(x, n: int = MAX_LISTED) -> str:
    x = [str(i) for i in x]
    return "、".join(x[:n]) + (" 等" if len(x) > n else "")


def _width(text: str) -> int:
    return sum(2 if ord(c) >= 0x2E80 else 1 for c in text)


def _rule(text: str, width: int = 60) -> str:
    """``━━ text ━━━━…`` as wide as the other rules (Chinese characters count twice)."""
    return f"{RULE * 2} {text} " + RULE * max(4, (width - _width(text) - 4) // 2)


# ---- the messages of the package in Chinese ---------------------------------------------------

ARG_LABEL = {"days": "监控天数", "house_width": "栋号位数", "low_feed_kg": "低采食阈值",
             "max_unidentified_pct": "未识别报警", "max_feed_drop_pct": "采食下降报警",
             "iqr_k": "体重异常值系数", "end_date": "截止日期"}

# (pattern of the English error, Chinese text, what to do)
ERRORS = [
    (r"No files matching .* in (?P<folder>.+)\.$",
     "导出文件夹里没有 CSV、TXT 或 Excel 文件：{folder}",
     "请确认选的是测定站导出文件所在的文件夹（子文件夹里的文件也会读取）。"),
    (r"Cannot detect the station type",
     "从列名看不出是 NEDAP 还是 FIRE 的导出文件。",
     "请在“测定站类型”里选 NEDAP 或 FIRE；如果导出文件的列名改过，需要写一个格式文件（见网站“读取数据”）。"),
    (r"Field '(?P<field>[^']+)' \(column (?P<col>.+?)\) in (?P<file>.+?): cannot read (?P<n>\d+) value\(s\) "
     r"as time, e\.g\. (?P<ex>.+?)\. Give",
     "文件 {file} 的 {col} 列有 {n} 个值读不出时间，例如 {ex}",
     "请检查这个文件是否完整，是否在 Excel 里改过日期格式后保存过。"),
    (r"Field '(?P<field>[^']+)' in (?P<file>.+?) has values that are not numbers: (?P<ex>.+?)\. Check",
     "文件 {file} 的 {field} 列有不是数字的值，例如 {ex}",
     "请检查这个文件是否完整、各列是否错位。"),
    (r"(?P<file>.+?) has no column for required field\(s\): (?P<fields>\[.*?\])\.",
     "文件 {file} 缺少必需的列 {fields}",
     "请确认这是测定站导出的原始文件，并检查“测定站类型”是否选对。"),
    (r"(?P<file>.+?): \.xls files are not supported",
     "不支持旧版 Excel 文件（.xls）：{file}",
     "请在 Excel 里把它另存为 .xlsx 或 .csv，再删除 .xls 文件。"),
    (r"Cannot read (?P<file>.+?): ",
     "读不了文件 {file}",
     "文件可能已损坏，或正被其他程序占用。"),
    (r"File names must be unique: (?P<names>.+)\.$",
     "导出文件夹里有重名的文件：{names}",
     "子文件夹里的文件名也不能重复，请删除或改名重复的文件。"),
    (r"File\(s\) not found: \['?(?P<files>.+?)'?\]\.$",
     "找不到导出文件夹：{files}", "文件夹可能被移走或改名了，请重新选择导出文件夹。"),
    (r"`data` has no visits with a date",
     "导出文件里没有任何带日期的访问记录。", "请检查导出文件是否为空。"),
    (r"`end_date` must be a date",
     "截止日期的格式不对。", "请写成 2025-01-10 这样，或者留空。"),
    (r"`(?P<arg>\w+)` must be a (?:whole )?number of at least (?P<min>\S+), not",
     "设置“{label}”的值不对，应不小于 {min}。", "请在“设置”里改正。"),
]

# (pattern of an English note of the package, Chinese text); the stale-data
# note is left out: the conclusion says it
NOTES = [
    (r"Visit times with time zone (?P<tz>\S+) converted to (?P<to>.+?)(?: \(the time zone of this computer\))?$",
     "导出文件里的时间带时区标记（{tz}），已换算成{to_zh}后按天统计"),
    (r"(?P<n>[\d,]+) rows without entry time dropped", "删除了 {n} 行没有进站时间的记录"),
    (r"(?P<n>[\d,]+) duplicated rows dropped", "删除了 {n} 行完全重复的记录"),
    (r"(?P<n>[\d,]+) pigs? seen at several stations: (?P<a>\d+) moved between stations, (?P<b>\d+) "
     r"with misreads \((?P<c>\d+) visits kept as unidentified\)",
     "{n} 头猪出现在多台测定站：{a} 头转过栏，{b} 头有耳标误读（{c} 次访问记为未识别）"),
    (r"Pig (?P<pig>\S+) moves (?P<n>\d+) times between stations \((?P<path>.+)\)\. Are these",
     "猪 {pig} 在测定站之间来回 {n} 次（{path}），这几台测定站是不是在同一个栏？"),
    (r"No visits between (?P<a>\S+) and (?P<b>\S+)\.", "{a} 至 {b} 之间没有任何访问记录"),
    (r"Drawing on (?P<n>\d+) cores failed \((?P<why>.+)\); drawing",
     "多核作图失败（{why}），已改为一次画一台，报告不受影响"),
    (r"(?P<n>\d+) plot\(s\) could not be saved", "{n} 张图没能保存"),
    (r"Could not save (?P<f>.+?): (?P<why>.+)", "图 {name} 没能保存：{why}"),
]


def error_zh(text: str) -> tuple[str, str | None]:
    """Chinese text and what to do, for an error message of the package."""
    for pat, zh, todo in ERRORS:
        m = re.search(pat, text, re.S)
        if m:
            g = m.groupdict()
            if "arg" in g:
                g["label"] = ARG_LABEL.get(g["arg"], g["arg"])
            if "file" in g:
                g["file"] = Path(g["file"]).name
            return zh.format(**g), todo
    return text, None


def note_zh(text: str) -> str | None:
    """Chinese text for a note of the package; None for the others (the
    summary lines of the package, which the steps and the conclusion say in
    Chinese; they stay in the log file)."""
    for pat, zh in NOTES:
        m = re.search(pat, text)
        if m:
            g = m.groupdict()
            if "to" in g:
                g["to_zh"] = "北京时间" if g["to"] in ("UTC+08:00", "Asia/Shanghai") else g["to"]
            if "f" in g:
                g["name"] = Path(g["f"]).name
            return zh.format(**g)
    return None


# ---- the run ------------------------------------------------------------------------------------

def _conclusion(mon, w, looked_back: bool = False) -> list[tuple[str, str | None]]:
    from ._watch import alert_text
    s = mon.settings
    end = s["end_date"]
    a = w.alerts
    last = mon.stations[mon.stations["date"] == end]
    out = [(f"{_date(end)}：{len(last)} 台测定站，{int(last['n_pigs'].sum()):,} 头猪来吃过料，"
            f"{_n(last['n_visits'].sum(), '次')}访问，采食 {float(last['feed_kg'].sum()):,.1f} kg", None)]
    if w.end_note:
        out.append((f"ℹ {w.end_note}", None))
    danger = a[a["level"] == "danger"]
    warning = a[a["level"] == "warning"]
    absent = a[a["level"] == "absent"]
    if len(danger) + len(warning) == 0:
        out.append(("✓ 没有警报", "ok"))
    if len(danger):
        n_new = sum(int(r["days"]) <= 1 for _, r in danger.iterrows())
        out.append((f"✗ 严重 {len(danger)} 条（新 {n_new} 条）：", "bad"))
        for _, r in danger.head(MAX_LISTED).iterrows():
            out.append(("   · " + alert_text(r), "bad"))
        if len(danger) > MAX_LISTED:
            out.append((f"   · 另有 {len(danger) - MAX_LISTED} 条，见报告首页", "bad"))
    if len(warning):
        parts = []
        for typ, word in (("station_gap", "长时间没有记录"), ("unidentified", "未识别过多"),
                          ("feed_drop", "头均采食下降")):
            x = warning.loc[warning["type"] == typ, "location"]
            if len(x):
                parts.append(f"{word} {len(x)} 台（{_ids(x)}）")
        for typ, word in (("pig_low_feed", "低采食"), ("pig_feed_drop", "采食骤降")):
            n = int((warning["type"] == typ).sum())
            if n:
                parts.append(f"{word} {n} 头")
        out.append((f"⚠ 警告 {len(warning)} 条：" + "，".join(parts) + "。明细见报告首页的“今日待办”", "warn"))
    if len(absent):
        out.append((f"ℹ 长期未访问 {len(absent)} 头（{_ids(absent['responder'])}）："
                    "如果已离场，把耳标号写进结果文件夹里的“离场猪.txt”，就不再报警", None))
    if w.removed:
        out.append((f"ℹ 离场名单上有 {len(w.removed)} 头猪，其中 {w.removed_found} 头在本次数据中，已不报警", None))
    if w.behind_days > 1 and not looked_back:
        out.append((f"⚠ 最新数据是 {w.behind_days} 天前（{_date(s['data_last_date'])}）的。"
                    "如果是每天的监控，请检查测定站的导出文件是否更新。", "warn"))
    return out


def run_zh(data, out_dir, sink: Sink, format: str = "xlsx", workers: int | None = None,
           station: str | None = None, time_zone: str = "local", pig_drop_pct: float = 50,
           **monitor_args) -> dict | None:
    """Run the monitor as ``monitor_to_folder()`` does and write the run in
    Chinese to ``sink``. Returns the same dict, or None when it failed (the
    reason is in the lines)."""
    from ._monitor import run_monitor
    from ._prep import prep_visits
    from ._report import _n_workers
    from ._report_zh import write_report_zh
    from ._watch import alerts_table, choose_end_date, read_removed, watch
    from ._station import read_station, resolve_files
    from ._tables import write_monitor_tables

    t_all = time.perf_counter()
    sink.line(_rule(f"{_dt.datetime.now():%Y-%m-%d %H:%M} 开始（tidypptsdm {__version__}）"), "head")
    step = 0
    t = time.perf_counter()

    def begin(i: int, text: str = "") -> None:
        nonlocal step, t
        step, t = i, time.perf_counter()
        sink.progress(f"{NUM[i]} {STEPS[i]}…{text}", START[i])

    def done(detail: str) -> None:
        sink.line(f"{NUM[step]} {STEPS[step]}：{detail} · {_secs(time.perf_counter() - t)}", "step")

    try:
        with capture() as notes:
            begin(0)
            files = resolve_files(data)
            raw = read_station(files, station=station, time_zone=time_zone, verbose=0)
            done(f"{len(files)} 个文件，{_n(len(raw), '条')}记录（{raw.attrs['station'].upper()}）")

            begin(1)
            v = prep_visits(raw, verbose=0)
            del raw
            ident = v["identified"]
            n_days = (v["date"].max() - v["date"].min()).days + 1 if len(v) else 0
            done(f"{v.loc[ident, 'responder'].nunique():,} 头猪，{v['location'].nunique()} 台测定站，"
                 f"{n_days} 天；{100 * (~ident).mean() if len(v) else 0:.1f}% 的访问没读到耳标")

            begin(2)
            looked_back = monitor_args.get("end_date") is not None
            end, end_note = choose_end_date(v, monitor_args.get("end_date"))
            if end is not None and not looked_back:
                monitor_args["end_date"] = end
            mon = run_monitor(v, verbose=0, **monitor_args)
            del v
            s = mon.settings
            w = watch(mon, removed=read_removed(out_dir), pig_drop_pct=pig_drop_pct, end_note=end_note)
            done(f"{_date(s['start_date'])} 至 {_date(s['end_date'])}，{s['days']} 天"
                 + ("（按截止日期回看）" if looked_back else "（最后一天不完整，用前一天）" if end_note else ""))

            n_locs = mon.stations["location"].nunique()
            n_w = _n_workers(workers, n_locs)
            how = f"，{n_w} 核同时画" if n_w > 1 else ""
            begin(3, f"0/{n_locs} 台测定站")

            def plotted(k: int, total: int) -> None:
                sink.progress(f"{NUM[3]} {STEPS[3]}…{k}/{total} 台测定站{how}",
                              START[3] + (START[4] - START[3]) * k / max(total, 1))

            folder = Path(out_dir) / _date(s["end_date"])
            report = write_report_zh(mon, w, folder, workers=workers, progress=plotted,
                                     looked_back=looked_back)
            done(f"{n_locs} 台测定站，每台 4 张图{how}")

            begin(4)
            from dataclasses import replace
            tables = write_monitor_tables(replace(mon, alerts=alerts_table(w)), folder, format=format,
                                          verbose=0)
            done("报告和 Excel 工作簿已保存" if format == "xlsx"
                 else f"报告和 {len(tables)} 个 CSV 文件已保存")
    except Abort as e:
        text, todo = error_zh(str(e))
        sink.line(f"✗ 没有完成（{NUM[step]} {STEPS[step]}）：{text}", "bad")
        if todo:
            sink.line(f"   怎么办：{todo}", None)
        sink.detail(f"   原文：{e}")
        return None
    except PermissionError as e:
        sink.line(f"✗ 没有完成（{NUM[step]} {STEPS[step]}）：文件被占用或没有写入权限："
                  f"{e.filename or e}", "bad")
        sink.line("   怎么办：如果报告或 Excel 正在打开，请先关闭再运行；或换一个结果文件夹。", None)
        sink.detail(traceback.format_exc())
        return None
    except Exception as e:  # noqa: BLE001 - anything else: say so, keep the details in the log
        sink.line(f"✗ 没有完成（{NUM[step]} {STEPS[step]}）：程序出错：{type(e).__name__}: {e}", "bad")
        sink.line(f"   怎么办：请把结果文件夹里的 {LOG_NAME} 发给维护者。", None)
        sink.detail(traceback.format_exc())
        return None

    sink.line(_rule("结论"), "head")
    for text, tag in _conclusion(mon, w, looked_back):
        sink.line(text, tag)
    shown = set()
    for kind, text in notes:
        zh = note_zh(text)
        if zh and zh not in shown:
            shown.add(zh)
            sink.line(f"ℹ {zh}", "warn" if kind in ("warning", "danger") else None)
        elif zh is None and kind in ("warning", "danger") and not re.match(r"\d+ alerts?:", text):
            sink.detail(f"   ({kind}) {text}")
    sink.line(f"共用时 {_secs(time.perf_counter() - t_all)}。报告：{report.resolve()}", None)
    sink.progress("", 1.0)
    return {"monitor": mon, "watch": w, "folder": folder, "report": report, "tables": tables}
