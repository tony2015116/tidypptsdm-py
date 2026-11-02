"""The run in Chinese, as the desktop app and the scheduled task show it."""

import sys

import pandas as pd
import pytest

import tidypptsdm as tp
from tidypptsdm import _zh
from tidypptsdm._zh import ListSink, error_zh, note_zh, run_zh


@pytest.fixture(scope="module")
def exports(tmp_path_factory):
    d = tmp_path_factory.mktemp("exports")
    tp.write_example(d, "nedap")
    return d


def test_run_in_five_steps_with_a_conclusion(exports, tmp_path):
    sink = ListSink()
    res = run_zh(exports, tmp_path, sink, days=7, end_date="2024-05-25")
    text = sink.text
    for i, step in enumerate(_zh.STEPS):
        assert f"{_zh.NUM[i]} {step}：" in text
    assert "━━ 结论" in text and "共用时" in text and "✓ 没有警报" in text
    assert "（按截止日期回看）" in text and "最新数据是" not in text  # a past end date: no stale note
    assert res["report"].exists() and (res["folder"] / "monitor.xlsx").exists()
    fr = [f for _, f in sink.progresses]
    assert fr == sorted(fr) and fr[-1] == 1.0
    assert all(text.isascii() is False for text, _ in sink.lines[:1])  # Chinese


def test_conclusion_lists_danger_alerts(nedap_like):
    from tidypptsdm._watch import watch
    w = watch(nedap_like)
    lines = _zh._conclusion(nedap_like, w)
    text = "\n".join(t for t, _ in lines)
    assert "✗ 严重" in text and "【新】测定站 102：全天没有访问" in text and "已 2 天没有访问" in text
    assert "最新数据是" in text
    assert all(tag == "bad" for t, tag in lines if t.startswith("   · "))


@pytest.fixture(scope="module")
def nedap_like():
    v = tp.prep_visits(tp.load_example("nedap"), verbose=0)
    end = v["date"].max()
    pig = sorted(v.loc[(v["location"] == "101") & v["identified"], "responder"].unique())[3]
    spoiled = v[~((v["location"] == "102") & (v["date"] == end))
                & ~((v["responder"] == pig) & (v["date"] >= end - pd.Timedelta(days=1)))]
    return tp.run_monitor(spoiled, days=7, verbose=0)


def test_many_danger_alerts_are_cut(nedap_like):
    from tidypptsdm._watch import watch
    w = watch(nedap_like)
    pig = w.alerts[w.alerts["type"] == "pig_no_visit"]
    w.alerts = pd.concat([w.alerts] + [pig] * 12, ignore_index=True)
    lines = [t for t, _ in _zh._conclusion(nedap_like, w)]
    listed = [t for t in lines if t.startswith("   · ")]
    assert len(listed) == _zh.MAX_LISTED + 1 and listed[-1].startswith("   · 另有")


def test_errors_say_what_to_do(tmp_path):
    (tmp_path / "empty").mkdir()
    sink = ListSink()
    assert run_zh(tmp_path / "empty", tmp_path / "out", sink) is None
    assert "导出文件夹里没有 CSV、TXT 或 Excel 文件" in sink.text and "怎么办：" in sink.text
    assert any("原文" in d for d in sink.details)
    text, todo = error_zh("Field 'entry_time' (column 'visit_time') in D:/x/a.csv: cannot read 3 "
                          "value(s) as time, e.g. ['x', 'y']. Give the time format")
    assert text == "文件 a.csv 的 'visit_time' 列有 3 个值读不出时间，例如 ['x', 'y']" and todo
    assert error_zh("`days` must be a whole number of at least 1, not 0.")[0] == "设置“监控天数”的值不对，应不小于 1。"
    assert error_zh("something new") == ("something new", None)


def test_bad_csv_is_explained(tmp_path):
    raw = tp.load_example("nedap").head(50).copy()
    raw.loc[3, "visit_time"] = "not a time"
    (tmp_path / "in").mkdir()
    raw.to_csv(tmp_path / "in" / "a.csv", index=False)
    sink = ListSink()
    assert run_zh(tmp_path / "in", tmp_path / "out", sink) is None
    assert "文件 a.csv 的 'visit_time' 列有 1 个值读不出时间，例如 ['not a time']" in sink.text


def test_notes_in_chinese():
    assert note_zh("Visit times with time zone UTC converted to UTC+08:00") == \
        "导出文件里的时间带时区标记（UTC），已换算成北京时间后按天统计"
    assert note_zh("1,204 duplicated rows dropped") == "删除了 1,204 行完全重复的记录"
    assert note_zh("3 pigs seen at several stations: 1 moved between stations, 2 with misreads "
                   "(5 visits kept as unidentified)") == \
        "3 头猪出现在多台测定站：1 头转过栏，2 头有耳标误读（5 次访问记为未识别）"
    assert note_zh("Drawing on 4 cores failed (OSError: x); drawing the other stations one at a time.") \
        .startswith("多核作图失败")
    assert note_zh("The latest data are from 2024-05-25, 9 days ago, ...") is None
    assert note_zh("2 alerts: 2 danger, 0 warning") is None


def test_log_is_rotated(tmp_path, monkeypatch):
    monkeypatch.setattr(_zh, "LOG_MAX_BYTES", 100)
    (tmp_path / "tidypptsdm.log").write_text("x" * 200, encoding="utf-8")
    f = _zh.open_log(tmp_path)
    f.write("new\n")
    f.close()
    assert (tmp_path / "tidypptsdm.log").read_text(encoding="utf-8") == "new\n"
    assert (tmp_path / "tidypptsdm.log.1").stat().st_size == 200


def test_windowed_exe_run_writes_chinese_log(exports, tmp_path, monkeypatch):
    from tidypptsdm.cli import main
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    code = main(["run", str(exports), "--out", str(tmp_path), "--days", "7"])
    sys.stderr.close()
    log = (tmp_path / "tidypptsdm.log").read_text(encoding="utf-8")
    assert code == 0 and "① 读取数据" in log and "━━ 结论" in log and "共用时" in log


def test_quiet_command_line_prints_nothing(exports, tmp_path, capsys):
    from tidypptsdm.cli import main
    assert main(["run", str(exports), "--out", str(tmp_path), "-q"]) == 0
    out = capsys.readouterr()
    assert out.err == "" and out.out == ""
