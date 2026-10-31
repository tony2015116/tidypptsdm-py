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
    "max_unidentified_pct": 5.0, "max_feed_drop_pct": 30.0, "station": "自动识别",
    "format": "xlsx", "time": "07:30", "time_zone": "本地（自动换算）",
}

TZ_CHOICES = {"本地（自动换算）": "local", "UTC（不换算）": "UTC"}

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
        root.minsize(720, 560)
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
        self.v_station = tk.StringVar(value=s["station"])
        self.v_format = tk.StringVar(value=s["format"])
        self.v_tz = tk.StringVar(value=s.get("time_zone", DEFAULTS["time_zone"]))
        fields = [
            ("监控天数", self.v_days, "天"), ("栋号位数", self.v_house, "测定站编号前几位是栋号"),
            ("低采食阈值", self.v_low, "kg/天"), ("未识别报警", self.v_unid, "%"),
            ("采食下降报警", self.v_drop, "% (比前几天平均)"),
        ]
        for i, (label, var, unit) in enumerate(fields):
            r, c = divmod(i, 2)
            ttk.Label(f_set, text=label).grid(row=r, column=c * 3, sticky="w", **pad)
            ttk.Entry(f_set, textvariable=var, width=8).grid(row=r, column=c * 3 + 1, sticky="w", **pad)
            ttk.Label(f_set, text=unit, foreground="#667085").grid(row=r, column=c * 3 + 2, sticky="w", **pad)
        ttk.Label(f_set, text="测定站类型").grid(row=2, column=3, sticky="w", **pad)
        ttk.Combobox(f_set, textvariable=self.v_station, values=list(STATION_CHOICES), width=8,
                     state="readonly").grid(row=2, column=4, sticky="w", **pad)
        ttk.Label(f_set, text="带时区的时间").grid(row=3, column=3, sticky="w", **pad)
        ttk.Combobox(f_set, textvariable=self.v_tz, values=list(TZ_CHOICES), width=16,
                     state="readonly").grid(row=3, column=4, columnspan=2, sticky="w", **pad)
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
        self.status = tk.StringVar(value="选择导出文件夹和结果文件夹，然后点“运行监控”。")
        ttk.Label(main, textvariable=self.status, foreground="#667085").pack(fill="x", pady=(6, 0))
        root.after(100, self._poll)

    # ---- helpers
    def _browse(self, var) -> None:
        from tkinter import filedialog
        d = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
        if d:
            var.set(d)

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        for line in text.splitlines(keepends=True):
            s = line.lstrip()
            tag = ("bad" if s.startswith("x ") else "warn" if s.startswith("! ")
                   else "ok" if s.startswith("v ") else "head" if s.startswith("-- ") else None)
            self.log.insert("end", line, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple):
                    self._done(*item)
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
                "max_feed_drop_pct": float(self.v_drop.get()), "station": self.v_station.get(),
                "format": self.v_format.get(), "time": self.v_time.get().strip(),
                "time_zone": self.v_tz.get(),
            }
        except ValueError as e:
            raise Abort("天数、栋号位数和各阈值必须是数字。") from e
        if not s["data"] or not Path(s["data"]).is_dir():
            raise Abort("请选择导出文件夹。")
        if not s["out"]:
            raise Abort("请选择结果文件夹。")
        return s

    @staticmethod
    def _monitor_args(s: dict) -> dict:
        return dict(days=s["days"], house_width=s["house_width"], low_feed_kg=s["low_feed_kg"],
                    max_unidentified_pct=s["max_unidentified_pct"], max_feed_drop_pct=s["max_feed_drop_pct"],
                    station=STATION_CHOICES.get(s["station"]),
                    time_zone=TZ_CHOICES.get(s["time_zone"], "local"))

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
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        threading.Thread(target=self._work, args=(s,), daemon=True).start()

    def _work(self, s: dict) -> None:
        from ._messages import Abort
        from ._schedule import monitor_to_folder
        old = sys.stderr
        sys.stderr = _QueueWriter(self.q)
        try:
            res = monitor_to_folder(s["data"], s["out"], format=s["format"], **self._monitor_args(s))
            a = res["monitor"].alerts
            self.q.put((True, res["report"], res["folder"], len(a), int((a["level"] == "danger").sum())))
        except Abort as e:
            self.q.put(f"x {e}\n")
            self.q.put((False, None, None, 0, 0))
        except Exception:  # noqa: BLE001 - show anything in the log
            self.q.put("x " + traceback.format_exc())
            self.q.put((False, None, None, 0, 0))
        finally:
            sys.stderr = old

    def _done(self, ok: bool, report, folder, n_alerts: int, n_danger: int) -> None:
        self.busy = False
        self.b_run.configure(state="normal")
        if not ok:
            self.status.set("没有完成，原因见运行信息。")
            return
        self.last_report, self.last_folder = Path(report), Path(folder)
        self.b_report.configure(state="normal")
        self.b_folder.configure(state="normal")
        self.status.set(f"完成：{n_alerts} 条警报（{n_danger} 条严重）。报告在 {folder}")
        self.open_report()

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
        self._append("\n-- 定时任务状态 --\n" + text + "\n")
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
                            "日志最后应有 “Report … written to …”。")

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
