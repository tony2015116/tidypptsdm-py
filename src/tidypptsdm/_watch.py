"""Alerts of the desktop app (exe) and of its daily task.

The functions of the package (and the R package) keep their alerts. The
desktop app is read every morning by the people in the barn, so it adds:

* an incomplete last day (data exported during the day) is not monitored:
  the day before is;
* a station that stopped recording during the day is one alert, not one
  alert per pig;
* each alert says whether it is new or since how many days it lasts; pigs
  that have not come for more than ``gone_days`` days are listed apart
  ("long absent": dead, culled or moved?), and pigs on the list of removed
  pigs are left out;
* a pig that eats much less than on its own earlier days is an alert
  (``pig_drop_pct``), and the feed drop of a station compares the feed per
  pig, so that fewer pigs do not look like a drop.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ._monitor import Monitor, natural_order

REMOVED_FILE = "离场猪.txt"
LAST_DAY_UNTIL = 22        # hour: a last day whose data end earlier is incomplete
STOP_HOURS = 4.0           # a station silent this long (and longer than usual) stopped
GONE_DAYS = 3              # pigs absent longer than this are listed apart
PIG_DROP_PCT = 50.0
PIG_DROP_MIN_KG = 1.0      # pigs that ate less than this before are not checked for a drop
PIG_DROP_DAYS = 5          # earlier days that make a pig's usual feed intake

LEVELS = ("danger", "warning", "absent")
TYPES = ("station_down", "station_stopped", "station_gap", "unidentified", "feed_drop",
         "pig_no_visit", "pig_low_feed", "pig_feed_drop", "pig_absent")
COLS = ["level", "type", "location", "responder", "value", "days", "message"]
TYPE_ZH = {"station_down": "全天没有访问", "station_stopped": "中途停止记录", "station_gap": "长时间没有记录",
           "unidentified": "未识别过多", "feed_drop": "头均采食下降", "pig_no_visit": "没有访问",
           "pig_low_feed": "低采食", "pig_feed_drop": "采食骤降", "pig_absent": "长期未访问"}
LEVEL_ZH = {"danger": "严重", "warning": "警告", "absent": "待确认"}

TEMPLATE = """# 离场猪名单：已经死亡、淘汰或转出测定栏的猪
# 每行一个耳标号，后面可以写日期和原因，例如：
# 414707  2025-11-20 淘汰
# 名单上的猪不再报警。以 # 开头的行不读取。
"""


@dataclass
class Watch:
    """The alerts of the app and what the run noticed."""
    alerts: pd.DataFrame
    end_note: str = ""                    # incomplete last day: why the day before is shown
    behind_days: int = 0                  # days between the last data and today
    removed: set[str] = field(default_factory=set)
    removed_found: int = 0                # removed pigs that are in the data of the window
    affected: dict = field(default_factory=dict)   # stopped/down station -> pigs on it
    pig_drop_pct: float = PIG_DROP_PCT

    def pig_status(self, mon: Monitor) -> dict:
        """Status of each pig for the pig tables of the report."""
        st = {r: s for r, s in zip(mon.pig_summary["responder"], mon.pig_summary["status"])}
        for _, a in self.alerts[self.alerts["responder"].notna()].iterrows():
            st[a["responder"]] = {"pig_no_visit": "no_visit", "pig_low_feed": "low_feed",
                                  "pig_feed_drop": "feed_drop", "pig_absent": "absent"}[a["type"]]
        silent = set(self.affected)
        for r, loc in zip(mon.pig_summary["responder"], mon.pig_summary["location"]):
            if loc in silent and r in st and st[r] != "ok":
                st[r] = "station_off"
        for r in self.removed:
            if r in st:
                st[r] = "removed"
        return st


# ---- removed pigs -------------------------------------------------------------------------------

def removed_file(out_dir) -> Path:
    return Path(out_dir) / REMOVED_FILE


def read_removed(out_dir) -> set[str]:
    """Ear tags in ``<out_dir>/离场猪.txt`` (first word of each line; ``#`` starts a comment)."""
    f = removed_file(out_dir)
    if not f.exists():
        return set()
    try:
        text = f.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = f.read_text(encoding="gb18030")
    out = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(re.split(r"[\s,，;；\t]+", line)[0])
    return out


def ensure_removed_file(out_dir) -> Path:
    f = removed_file(out_dir)
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(TEMPLATE, encoding="utf-8-sig")
    return f


# ---- the day to monitor -----------------------------------------------------------------------

def choose_end_date(v: pd.DataFrame, end_date=None) -> tuple[pd.Timestamp | None, str]:
    """The last day to monitor and, when it is not the last day of the data,
    why. A given ``end_date`` is kept (looking back)."""
    if end_date is not None or len(v) == 0:
        return end_date, ""
    last = v["date"].max()
    today = pd.Timestamp(_dt.date.today())
    if last >= today:
        return None, ""            # the package takes yesterday
    t = v.loc[v["date"] == last, "entry_time"].max()
    if pd.notna(t) and t.hour < LAST_DAY_UNTIL and last - pd.Timedelta(days=1) >= v["date"].min():
        end = last - pd.Timedelta(days=1)
        return end, (f"数据的最后一天 {last:%Y-%m-%d} 只到 {t:%H:%M}（导出时这一天还没结束），"
                     f"所以监控到前一天 {end:%Y-%m-%d}")
    return None, ""


# ---- helpers ----------------------------------------------------------------------------------

def _run_length(flags: pd.Series) -> int:
    """Days in a row at the end of ``flags`` (sorted by date) that are True."""
    n = 0
    for f in reversed(flags.tolist()):
        if not f:
            break
        n += 1
    return n


def _gaps(times: pd.Series, day: pd.Timestamp) -> tuple[float, pd.Timestamp, pd.Timestamp]:
    """Longest time without a visit on ``day`` (hours, from, to), counting
    from midnight to the first visit and from the last visit to midnight."""
    t = np.sort(times.to_numpy(dtype="datetime64[ns]"))
    edges = np.concatenate([[np.datetime64(day, "ns")], t, [np.datetime64(day + pd.Timedelta(days=1), "ns")]])
    d = np.diff(edges)
    i = int(np.argmax(d))
    return d[i] / np.timedelta64(1, "h"), pd.Timestamp(edges[i]), pd.Timestamp(edges[i + 1])


def _station_gaps(mon: Monitor) -> list[dict]:
    """Stations that were silent much longer than usual on the last day."""
    s = mon.settings
    end = s["end_date"]
    w = mon.visits
    out = []
    for loc, g in w.groupby("location", sort=False):
        today = g.loc[g["date"] == end, "entry_time"]
        if len(today) == 0:
            continue               # no visit at all: station_down
        gap, t0, t1 = _gaps(today, end)
        usual = [(_gaps(x["entry_time"], d)[0]) for d, x in g[g["date"] < end].groupby("date")]
        usual_max = max(usual) if usual else None
        if gap < STOP_HOURS or (usual_max is not None and gap < 1.5 * usual_max):
            continue
        to_end = t1 >= end + pd.Timedelta(days=1)
        out.append(dict(location=loc, hours=gap, start=t0, stop=t1, to_end=to_end, usual=usual_max))
    return out


# ---- the alerts ------------------------------------------------------------------------------

def watch(mon: Monitor, removed: set[str] | None = None, pig_drop_pct: float = PIG_DROP_PCT,
          gone_days: int = GONE_DAYS, end_note: str = "") -> Watch:
    s = mon.settings
    end = s["end_date"]
    removed = set(removed or ())
    rows: list[dict] = []
    st = mon.stations.sort_values(["location", "date"])
    pig_sum = mon.pig_summary
    pigs_at = pig_sum[~pig_sum["responder"].isin(removed)].groupby("location").size()
    affected: dict = {}

    def add(level, typ, loc, msg, value=np.nan, days=1, pig=None):
        rows.append(dict(level=level, type=typ, location=loc, responder=pig, value=float(value),
                         days=int(days), message=msg))

    # stations -------------------------------------------------------------------------------
    silent = set()
    for loc, g in st.groupby("location", sort=False):
        last = g[g["date"] == end]
        if len(last) and last["n_visits"].iloc[0] == 0:
            d = _run_length(g["n_visits"] == 0)
            n = int(pigs_at.get(loc, 0))
            silent.add(loc)
            affected[loc] = n
            add("danger", "station_down", loc, "全天没有访问" + (f"（站上 {n} 头猪）" if n else "")
                + (f"，已连续 {d} 天" if d > 1 else ""), 0, d)
    for gp in _station_gaps(mon):
        loc = gp["location"]
        usual = f"，平时最长 {gp['usual']:.1f} 小时" if gp["usual"] is not None else ""
        if gp["to_end"]:
            n = int(pigs_at.get(loc, 0))
            silent.add(loc)
            affected[loc] = n
            add("danger", "station_stopped", loc,
                f"从 {gp['start']:%H:%M} 起没有记录（{gp['hours']:.1f} 小时{usual}）；"
                f"站上 {n} 头猪当天的数据不完整，不逐头报警", gp["hours"])
        else:
            add("warning", "station_gap", loc,
                f"{gp['start']:%H:%M}–{gp['stop']:%H:%M} 没有记录（{gp['hours']:.1f} 小时{usual}）",
                gp["hours"])
    for loc, g in st.groupby("location", sort=False):
        if loc in silent:
            continue
        last = g[g["date"] == end]
        if not len(last) or last["n_visits"].iloc[0] == 0:
            continue
        r = last.iloc[0]
        if r["pct_unidentified"] > s["max_unidentified_pct"]:
            d = _run_length((g["n_visits"] > 0) & (g["pct_unidentified"] > s["max_unidentified_pct"]))
            add("warning", "unidentified", loc,
                f"{r['pct_unidentified']:.1f}% 的访问没读到耳标（{int(r['n_unidentified'])}/{int(r['n_visits'])}）"
                + (f"，已连续 {d} 天" if d > 1 else "") + "：检查耳标和天线", r["pct_unidentified"], d)
        prev = g[(g["date"] < end) & (g["n_visits"] > 0)]["feed_per_pig_kg"].mean()
        x = r["feed_per_pig_kg"]
        if pd.notna(prev) and prev > 0 and pd.notna(x) and x < (1 - s["max_feed_drop_pct"] / 100) * prev:
            add("warning", "feed_drop", loc,
                f"头均采食 {x:.2f} kg，比前几天平均（{prev:.2f} kg）低 {100 * (1 - x / prev):.0f}%：检查下料和料槽",
                x)

    # pigs -----------------------------------------------------------------------------------
    pigs = mon.pigs.sort_values(["responder", "date"])
    by_pig = {r: g for r, g in pigs.groupby("responder", sort=False)}
    for _, r in pig_sum.iterrows():
        pig, loc = r["responder"], r["location"]
        if pig in removed or loc in silent:
            continue
        g = by_pig.get(pig)
        if r["status"] == "no_visit":
            d = int(r["days_since_visit"])
            wt = "" if pd.isna(r["last_weight_kg"]) else f"（最后体重 {r['last_weight_kg']:.1f} kg）"
            if d > gone_days:
                add("absent", "pig_absent", loc, f"已 {d} 天没有访问{wt}：如果已离场，请加入离场名单",
                    d, d, pig)
            else:
                add("danger", "pig_no_visit", loc, f"已 {d} 天没有访问{wt}" if d > 1 else f"当天没有访问{wt}",
                    d, d, pig)
        elif r["status"] == "low_feed":
            d = _run_length(g["status"] == "low_feed") if g is not None else 1
            add("warning", "pig_low_feed", loc,
                f"采食 {r['last_feed_kg']:.2f} kg（低于 {s['low_feed_kg']:g} kg）"
                + (f"，已连续 {d} 天" if d > 1 else ""), r["last_feed_kg"], d, pig)
        elif g is not None and pig_drop_pct > 0:
            before = g[(g["date"] < end) & (g["n_visits"] > 0)].tail(PIG_DROP_DAYS)["feed_kg"]
            x = r["last_feed_kg"]
            if len(before) >= 2 and before.mean() >= PIG_DROP_MIN_KG and pd.notna(x) \
                    and x < (1 - pig_drop_pct / 100) * before.mean():
                b = before.mean()
                add("warning", "pig_feed_drop", loc,
                    f"采食 {x:.2f} kg，比前 {len(before)} 天平均（{b:.2f} kg）低 {100 * (1 - x / b):.0f}%",
                    x, 1, pig)

    out = pd.DataFrame(rows, columns=COLS)
    if len(out):
        loc_lv = {v: i for i, v in enumerate(natural_order(out["location"]))}
        resp_lv = {v: i for i, v in enumerate(natural_order(out["responder"]))}
        out = out.assign(
            _l=out["level"].map({v: i for i, v in enumerate(LEVELS)}),
            _p=out["responder"].notna().astype(int),
            _s=out["location"].map(loc_lv),
            _t=out["type"].map({v: i for i, v in enumerate(TYPES)}),
            _r=out["responder"].map(resp_lv).fillna(1e9),
        ).sort_values(["_l", "_p", "_s", "_t", "_r"], kind="stable")[COLS].reset_index(drop=True)
    behind = (pd.Timestamp(_dt.date.today()) - s["data_last_date"]).days if pd.notna(s["data_last_date"]) else 0
    found = int(pig_sum["responder"].isin(removed).sum())
    return Watch(alerts=out, end_note=end_note, behind_days=int(behind), removed=removed,
                 removed_found=found, affected=affected, pig_drop_pct=pig_drop_pct)


def alerts_table(w: Watch) -> pd.DataFrame:
    """The alerts with Chinese column names (sheet "Alerts" of the workbook)."""
    a = w.alerts
    return pd.DataFrame({
        "级别": a["level"].map(LEVEL_ZH),
        "新/持续": [("新" if is_new(r) else f"持续 {int(r['days'])} 天") if r["level"] != "absent" else ""
                  for _, r in a.iterrows()],
        "测定站": a["location"], "猪": a["responder"], "情况": a["type"].map(TYPE_ZH), "说明": a["message"],
    })


def is_new(a: pd.Series) -> bool:
    return int(a["days"]) <= 1


def alert_text(a: pd.Series) -> str:
    """One line: who, what, new or since when."""
    who = (f"测定站 {a['location']}" if pd.isna(a["responder"])
           else f"猪 {a['responder']}（测定站 {a['location']}）")
    tag = "【新】" if is_new(a) and a["level"] != "absent" else ""
    return f"{tag}{who}：{a['message']}"
