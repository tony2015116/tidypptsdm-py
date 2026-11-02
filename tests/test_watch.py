"""Alerts of the desktop app (stopped stations, new or ongoing, removed pigs, feed drops)."""

import pandas as pd
import pytest

import tidypptsdm as tp
from tidypptsdm import _watch
from tidypptsdm._watch import alert_text, choose_end_date, read_removed, watch


@pytest.fixture(scope="module")
def v():
    return tp.prep_visits(tp.load_example("nedap"), verbose=0)


@pytest.fixture(scope="module")
def pigs101(v):
    return sorted(v.loc[(v["location"] == "101") & v["identified"], "responder"].unique())


DAY = pd.Timestamp("2024-05-24")


def mon_of(x, **kw):
    return tp.run_monitor(x, days=7, end_date=DAY, verbose=0, **kw)


def test_incomplete_last_day_is_not_monitored(v):
    end = v["date"].max()
    cut = v[~((v["date"] == end) & (v["entry_time"].dt.hour >= 8))]
    d, note = choose_end_date(cut)
    assert d == end - pd.Timedelta(days=1) and "只到 07:" in note
    assert choose_end_date(cut, "2024-05-20") == ("2024-05-20", "")   # a date given: kept
    late = v[v["date"] < end]                                        # last day complete (to 23:xx)
    assert late.loc[late["date"] == late["date"].max(), "entry_time"].max().hour >= _watch.LAST_DAY_UNTIL
    assert choose_end_date(late) == (None, "")


def test_station_that_stopped_is_one_alert(v):
    x = v[~((v["location"] == "102") & (v["date"] == DAY) & (v["entry_time"].dt.hour >= 8))]
    mon = mon_of(x)
    assert (mon.alerts["location"] == "102").sum() >= 2          # the package: alerts per pig
    w = watch(mon)
    a = w.alerts[w.alerts["location"] == "102"]
    assert list(a["type"]) == ["station_stopped"] and a["level"].iloc[0] == "danger"
    assert "从 07:" in a["message"].iloc[0] and "不逐头报警" in a["message"].iloc[0]
    st = w.pig_status(mon)
    off = [p for p, l in zip(mon.pig_summary["responder"], mon.pig_summary["location"]) if l == "102"]
    assert {st[p] for p in off} <= {"ok", "station_off"} and "station_off" in {st[p] for p in off}


def test_gap_during_the_day_is_a_warning(v):
    x = v[~((v["location"] == "101") & (v["date"] == DAY) & v["entry_time"].dt.hour.between(9, 15))]
    w = watch(mon_of(x))
    a = w.alerts[w.alerts["type"] == "station_gap"]
    assert len(a) == 1 and a["location"].iloc[0] == "101" and a["level"].iloc[0] == "warning"
    assert "没有记录" in a["message"].iloc[0]
    assert not (w.alerts["type"] == "station_stopped").any()


def test_new_ongoing_and_long_absent(v, pigs101):
    p1, p5 = pigs101[0], pigs101[1]
    x = v[~((v["responder"] == p1) & (v["date"] == DAY))
          & ~((v["responder"] == p5) & (v["date"] >= DAY - pd.Timedelta(days=4)))]
    w = watch(mon_of(x))
    a = w.alerts.set_index("responder")
    assert a.loc[p1, "type"] == "pig_no_visit" and a.loc[p1, "days"] == 1 and a.loc[p1, "level"] == "danger"
    assert alert_text(a.reset_index().iloc[[list(a.index).index(p1)]].iloc[0]).startswith("【新】")
    assert a.loc[p5, "type"] == "pig_absent" and a.loc[p5, "level"] == "absent" and a.loc[p5, "days"] == 5
    # the absent pig comes last
    assert w.alerts["level"].iloc[-1] == "absent"


def test_removed_pigs_are_left_out(v, pigs101, tmp_path):
    p5 = pigs101[1]
    x = v[~((v["responder"] == p5) & (v["date"] >= DAY - pd.Timedelta(days=4)))]
    (tmp_path / _watch.REMOVED_FILE).write_text(
        f"# 离场猪\n{p5}  2024-05-19 淘汰\n  99999，死亡\n\n", encoding="gb18030")
    removed = read_removed(tmp_path)
    assert removed == {p5, "99999"}
    w = watch(mon_of(x), removed=removed)
    assert p5 not in set(w.alerts["responder"]) and w.removed_found == 1
    assert w.pig_status(mon_of(x))[p5] == "removed"
    f = _watch.ensure_removed_file(tmp_path / "new")
    assert f.exists() and read_removed(tmp_path / "new") == set()


def test_pig_eating_much_less_than_usual(v, pigs101):
    p = pigs101[2]
    today = (v["responder"] == p) & (v["date"] == DAY)
    keep = ~today | (today.cumsum() <= 2)
    w = watch(mon_of(v[keep]))
    a = w.alerts[w.alerts["responder"] == p]
    assert list(a["type"]) == ["pig_feed_drop"] and "比前 5 天平均" in a["message"].iloc[0]
    assert not (watch(mon_of(v[keep]), pig_drop_pct=0).alerts["responder"] == p).any()


def test_station_feed_drop_compares_feed_per_pig(v):
    # half of the pigs of station 101 leave on the last day: total feed drops, feed per pig does not
    pigs = sorted(v.loc[(v["location"] == "101") & v["identified"], "responder"].unique())
    gone = set(pigs[: len(pigs) // 2])
    x = v[~(v["responder"].isin(gone) & (v["date"] == DAY))]
    mon = mon_of(x, max_feed_drop_pct=30)
    assert ((mon.alerts["type"] == "feed_drop") & (mon.alerts["location"] == "101")).any()   # the package
    w = watch(mon, removed=gone)
    assert not ((w.alerts["type"] == "feed_drop") & (w.alerts["location"] == "101")).any()


def test_report_of_the_app_is_chinese_and_package_stays_english(v, tmp_path):
    from tidypptsdm._plots import _LANG, cjk_font
    from tidypptsdm._report_zh import write_report_zh
    x = v[~((v["location"] == "102") & (v["date"] == DAY) & (v["entry_time"].dt.hour >= 8))]
    mon = mon_of(x)
    f = write_report_zh(mon, watch(mon), tmp_path / "zh", workers=1, dpi=40)
    html = f.read_text(encoding="utf-8")
    assert "今日待办" in html and "需要检查的测定站" in html and "中途停止记录" in html
    assert len(list((tmp_path / "zh" / "img").glob("*.png"))) == 8
    assert _LANG["zh"] is False                                   # back to English afterwards
    en = tp.write_monitor_report(mon, tmp_path / "en", workers=1, dpi=40, verbose=0).read_text(encoding="utf-8")
    assert "今日待办" not in en and "Overview" in en
    for kind in ("trend", "intake", "weight", "hours"):
        fig = tp.plot_monitor(mon, kind, "101")[0].figure
        assert all(t.get_text().isascii() for t in fig.texts)
    if cjk_font() is None:
        pytest.skip("no Chinese font here: the app's plots fall back to English")
