"""Desktop app: choose the export folder, set the window, run, open the report,
and schedule the monitor every day. Labels are in Chinese."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

from ._version import __version__

SETTINGS_FILE = Path.home() / ".tidypptsdm.json"


DEFAULTS = {
    "data": "", "out": "", "days": 7, "house_width": 1, "low_feed_kg": 0.5,
    "max_unidentified_pct": 5.0, "max_feed_drop_pct": 30.0, "pig_drop_pct": 50.0, "station": "自动识别",
    "format": "xlsx", "time": "07:30", "end_date": "",
}



STATION_CHOICES = {"自动识别": None, "NEDAP": "nedap", "FIRE": "fire"}


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return s


def save_settings(s: dict) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def open_path(p: Path) -> None:
    """Open a file or folder with the program the system uses for it."""
    if sys.platform.startswith("win"):
        os.startfile(str(p))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


class _QueueSink:
    """Lines of a run (see _zh.run_zh) for the log box, through the queue."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def line(self, text: str, tag: str | None = None) -> None:
        self.q.put(("line", text, tag))

    def progress(self, text: str, fraction: float) -> None:
        self.q.put(("progress", text, fraction))

    def detail(self, text: str) -> None:
        pass  # only in the log file


class _QueueWriter:
    """File-like object that sends the messages of the package to the log box."""

    def __init__(self, q: queue.Queue):
        self.q = q
        self.encoding = "utf-8"

    def write(self, text: str) -> int:
        if text:
            self.q.put(text)
        return len(text)

    def flush(self) -> None:
        pass


class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.last_report: Path | None = None
        self.last_folder: Path | None = None
        self.busy = False
        s = load_settings()

        root.title(f"tidypptsdm {__version__} - 测定站日常监控")
        root.minsize(760, 640)
        try:
            ttk.Style().theme_use("vista" if sys.platform.startswith("win") else "clam")
        except tk.TclError:
            pass
        pad = dict(padx=6, pady=4)
        main = ttk.Frame(root, padding=10)
        main.pack(fill="both", expand=True)

        # ---- folders
        f_data = ttk.LabelFrame(main, text="数据", padding=8)
        f_data.pack(fill="x")
        self.v_data = tk.StringVar(value=s["data"])
        self.v_out = tk.StringVar(value=s["out"])
        for row, (label, var, tip) in enumerate([
            ("导出文件夹", self.v_data, "测定站导出的 CSV / TXT / Excel 文件所在的文件夹（含子文件夹）"),
            ("结果文件夹", self.v_out, "报告和表格写到这里，每天一个子文件夹"),
        ]):
            ttk.Label(f_data, text=label).grid(row=row, column=0, sticky="w", **pad)
            ttk.Entry(f_data, textvariable=var).grid(row=row, column=1, sticky="ew", **pad)
            ttk.Button(f_data, text="浏览…", command=lambda v=var: self._browse(v)).grid(row=row, column=2, **pad)
            ttk.Label(f_data, text=tip, foreground="#667085").grid(row=row, column=3, sticky="w", **pad)
        f_data.columnconfigure(1, weight=1)

        # ---- settings
        f_set = ttk.LabelFrame(main, text="设置", padding=8)
        f_set.pack(fill="x", pady=(8, 0))
        self.v_days = tk.StringVar(value=str(s["days"]))
        self.v_house = tk.StringVar(value=str(s["house_width"]))
        self.v_low = tk.StringVar(value=str(s["low_feed_kg"]))
        self.v_unid = tk.StringVar(value=str(s["max_unidentified_pct"]))
        self.v_drop = tk.StringVar(value=str(s["max_feed_drop_pct"]))
        self.v_pigdrop = tk.StringVar(value=str(s.get("pig_drop_pct", 50.0)))
        self.v_station = tk.StringVar(value=s["station"])
        self.v_format = tk.StringVar(value=s["format"])

        self.v_end = tk.StringVar(value=s.get("end_date", ""))
        fields = [
            ("监控天数", self.v_days, "天"), ("栋号位数", self.v_house, "测定站编号前几位是栋号"),
            ("低采食阈值", self.v_low, "kg/天"), ("未识别报警", self.v_unid, "%"),
            ("站采食下降报警", self.v_drop, "% (头均，比前几天平均)"),
            ("个体采食骤降", self.v_pigdrop, "% (比这头猪前几天平均；0 = 不检查)"),
        ]
        for i, (label, var, unit) in enumerate(fields):
            r, c = divmod(i, 2)
            ttk.Label(f_set, text=label).grid(row=r, column=c * 3, sticky="w", **pad)
            ttk.Entry(f_set, textvariable=var, width=8).grid(row=r, column=c * 3 + 1, sticky="w", **pad)
            ttk.Label(f_set, text=unit, foreground="#667085").grid(row=r, column=c * 3 + 2, sticky="w", **pad)
        ttk.Label(f_set, text="测定站类型").grid(row=3, column=3, sticky="w", **pad)
        ttk.Combobox(f_set, textvariable=self.v_station, values=list(STATION_CHOICES), width=8,
                     state="readonly").grid(row=3, column=4, sticky="w", **pad)
        ttk.Button(f_set, text="离场猪名单…", command=self.edit_removed).grid(row=5, column=0, columnspan=2,
                                                                         sticky="w", **pad)
        ttk.Label(f_set, text="死亡、淘汰或转出的猪：写进名单后不再报警（名单在结果文件夹里）",
                  foreground="#667085").grid(row=5, column=2, columnspan=4, sticky="w", **pad)
        ttk.Label(f_set, text="截止日期").grid(row=4, column=0, sticky="w", **pad)
        ttk.Entry(f_set, textvariable=self.v_end, width=12).grid(row=4, column=1, sticky="w", **pad)
        ttk.Label(f_set, text="留空 = 数据的最后一天；回看历史时填，如 2025-01-10",
                  foreground="#667085").grid(row=4, column=2, columnspan=4, sticky="w", **pad)
        ttk.Label(f_set, text="表格格式").grid(row=3, column=0, sticky="w", **pad)
        fm = ttk.Frame(f_set)
        fm.grid(row=3, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(fm, text="Excel", value="xlsx", variable=self.v_format).pack(side="left")
        ttk.Radiobutton(fm, text="CSV", value="csv", variable=self.v_format).pack(side="left", padx=8)

        # ---- actions
        f_act = ttk.Frame(main)
        f_act.pack(fill="x", pady=(10, 0))
        self.b_run = ttk.Button(f_act, text="▶ 运行监控", command=self.run)
        self.b_run.pack(side="left")
        self.b_report = ttk.Button(f_act, text="打开报告", command=self.open_report, state="disabled")
        self.b_report.pack(side="left", padx=6)
        self.b_folder = ttk.Button(f_act, text="打开结果文件夹", command=self.open_folder, state="disabled")
        self.b_folder.pack(side="left")
        ttk.Button(f_act, text="用示例数据试一下", command=self.try_example).pack(side="right")

        # ---- schedule
        f_sch = ttk.LabelFrame(main, text="每天定时运行", padding=8)
        f_sch.pack(fill="x", pady=(10, 0))
        self.v_time = tk.StringVar(value=s["time"])
        ttk.Label(f_sch, text="时间").pack(side="left")
        ttk.Entry(f_sch, textvariable=self.v_time, width=7).pack(side="left", padx=6)
        ttk.Button(f_sch, text="设为每天定时", command=self.schedule).pack(side="left")
        ttk.Button(f_sch, text="取消定时", command=self.unschedule).pack(side="left", padx=6)
        ttk.Button(f_sch, text="查看定时状态", command=self.task_status).pack(side="left")
        ttk.Button(f_sch, text="立即运行一次", command=self.task_run_now).pack(side="left", padx=6)
        ttk.Label(f_sch, text="关闭本程序后照常运行", foreground="#667085").pack(side="left", padx=6)

        # ---- log
        f_log = ttk.LabelFrame(main, text="运行信息", padding=4)
        f_log.pack(fill="both", expand=True, pady=(10, 0))
        self.log = tk.Text(f_log, height=12, wrap="word", font=("Consolas", 9) if sys.platform.startswith("win")
                           else ("DejaVu Sans Mono", 9), state="disabled", background="#FAFAFA")
        sb = ttk.Scrollbar(f_log, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log.tag_configure("warn", foreground="#A15C00")
        self.log.tag_configure("bad", foreground="#B42318")
        self.log.tag_configure("ok", foreground="#1A7F4B")
        self.log.tag_configure("head", font=("TkDefaultFont", 9, "bold"))
        self.log.tag_configure("step", foreground="#344054")
        self.log.tag_configure("prog", foreground="#667085")
        self.log.mark_set("prog", "end")
        self.log.mark_gravity("prog", "left")
        self.in_progress = False
        f_st = ttk.Frame(main)
        f_st.pack(fill="x", pady=(6, 0))
        ttk.Style().configure("Run.Horizontal.TProgressbar", background="#1A7F4B")  # Windows: native green
        self.bar = ttk.Progressbar(f_st, mode="determinate", maximum=1.0, length=160,
                                   style="Run.Horizontal.TProgressbar")
        self.bar.pack(side="right")
        self.status = tk.StringVar(value="选择导出文件夹和结果文件夹，然后点“运行监控”。")
        ttk.Label(f_st, textvariable=self.status, foreground="#667085").pack(side="left", fill="x")
        root.after(100, self._poll)

    # ---- helpers
    def _browse(self, var) -> None:
        from tkinter import filedialog
        d = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
        if d:
            var.set(d)

    def _drop_progress(self) -> None:
        if self.in_progress:
            self.log.delete("prog", "end-1c")
            self.in_progress = False

    def _line(self, text: str, tag: str | None) -> None:
        self.log.configure(state="normal")
        self._drop_progress()
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _progress(self, text: str, fraction: float) -> None:
        self.bar["value"] = fraction
        self.log.configure(state="normal")
        self._drop_progress()
        if text:
            self.log.mark_set("prog", "end-1c")
            self.log.insert("end", text, "prog")
            self.in_progress = True
        self.log.see("end")
        self.log.configure(state="disabled")

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self._drop_progress()
        for line in text.splitlines(keepends=True):
            s = line.lstrip()
            tag = ("bad" if s.startswith(("x ", "✗")) else "warn" if s.startswith(("! ", "⚠"))
                   else "ok" if s.startswith(("v ", "✓")) else "head" if s.startswith(("-- ", "━━"))
                   else None)
            self.log.insert("end", line, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple) and item[0] == "line":
                    self._line(item[1], item[2])
                elif isinstance(item, tuple) and item[0] == "progress":
                    self._progress(item[1], item[2])
                elif isinstance(item, tuple):
                    self._done(*item[1:])
                else:
                    self._append(item)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _settings(self) -> dict:
        from ._messages import Abort
        try:
            s = {
                "data": self.v_data.get().strip(), "out": self.v_out.get().strip(),
                "days": int(self.v_days.get()), "house_width": int(self.v_house.get()),
                "low_feed_kg": float(self.v_low.get()), "max_unidentified_pct": float(self.v_unid.get()),
                "max_feed_drop_pct": float(self.v_drop.get()), "pig_drop_pct": float(self.v_pigdrop.get()),
                "station": self.v_station.get(),
                "format": self.v_format.get(), "time": self.v_time.get().strip(),
                "end_date": self.v_end.get().strip(),
            }
        except ValueError as e:
            raise Abort("天数、栋号位数和各阈值必须是数字。") from e
        if not s["data"] or not Path(s["data"]).is_dir():
            raise Abort("请选择导出文件夹。")
        if not s["out"]:
            raise Abort("请选择结果文件夹。")
        if not 0 <= s["pig_drop_pct"] < 100:
            raise Abort("个体采食骤降请填 0 到 100 之间的数（0 = 不检查）。")
        if s["end_date"]:
            import re as _re
            if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", s["end_date"]):
                raise Abort("截止日期请写成 2025-01-10 这样的格式，或者留空。")
        return s

    @staticmethod
    def _monitor_args(s: dict) -> dict:
        return dict(days=s["days"], house_width=s["house_width"], low_feed_kg=s["low_feed_kg"],
                    max_unidentified_pct=s["max_unidentified_pct"], max_feed_drop_pct=s["max_feed_drop_pct"],
                    station=STATION_CHOICES.get(s["station"]), pig_drop_pct=s["pig_drop_pct"],
                    # times written with a time zone (…Z) are shown in Beijing time;
                    # ordinary exports have none and are taken as they are
                    time_zone="+08:00")

    def _error(self, text: str) -> None:
        from tkinter import messagebox
        messagebox.showerror("tidypptsdm", text)

    # ---- actions
    def run(self) -> None:
        from ._messages import Abort
        if self.busy:
            return
        try:
            s = self._settings()
        except Abort as e:
            self._error(str(e))
            return
        save_settings(s)
        self.busy = True
        self.b_run.configure(state="disabled")
        self.status.set("正在运行…")
        self.bar["value"] = 0
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.in_progress = False
        self.log.configure(state="disabled")
        threading.Thread(target=self._work, args=(s,), daemon=True).start()

    def _work(self, s: dict) -> None:
        from ._zh import FileSink, TeeSink, open_log, run_zh
        log = open_log(s["out"])  # manual runs are kept in the log too
        sink = TeeSink(_QueueSink(self.q), FileSink(log) if log else None)
        res = None
        try:
            res = run_zh(s["data"], s["out"], sink, format=s["format"],
                         end_date=s["end_date"] or None, **self._monitor_args(s))
        except Exception:  # noqa: BLE001 - never leave the app hanging
            sink.line("✗ 程序出错，详细信息已写入结果文件夹里的 tidypptsdm.log。", "bad")
            sink.detail(traceback.format_exc())
        finally:
            if log:
                log.write("\n")
                log.close()
        if res is None:
            self.q.put(("done", False, None, None, 0, 0))
        else:
            a = res["watch"].alerts
            a = a[a["level"] != "absent"]
            self.q.put(("done", True, res["report"], res["folder"], len(a),
                        int((a["level"] == "danger").sum())))

    def _done(self, ok: bool, report, folder, n_alerts: int, n_danger: int) -> None:
        self.busy = False
        self.b_run.configure(state="normal")
        if not ok:
            self.bar["value"] = 0
            self.status.set("没有完成，原因和处理办法见运行信息。")
            return
        self.last_report, self.last_folder = Path(report), Path(folder)
        self.b_report.configure(state="normal")
        self.b_folder.configure(state="normal")
        self.status.set(f"完成：{n_alerts} 条警报（{n_danger} 条严重）。报告已在浏览器中打开。")
        self.open_report()

    def edit_removed(self) -> None:
        from ._watch import ensure_removed_file
        out = self.v_out.get().strip()
        if not out:
            self._error("请先选择结果文件夹：离场猪名单保存在结果文件夹里。")
            return
        try:
            f = ensure_removed_file(out)
        except OSError as e:
            self._error(f"无法创建离场猪名单：{e}")
            return
        open_path(f)
        self.status.set(f"在记事本里每行写一个耳标号，保存后下次运行生效：{f}")

    def open_report(self) -> None:
        if self.last_report and self.last_report.exists():
            webbrowser.open(self.last_report.resolve().as_uri())

    def open_folder(self) -> None:
        if self.last_folder and self.last_folder.exists():
            open_path(self.last_folder)

    def try_example(self) -> None:
        from .datasets import write_example
        base = Path.home() / "tidypptsdm_example"
        write_example(base / "exports", "nedap")
        self.v_data.set(str(base / "exports"))
        self.v_out.set(str(base / "results"))
        self.status.set(f"示例数据已写到 {base / 'exports'}，点“运行监控”试一下。")

    def schedule(self) -> None:
        from tkinter import messagebox

        from ._messages import Abort
        from ._schedule import schedule_monitor
        try:
            s = self._settings()
            save_settings(s)
            sys_err = sys.stderr
            sys.stderr = _QueueWriter(self.q)
            try:
                script = schedule_monitor(s["data"], s["out"], time=s["time"], format=s["format"],
                                          **self._monitor_args(s))
            finally:
                sys.stderr = sys_err
        except Abort as e:
            self._error(str(e))
            return
        if os.name == "nt":
            messagebox.showinfo("tidypptsdm", f"已设为每天 {s['time']} 自动运行，关闭本程序后照常运行。\n\n"
                                f"报告写到：{s['out']}\\<数据最后一天的日期>\n"
                                f"运行日志：{s['out']}\\tidypptsdm.log\n\n"
                                "到时电脑需要开着并已登录（可以锁屏）；如果当时关机或睡眠，开机后会补跑一次。"
                                "用电池时也会运行。\n\n"
                                "可以点“立即运行一次”检查；点“查看定时状态”看上次运行的时间和结果。")
        else:
            messagebox.showinfo("tidypptsdm", f"脚本已写到 {script}。\n请用 crontab -e 加入运行信息中的那一行。")

    def task_status(self) -> None:
        from ._schedule import task_status
        text = task_status(out_dir=self.v_out.get().strip() or None)
        self._append("\n━━ 定时任务状态 ━━\n" + text + "\n")
        self.status.set("“上次结果”为 0 表示成功；日志的最后几行见运行信息。")

    def task_run_now(self) -> None:
        from tkinter import messagebox

        from ._messages import Abort
        from ._schedule import run_task_now
        try:
            run_task_now()
        except Abort as e:
            self._error(str(e) + "\n\n请先点“设为每天定时”。")
            return
        messagebox.showinfo("tidypptsdm", "已在后台启动定时任务（不会弹出窗口）。\n\n"
                            "数据多时需要一两分钟；完成后点“查看定时状态”，"
                            "日志最后应有“结论”和“共用时 … 报告：…”。")

    def unschedule(self) -> None:
        from tkinter import messagebox

        from ._messages import Abort
        from ._schedule import unschedule_monitor
        try:
            unschedule_monitor()
        except Abort as e:
            self._error(str(e))
            return
        if os.name == "nt":
            messagebox.showinfo("tidypptsdm", "已取消每天定时运行。")


def main() -> None:
    from ._tkcheck import diagnose, setup_tcl_tk, show_error
    setup_tcl_tk()
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        ok, lines = diagnose()
        report = Path.home() / "tidypptsdm-selftest.txt"
        try:
            report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass
        show_error("tidypptsdm", "无法打开程序窗口（Tk 图形界面库启动失败）。\n\n"
                   "请确认解压了整个 zip 文件夹，并且杀毒软件没有删除 _internal 文件夹里的文件；"
                   "然后重新解压一次再试。\n\n"
                   f"诊断信息已保存到：{report}\n请把这个文件发给维护者。\n\n" + "\n".join(lines[-8:]))
        return
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
