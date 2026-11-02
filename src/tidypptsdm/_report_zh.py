"""The HTML report of the desktop app, in Chinese, with a to-do list first.

Same layout as the report of the package (one page per station, arrow keys,
pig search), but the pages, the plots and the alerts are in Chinese, and the
alerts are those of the app (see ``_watch``)."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

from ._monitor import Monitor, _fmt_date
from ._plots import _pick_locations
from ._report import _draw_all, _esc, _link, _n_workers, _num, _table
from ._version import __version__
from ._watch import LEVEL_ZH, REMOVED_FILE, TYPE_ZH, Watch, is_new

STATUS_ZH = {"ok": "正常", "low_feed": "低采食", "no_visit": "未访问", "feed_drop": "采食骤降",
             "absent": "长期未访问", "removed": "已离场", "station_off": "站停止记录", "danger": "严重", "warning": "警告",
             "absent_level": "待确认"}


def _tag(status: str, text: str | None = None) -> str:
    return f'<span class="tag s-{status}">{_esc(text or STATUS_ZH.get(status, status))}</span>'


def _since(a) -> str:
    if a["level"] == "absent":
        return ""
    if is_new(a):
        return '<span class="tag new">新</span>'
    return f'<span class="since">持续 {int(a["days"])} 天</span>'


def _level(a) -> str:
    return _tag(a["level"], LEVEL_ZH[a["level"]])


def _station_alerts(a: pd.DataFrame, page_of: dict, link: bool = True) -> str:
    rows = []
    for _, r in a.iterrows():
        st = _link(r["location"], page_of) if link else _esc(r["location"])
        rows.append(f'<tr><td>{_level(r)}{_since(r)}</td><td class="id">{st}</td>'
                    f'<td>{_esc(TYPE_ZH[r["type"]])}</td><td class="note">{_esc(r["message"])}</td></tr>')
    return _table("<th>级别</th><th>测定站</th><th>情况</th><th>说明</th>", rows)


def _pig_alerts(a: pd.DataFrame, page_of: dict, link: bool = True) -> str:
    rows = []
    for _, r in a.iterrows():
        pig = r["responder"]
        st = _link(r["location"], page_of) if link else _esc(r["location"])
        pg = _link(r["location"], page_of, pig, pig) if link else _esc(pig)
        rows.append(f'<tr><td>{_level(r)}{_since(r)}</td><td class="id">{pg}</td><td class="id">{st}</td>'
                    f'<td>{_esc(TYPE_ZH[r["type"]])}</td><td class="note">{_esc(r["message"])}</td></tr>')
    return _table("<th>级别</th><th>猪</th><th>测定站</th><th>情况</th><th>说明</th>", rows)


def _todo(w: Watch, page_of: dict, out_hint: str) -> str:
    a = w.alerts[w.alerts["location"].isin(page_of)]
    st = a[a["responder"].isna()]
    pig = a[a["responder"].notna() & (a["level"] != "absent")]
    gone = a[a["level"] == "absent"]
    if len(st) + len(pig) + len(gone) == 0:
        return '<h2>今日待办</h2><p class="todo-ok">✓ 今天没有需要处理的事项</p>'
    html = ['<h2>今日待办</h2>']
    if len(st):
        html.append(f'<h2>需要检查的测定站 <span class="count">{len(st)}</span></h2>'
                    + _station_alerts(st, page_of))
    if len(pig):
        n_new = int(sum(is_new(r) for _, r in pig.iterrows()))
        html.append(f'<h2>需要看的猪 <span class="count">{len(pig)}</span>'
                    f'<small>其中 {n_new} 头是新出现的</small></h2>' + _pig_alerts(pig, page_of))
    if len(gone):
        html.append(f'<h2>长期未访问 <span class="count">{len(gone)}</span>'
                    f'<small>死亡、淘汰或转出？确认后把耳标号写进 {_esc(out_hint)}，就不再报警</small></h2>'
                    + _pig_alerts(gone, page_of))
    return "".join(html)


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


STATION_HEAD = (
    '<th>测定站</th><th class="n">猪数</th><th class="n">访问</th>'
    '<th class="n">未识别<br><small>%</small></th><th class="n">占用<br><small>小时</small></th>'
    '<th class="n">采食<br><small>kg</small></th><th class="n">头均采食<br><small>kg</small></th>'
    '<th class="n">体重<br><small>kg</small></th><th class="n">体重异常<br><small>%</small></th>'
    '<th class="n">警报</th>')


def _pig_table(d: pd.DataFrame, status: dict, notes: dict) -> str:
    if len(d) == 0:
        return '<p class="muted">窗口内没有识别到的猪。</p>'
    rows = []
    for _, r in d.iterrows():
        pid = _esc(r["responder"])
        stt = status.get(r["responder"], r["status"])
        rows.append(
            f'<tr id="pig-{pid}"><td class="id">{pid}</td><td>{_tag(stt)}</td>'
            f'<td class="n">{_num(r["last_visits"])}</td><td class="n">{_num(r["last_feed_kg"], 2)}</td>'
            f'<td class="n">{_num(r["mean_feed_kg"], 2)}</td>'
            f'<td class="n{" warn" if r["low_feed_days"] > 0 else ""}">{int(r["low_feed_days"])}</td>'
            f'<td class="n{" warn" if r["no_visit_days"] > 0 else ""}">{int(r["no_visit_days"])}</td>'
            f'<td class="n">{_num(r["days_since_visit"])}</td><td class="n">{_num(r["last_weight_kg"], 1)}</td>'
            f'<td class="note">{_esc(notes.get(r["responder"], ""))}</td></tr>')
    return _table(
        '<th>猪</th><th>状态</th><th class="n">访问</th><th class="n">采食<br><small>kg</small></th>'
        '<th class="n">平均采食<br><small>kg/天</small></th><th class="n">低采食<br><small>天</small></th>'
        '<th class="n">未访问<br><small>天</small></th><th class="n">距上次访问<br><small>天</small></th>'
        '<th class="n">体重<br><small>kg</small></th><th>说明</th>', rows)


def _card(label: str, value, sub: str = "") -> str:
    return (f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div>'
            f'<div class="sub">{sub}</div></div>')


def title_zh(mon: Monitor) -> str:
    s = mon.settings
    return f"{str(s['station']).upper()} 测定站监控：{_fmt_date(s['start_date'])} 至 {_fmt_date(s['end_date'])}"


def _html(mon: Monitor, w: Watch, locs: list[str], files: dict, looked_back: bool) -> str:
    s = mon.settings
    end = s["end_date"]
    d_end = _fmt_date(end)
    page_of = {l: i + 1 for i, l in enumerate(locs)}
    last = mon.stations[(mon.stations["date"] == end) & mon.stations["location"].isin(locs)]
    last = last.set_index("location").loc[locs].reset_index()
    a = w.alerts[w.alerts["location"].isin(locs)]
    n_alerts = a[a["level"] != "absent"].groupby("location").size().to_dict()
    ps = mon.pig_summary[mon.pig_summary["location"].isin(locs)]
    status = w.pig_status(mon)
    notes = {r["responder"]: r["message"] for _, r in a[a["responder"].notna()].iterrows()}
    for r in w.removed:
        notes.setdefault(r, "在离场名单上，不报警")
    for r, stt in status.items():
        if stt == "station_off":
            notes.setdefault(r, "测定站当天没有完整记录，不单独报警")

    banners = []
    if w.end_note:
        banners.append(f'<p class="banner">{_esc(w.end_note)}</p>')
    if w.behind_days > 1 and not looked_back:
        banners.append(f'<p class="banner w">最新数据是 {w.behind_days} 天前（{_fmt_date(s["data_last_date"])}）的。'
                       "如果是每天的监控，请检查测定站的导出文件是否更新。</p>")
    if w.removed:
        banners.append(f'<p class="banner">离场名单上有 {len(w.removed)} 头猪，其中 {w.removed_found} 头在本次数据中，已不报警。</p>')

    vis = int(last["n_visits"].sum())
    unid = int(last["n_unidentified"].sum())
    np_total = int(last["n_pigs"].sum())
    per_pig = (float((last["feed_per_pig_kg"].fillna(0) * last["n_pigs"]).sum()) / np_total
               if np_total > 0 else np.nan)
    n_check = int(a.loc[a["responder"].isna(), "location"].nunique())
    danger = int((a["level"] == "danger").sum())
    warning = int((a["level"] == "warning").sum())
    cards = ('<div class="cards">'
             + _card("测定站", len(locs), f'<span class="warn">{n_check} 台需要检查</span>' if n_check
                     else "都在正常记录")
             + _card("猪", len(ps), f"{np_total} 头当天来吃过料")
             + _card("访问", _num(vis), f"{_num(100 * unid / vis if vis else np.nan, 1)}% 没读到耳标")
             + _card("采食", f"{_num(float(last['feed_kg'].sum()), 1)} kg", f"头均 {_num(per_pig, 2)} kg")
             + _card("警报", danger + warning, f"严重 {danger} &middot; 警告 {warning}"
                     + (f" &middot; 待确认 {int((a['level'] == 'absent').sum())}" if (a["level"] == "absent").any() else ""))
             + "</div>")

    hw = s["house_width"]
    settings = {
        "监控窗口": f"{_fmt_date(s['start_date'])} 至 {d_end}（{s['days']} 天）",
        "低采食": f"一天少于 {s['low_feed_kg']:g} kg",
        "个体采食骤降": f"比这头猪前几天的平均低 {w.pig_drop_pct:g}% 以上" if w.pig_drop_pct > 0 else "不检查",
        "未识别访问": f"超过 {s['max_unidentified_pct']:g}% 报警",
        "测定站采食下降": f"头均采食比前几天平均低 {s['max_feed_drop_pct']:g}% 以上",
        "体重异常值": f"Tukey 法，k = {s['iqr_k']:g}",
        "栋": f"测定站编号的前 {hw} 位",
        "离场名单": REMOVED_FILE + "（结果文件夹里）",
        "程序": f"tidypptsdm {__version__} 桌面程序",
    }
    settings_html = ('<dl class="settings">'
                     + "".join(f"<dt>{k}</dt><dd>{_esc(v)}</dd>" for k, v in settings.items()) + "</dl>")
    hl = mon.houses[mon.houses["date"] == end]
    house_html = _table(
        '<th>栋</th><th class="n">测定站</th><th class="n">猪数</th><th class="n">访问</th>'
        '<th class="n">采食<br><small>kg</small></th><th class="n">头均采食<br><small>kg</small></th>'
        '<th class="n">体重<br><small>kg</small></th>',
        [f'<tr><td class="id">{_esc(r["house"])}</td><td class="n">{r["n_stations"]}</td>'
         f'<td class="n">{r["n_pigs"]}</td><td class="n">{_num(r["n_visits"])}</td>'
         f'<td class="n">{_num(r["feed_kg"], 1)}</td><td class="n">{_num(r["feed_per_pig_kg"], 2)}</td>'
         f'<td class="n">{_num(r["weight_kg"], 1)}</td></tr>' for _, r in hl.iterrows()])
    overview = ('<section class="page" id="p-0" data-title="总览">'
                f'<h1>总览</h1><p class="lead">最后一天：{d_end}</p>' + "".join(banners)
                + _todo(w, page_of, REMOVED_FILE) + cards
                + f"<h2>{d_end} 各测定站</h2>" + _table(STATION_HEAD, _station_rows(last, page_of, n_alerts))
                + f"<h2>{d_end} 各栋</h2>" + house_html
                + "<h2>设置</h2>" + settings_html + "</section>")

    def fig(loc: str, kind: str, cap: str) -> str:
        f = files.get((loc, kind))
        if not f:
            return ""
        src = "img/" + quote(f)
        return (f'<figure><a href="{src}" target="_blank" title="打开原图">'
                f'<img loading="lazy" src="{src}" alt="{_esc(cap)}"></a><figcaption>{cap}</figcaption></figure>')

    pages = []
    for l in locs:
        b = last[last["location"] == l].iloc[0]
        al = a[a["location"] == l]
        sub = (f"{d_end}：{int(b['n_pigs'])} 头猪 &middot; {_num(b['n_visits'])} 次访问 &middot; "
               f"采食 {_num(b['feed_kg'], 1)} kg"
               + (' &middot; <span class="warn">没有访问</span>' if b["n_visits"] == 0 else ""))
        al_st, al_pig = al[al["responder"].isna()], al[al["responder"].notna()]
        alerts = ""
        if len(al):
            alerts = f'<h2>警报 <span class="count">{len(al)}</span></h2>'
            if len(al_st):
                alerts += _station_alerts(al_st, page_of, False)
            if len(al_pig):
                alerts += ("<p></p>" if len(al_st) else "") + _pig_alerts(al_pig, page_of, False)
        pages.append(
            f'<section class="page" id="p-{page_of[l]}" data-title="测定站 {_esc(l)}" hidden>'
            f'<h1>测定站 {_esc(l)}</h1><p class="lead">{sub}</p>' + alerts
            + fig(l, "trend", "窗口内每天的变化，含猪的体重（灰色带：最轻到最重的猪）；红色：没有访问的日子")
            + fig(l, "intake", "每头猪每天的采食：上图为占全站的比例，下图为 kg；最后一天未访问或低采食的猪在图例中标出")
            + "<h2>猪</h2>" + _pig_table(ps[ps["location"] == l], status, notes)
            + fig(l, "weight", "每天称到的体重")
            + fig(l, "hours", f"{d_end} 每小时的访问、占用时间和采食量；整段空白说明这段时间没有记录")
            + "</section>")

    nav = '<a href="#p-0" data-page="0" class="nav-item">总览</a>' + "".join(
        f'<a href="#p-{page_of[l]}" data-page="{page_of[l]}" class="nav-item">测定站 {_esc(l)}'
        + (f' <span class="badge" title="警报">{n_alerts[l]}</span>' if n_alerts.get(l) else "")
        + "</a>" for l in locs)
    pig_map = json.dumps({str(r): page_of[l] for r, l in zip(ps["responder"], ps["location"])},
                         ensure_ascii=False)
    tpl = (resources.files("tidypptsdm") / "templates" / "report_zh.html").read_text(encoding="utf-8")
    repl = {"{{TITLE}}": _esc(title_zh(mon)), "{{NAV}}": nav, "{{PAGES}}": "\n".join([overview] + pages),
            "{{PIGS}}": pig_map, "{{DATE}}": pd.Timestamp.today().strftime("%Y-%m-%d")}
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    return tpl


def write_report_zh(mon: Monitor, w: Watch, path, workers: int | None = None, progress=None,
                    dpi: int = 150, looked_back: bool = False) -> Path:
    """Write ``index.html`` and ``img/`` into ``path``. ``progress(done, total)``."""
    path = Path(path)
    locs = _pick_locations(mon, None)
    img = path / "img"
    img.mkdir(parents=True, exist_ok=True)

    def show(n: int) -> None:
        if progress is not None:
            progress(n, len(locs))

    rows = _draw_all(mon, locs, img, dpi, _n_workers(workers, len(locs)), show, zh=True)
    files = {(l, t): f for l, t, f, ok in rows if ok}
    out = path / "index.html"
    out.write_text(_html(mon, w, locs, files, looked_back), encoding="utf-8")
    return out
