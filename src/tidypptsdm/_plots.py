"""One plot per station, drawn with matplotlib (as the R package does with ggplot2)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # files only; no window needed (also inside the exe)

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.patches  # noqa: E402,F401
import matplotlib.ticker  # noqa: E402,F401
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, to_hex  # noqa: E402

from ._messages import Abort, local_verbose, msg  # noqa: E402
from ._monitor import Monitor, natural_order  # noqa: E402

PLOT_TYPES = ("trend", "intake", "weight", "hours")
CM = 1 / 2.54

INK = "#1D2330"
MUTED = "#667085"
GRID = "#EBEBEB"
RED = "#B42318"
ORANGE = "#D97706"

# Okabe-Ito: colour-blind safe
OKABE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9",
         "#F0E442", "#000000", "#999999"]
# ColorBrewer Paired and Dark2, as in pptsdm
PIG_COLOURS = ["#A6CEE3", "#1F78B4", "#B2DF8A", "#33A02C", "#FB9A99", "#E31A1C",
               "#FDBF6F", "#FF7F00", "#CAB2D6", "#6A3D9A", "#B15928", "#8DD3C7",
               "#1B9E77", "#D95F02", "#7570B3", "#E7298A", "#66A61E", "#E6AB02",
               "#A6761D", "#666666"]


# ---- language: English for the package (as the R package); Chinese in the desktop app ------

_LANG = {"zh": False}
CJK_FONTS = ["Microsoft YaHei", "DengXian", "SimHei", "Noto Sans CJK SC", "Source Han Sans SC",
             "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "PingFang SC", "Heiti SC", "Arial Unicode MS"]


def _tr(en: str, zh: str, **kw) -> str:
    return (zh if _LANG["zh"] else en).format(**kw)


def cjk_font() -> str | None:
    """A font with Chinese characters on this computer, or None."""
    from matplotlib import font_manager
    names = {f.name for f in font_manager.fontManager.ttflist}
    return next((f for f in CJK_FONTS if f in names), None)


def set_language(zh: bool) -> bool:
    """Chinese plot labels (only when a Chinese font is found). Returns
    whether the plots are in Chinese."""
    font = cjk_font() if zh else None
    _LANG["zh"] = font is not None
    if font is not None:
        matplotlib.rcParams["font.sans-serif"] = [font, "DejaVu Sans"]
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["axes.unicode_minus"] = False
    else:
        matplotlib.rcParams["font.sans-serif"] = matplotlib.rcParamsDefault["font.sans-serif"]
        matplotlib.rcParams["axes.unicode_minus"] = matplotlib.rcParamsDefault["axes.unicode_minus"]
    return _LANG["zh"]


def _ramp(colours: list[str], n: int) -> list[str]:
    if n <= len(colours):
        return colours[:n]
    cmap = LinearSegmentedColormap.from_list("ramp", colours)
    return [to_hex(cmap(i / (n - 1))) for i in range(n)]


def pig_palette(n: int) -> list[str]:
    return _ramp(PIG_COLOURS, n)


@dataclass
class StationPlot:
    """A plot of one station. ``width`` and ``height`` are in cm."""

    location: str
    type: str
    figure: plt.Figure
    width: float
    height: float


def _style(ax, grid_x: bool = True) -> None:
    ax.set_facecolor("white")
    for sp in ax.spines.values():
        sp.set_color("#333333")
        sp.set_linewidth(0.6)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    if grid_x:
        ax.grid(True, axis="x", color=GRID, linewidth=0.8)
    else:
        ax.grid(False, axis="x")
    ax.set_axisbelow(True)
    ax.tick_params(colors="#4D4D4D", labelsize=8, length=3)


def _title(fig, title: str, subtitle: str | None = None) -> None:
    fig.text(0.01, 0.995, title, ha="left", va="top", fontsize=12, fontweight="bold", color="black")
    if subtitle:
        fig.text(0.01, 0.995 - 0.38 / fig.get_figheight(), subtitle, ha="left", va="top",
                 fontsize=9, color=MUTED)


def _top_margin(fig, subtitle: bool = True) -> float:
    return 1 - (0.75 if subtitle else 0.45) / fig.get_figheight()


def _date_axis(ax, s: dict, rotate: bool = True) -> None:
    start, end, days = s["start_date"], s["end_date"], s["days"]
    step = max(1, int(np.ceil(days / 14)))
    ticks = list(pd.date_range(end, start, freq=f"-{step}D"))[::-1]
    ax.set_xticks(ticks)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.set_xlim(start - pd.Timedelta(hours=14), end + pd.Timedelta(hours=14))
    if rotate:
        for lab in ax.get_xticklabels():
            lab.set_rotation(45)
            lab.set_ha("right")


def _text_width_cm(fig, artists) -> float:
    """Width in cm of the widest artist once drawn (legend, tick labels)."""
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    widths = [a.get_window_extent(renderer=r).width for a in artists if a.get_visible()]
    return (max(widths) if widths else 0.0) / fig.dpi * 2.54


def _plot_width(days: int) -> float:
    return max(16, 0.7 * days + 8)


def _empty(location: str, kind: str, title: str, text: str) -> StationPlot:
    fig = plt.figure(figsize=(16 * CM, 6 * CM))
    _title(fig, title)
    fig.text(0.5, 0.45, text, ha="center", va="center", color=MUTED, fontsize=10)
    return StationPlot(location, kind, fig, 16, 6)


def _strip_label(ax, text: str) -> None:
    ax.set_ylabel(text, rotation=0, ha="right", va="center", fontsize=9, color="#333333", labelpad=8)


# ---- trend -----------------------------------------------------------------------------

TREND = [("n_pigs", "Pigs"), ("n_visits", "Visits"), ("pct_unidentified", "Unidentified (%)"),
         ("occupation_h", "Occupation (h)"), ("feed_kg", "Feed (kg)"),
         ("feed_per_pig_kg", "Feed per pig (kg)"), ("weight_kg", "Weight (kg)")]
LABEL_ZH = {"Pigs": "猪数", "Visits": "访问次数", "Unidentified (%)": "未识别 (%)",
            "Occupation (h)": "占用 (小时)", "Feed (kg)": "采食 (kg)", "Feed per pig (kg)": "头均采食 (kg)",
            "Weight (kg)": "体重 (kg)", "Occupation (min)": "占用 (分钟)"}


def _label(en: str) -> str:
    return LABEL_ZH[en] if _LANG["zh"] else en


def _plot_trend(mon: Monitor, loc: str) -> StationPlot:
    s = mon.settings
    d = mon.stations[mon.stations["location"] == loc]
    down = d.loc[d["n_visits"] == 0, "date"]
    colours = OKABE[:6] + ["#1B2A4A"]
    width, height = _plot_width(s["days"]), 3.2 * len(TREND) + 3
    fig, axes = plt.subplots(len(TREND), 1, sharex=True, figsize=(width * CM, height * CM))
    band = mon.pigs[(mon.pigs["location"] == loc) & mon.pigs["weight_kg"].notna()] \
        .groupby("date")["weight_kg"].agg(["min", "max"])
    for ax, (col, label), colour in zip(axes, TREND, colours):
        _style(ax)
        for day in down:
            ax.axvspan(day - pd.Timedelta(hours=12), day + pd.Timedelta(hours=12), color=RED, alpha=0.15, lw=0)
        if col == "weight_kg" and len(band):
            ax.fill_between(band.index, band["min"], band["max"], color="#999999", alpha=0.25, lw=0)
        y = d[col].astype(float)
        ax.plot(d["date"], y, color=colour, lw=1.2)
        ax.plot(d["date"], y, "o", color=colour, ms=3.5)
        _strip_label(ax, _label(label))
        if col in ("n_pigs", "n_visits"):
            ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    _date_axis(axes[-1], s)
    sub = (_tr("{a} to {b}; weight band: lightest to heaviest pig", "{a} 至 {b}；灰色带：最轻到最重的猪",
               a=f"{s['start_date']:%Y-%m-%d}", b=f"{s['end_date']:%Y-%m-%d}")
           + (_tr("; red: no visits", "；红色：没有访问") if len(down) else ""))
    _title(fig, _tr("Station {loc}", "测定站 {loc}", loc=loc), sub)
    fig.subplots_adjust(left=4.6 / width, right=0.98, bottom=1.4 / height, top=_top_margin(fig), hspace=0.12)
    return StationPlot(loc, "trend", fig, width, height)


# ---- intake: stacked bars ----------------------------------------------------------------

def _plot_intake(mon: Monitor, loc: str) -> StationPlot:
    s = mon.settings
    title = _tr("Station {loc} - feed intake per pig", "测定站 {loc}：每头猪的采食量", loc=loc)
    d = mon.pigs[(mon.pigs["location"] == loc) & (mon.pigs["n_visits"] > 0)]
    if len(d) == 0:
        return _empty(loc, "intake", title, _tr("No identified pig in the window", "窗口内没有识别到的猪"))
    pigs = natural_order(d["responder"])
    ps = mon.pig_summary[mon.pig_summary["location"] == loc].set_index("responder")["status"]
    flags = [ps.get(p) for p in pigs]
    labels = [p + (_tr(" [no visit]", " [未访问]") if f == "no_visit"
                   else _tr(" [low feed]", " [低采食]") if f == "low_feed" else "")
              for p, f in zip(pigs, flags)]
    kg = d.pivot_table(index="date", columns="responder", values="feed_kg", aggfunc="sum") \
        .reindex(columns=pigs).fillna(0.0)
    total = kg.sum(axis=1)
    share = kg.div(total.where(total > 0, 1.0), axis=0) * 100
    colours = pig_palette(len(pigs))
    ncol = max(1, int(np.ceil(len(pigs) / 25)))
    plot_w = _plot_width(s["days"])
    width = plot_w + 6 * ncol          # first guess; corrected once the legend is measured
    height = max(18, 0.45 * len(pigs) / ncol + 6)
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(width * CM, height * CM))
    bar_w = 0.8
    x = kg.index
    for ax, data in ((ax1, share), (ax2, kg)):
        _style(ax, grid_x=False)
        bottom = np.zeros(len(data))
        for p, c in zip(pigs, colours):
            vals = data[p].to_numpy()
            ax.bar(x, vals, width=bar_w, bottom=bottom, color=c, edgecolor="white", linewidth=0.3)
            bottom += vals
    ax1.set_ylim(0, 108)
    ax1.set_ylabel(_tr("Share of station feed (%)", "占全站采食 (%)"), fontsize=9, color="#333333")
    ax2.set_ylim(0, max(total.max(), 0.1) * 1.1)
    ax2.set_ylabel(_tr("Feed intake (kg)", "采食量 (kg)"), fontsize=9, color="#333333")
    if s["days"] <= 31:
        for xi, t in zip(x, total):
            ax2.text(xi, t, f"{t:.1f}", ha="center", va="bottom", fontsize=7, color=INK)
    _date_axis(ax2, s)
    handles = [matplotlib.patches.Patch(facecolor=c, label=l) for c, l in zip(colours, labels)]
    leg = fig.legend(handles=handles, title=_tr("Pig", "猪"), loc="center left", bbox_to_anchor=(0, 0.5),
                     ncol=ncol, fontsize=8, title_fontsize=9, frameon=False,
                     handlelength=1.2, handleheight=1.0)
    n_flag = sum(f in ("no_visit", "low_feed") for f in flags)
    sub = _tr("{n} pigs; bottom: daily total above the bar", "{n} 头猪；下图柱顶为当天总量", n=len(pigs))
    if n_flag:
        sub += _tr("; {k} pig{pl} marked in the legend on {d}", "；图例中标出 {k} 头猪（{d}）",
                   k=n_flag, pl="s" if n_flag > 1 else "", d=f"{s['end_date']:%Y-%m-%d}")
    _title(fig, title, sub)
    # size the figure so that the legend, however long the pig IDs are, sits
    # right of the plots and inside the picture
    left = 1.6
    leg_w = _text_width_cm(fig, [leg])
    width = left + plot_w + 0.5 + leg_w + 0.4
    fig.set_size_inches(width * CM, height * CM)
    right = (left + plot_w) / width
    leg.set_bbox_to_anchor((right + 0.5 / width, 0.5), transform=fig.transFigure)
    fig.subplots_adjust(left=left / width, right=right, bottom=1.4 / height,
                        top=_top_margin(fig), hspace=0.06)
    return StationPlot(loc, "intake", fig, width, height)


# ---- weights ----------------------------------------------------------------------------------

def _plot_weight(mon: Monitor, loc: str) -> StationPlot:
    s = mon.settings
    title = _tr("Station {loc} - recorded body weights", "测定站 {loc}：称到的体重", loc=loc)
    d = mon.visits[(mon.visits["location"] == loc) & mon.visits["identified"] & mon.visits["weight"].notna()]
    if len(d) == 0:
        return _empty(loc, "weight", title, _tr("No body weight in the window", "窗口内没有体重记录"))
    width, height = _plot_width(s["days"]), 10
    fig, ax = plt.subplots(figsize=(width * CM, height * CM))
    _style(ax)
    groups = [(day, g["weight"].to_numpy()) for day, g in d.groupby("date")]
    pos = [mdates.date2num(day) for day, _ in groups]
    ax.boxplot([g for _, g in groups], positions=pos, widths=0.7, patch_artist=True, manage_ticks=False,
               boxprops=dict(facecolor="#E6F0FA", edgecolor="#0F6CBD", linewidth=0.9),
               medianprops=dict(color="#0F6CBD", linewidth=1.6),
               whiskerprops=dict(color="#0F6CBD", linewidth=0.9),
               capprops=dict(color="#0F6CBD", linewidth=0),
               flierprops=dict(marker="o", markerfacecolor=RED, markeredgecolor=RED, markersize=2.5))
    ax.xaxis_date()
    _date_axis(ax, s)
    ax.set_ylabel(_tr("Body weight (kg)", "体重 (kg)"), fontsize=9)
    _title(fig, title, _tr("All weights of the identified visits; red: outside the whiskers",
                           "识别到的访问的全部体重；红点：须线以外"))
    fig.subplots_adjust(left=1.8 / width, right=0.98, bottom=1.6 / height, top=_top_margin(fig))
    return StationPlot(loc, "weight", fig, width, height)


# ---- hours --------------------------------------------------------------------------------------

HOURS = [("n_visits", "Visits"), ("occupation_min", "Occupation (min)"), ("feed_kg", "Feed (kg)")]


def _plot_hours(mon: Monitor, loc: str) -> StationPlot:
    s = mon.settings
    d = mon.hours[mon.hours["location"] == loc]
    width, height = 18, 12
    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(width * CM, height * CM))
    for ax, (col, label), colour in zip(axes, HOURS, OKABE[:3]):
        _style(ax, grid_x=False)
        ax.bar(d["hour"], d[col].astype(float), width=0.8, color=colour)
        _strip_label(ax, _label(label))
    axes[-1].set_xticks(range(24))
    axes[-1].tick_params(axis="x", labelsize=8)
    axes[-1].set_xlim(-0.6, 23.6)
    axes[-1].set_xlabel(_tr("Hour of the day", "时（按进站时间）"), fontsize=9)
    _title(fig, _tr("Station {loc} - hours of {d}", "测定站 {loc}：{d} 各小时", loc=loc, d=f"{s['end_date']:%Y-%m-%d}"))
    fig.subplots_adjust(left=4.2 / width, right=0.98, bottom=1.4 / height, top=_top_margin(fig, False), hspace=0.12)
    return StationPlot(loc, "hours", fig, width, height)


_DRAW = {"trend": _plot_trend, "intake": _plot_intake, "weight": _plot_weight,
         "hours": _plot_hours}


def _pick_locations(mon: Monitor, locations) -> list[str]:
    all_locs = natural_order(mon.stations["location"])
    if locations is None:
        return all_locs
    if isinstance(locations, (str, int)):
        locations = [locations]
    locations = [str(l) for l in locations]
    bad = [l for l in locations if l not in all_locs]
    if bad:
        raise Abort(f"Unknown station(s): {bad}. Stations: {all_locs}.")
    return [l for l in all_locs if l in locations]


def plot_monitor(mon: Monitor, type: str = "trend", locations=None) -> list[StationPlot]:
    """Plot the monitor, one plot per station.

    Args:
        mon: Result of [run_monitor()][tidypptsdm.run_monitor].
        type: ``"trend"`` (default): pigs, visits, unidentified visits,
            occupation time, feed intake, feed intake per pig and body weight
            (mean of the pigs' daily medians; band from the lightest to the
            heaviest pig) per day; days without visits shaded red.
            ``"intake"``: stacked bars, one colour per pig: share of the
            station's feed (top) and kg (bottom) with the daily total; pigs
            without visit or with low feed on the last day are marked in the
            legend. ``"weight"``: box plots of the
            recorded body weights per day. ``"hours"``: visits, occupation
            time and feed intake per hour of the last day.
        locations: Stations to plot. Default ``None``: all.

    Returns:
        A list of [StationPlot][tidypptsdm.StationPlot]: ``location``,
        ``type``, ``figure`` (a matplotlib Figure) and ``width`` and
        ``height`` in cm.
    """
    if not isinstance(mon, Monitor):
        raise Abort("`mon` must be the result of run_monitor().")
    if type not in PLOT_TYPES:
        raise Abort(f"`type` must be one of {list(PLOT_TYPES)}, not {type!r}.")
    return [_DRAW[type](mon, l) for l in _pick_locations(mon, locations)]


def save_monitor_plots(plots: list[StationPlot], path, device: str = "png", dpi: int = 150,
                       verbose: int = 1) -> pd.DataFrame:
    """Save plots from [plot_monitor()][tidypptsdm.plot_monitor] to files.

    Files are named ``station_<location>_<type>.<device>``.

    Args:
        plots: One or more results of ``plot_monitor()`` (lists can be added
            with ``+``).
        path: Folder to write to (created if needed).
        device: ``"png"`` (default) or ``"pdf"``.
        dpi: Resolution of PNG files. Default 150.
        verbose: 0 (silent) or 1.

    Returns:
        A DataFrame with ``location``, ``type``, ``file`` and ``saved``.
    """
    with local_verbose(verbose):
        if device not in ("png", "pdf"):
            raise Abort("`device` must be 'png' or 'pdf'.")
        if not isinstance(plots, list) or not all(isinstance(p, StationPlot) for p in plots):
            raise Abort("`plots` must be the result of plot_monitor().")
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        rows = []
        for p in plots:
            f = path / f"station_{p.location}_{p.type}.{device}"
            try:
                p.figure.set_size_inches(p.width * CM, p.height * CM)
                p.figure.savefig(f, dpi=dpi, facecolor="white")
                ok = True
            except Exception as e:  # noqa: BLE001 - report and go on
                msg(f"Could not save {f}: {e}", "warning")
                ok = False
            finally:
                plt.close(p.figure)
            rows.append({"location": p.location, "type": p.type, "file": str(f), "saved": ok})
        res = pd.DataFrame(rows, columns=["location", "type", "file", "saved"])
        msg(f"Saved {int(res['saved'].sum())} of {len(res)} plots to {path}",
            "success" if res["saved"].all() else "warning")
        return res
