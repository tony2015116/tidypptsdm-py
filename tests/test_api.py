from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import tidypptsdm as tp
from tidypptsdm._monitor import natural_order, r_round
from tidypptsdm._prep import misread_runs


@pytest.fixture(scope="module")
def nedap_visits():
    return tp.prep_visits(tp.load_example("nedap"), verbose=0)


@pytest.fixture(scope="module")
def mon(nedap_visits):
    return tp.run_monitor(nedap_visits, days=5, verbose=0)


# ---- reading -----------------------------------------------------------------

def test_read_folder_and_detect(tmp_path):
    raw = tp.load_example("fire")
    raw[raw["Location"] == "101"].to_csv(tmp_path / "a.csv", index=False)
    raw[raw["Location"] == "102"].to_csv(tmp_path / "b.txt", index=False, sep="\t")
    d = tp.read_station(tmp_path, verbose=0)
    assert d.attrs["station"] == "fire"
    assert len(d) == len(raw)
    assert set(d["source_file"]) == {"a.csv", "b.txt"}
    assert d["feed_intake"].max() > 100          # kg -> g
    v = tp.prep_visits(d, verbose=0)
    assert int((~v["identified"]).sum()) == 51


def test_format_file_and_chinese_headers(tmp_path):
    raw = tp.load_example("fire").rename(columns={
        "Tag": "耳标号", "Location": "站号", "Date": "日期", "Entry": "进站", "Exit": "出站",
        "Ent Wt": "进站料重", "Ext Wt": "出站料重", "Consumed": "采食量", "Weight": "体重"})
    raw.to_csv(tmp_path / "zh.csv", index=False, encoding="utf-8-sig")
    fmt = tmp_path / "format.txt"
    tp.station_format("fire", file=fmt)
    txt = fmt.read_text(encoding="utf-8")
    for a, b in [("Tag", "耳标号"), ("\tLocation", "\t站号"), ("Date,Entry", "日期,进站"),
                 ("Date,Exit", "日期,出站"), ("Ent Wt", "进站料重"), ("Ext Wt", "出站料重"),
                 ("Consumed", "采食量"), ("\tWeight", "\t体重")]:
        txt = txt.replace(a, b)
    fmt.write_text(txt, encoding="utf-8")
    d = tp.read_station(tmp_path / "zh.csv", station="fire", format=fmt, verbose=0)
    assert len(d) == len(raw)
    assert d["responder"].iloc[0] == "35877"


def test_excel_input_keeps_leading_zeros(tmp_path):
    raw = tp.load_example("nedap").head(200).copy()
    raw["responder"] = raw["responder"].map(lambda r: r if pd.isna(r) else "0" + r)
    raw.to_excel(tmp_path / "n.xlsx", index=False)
    d = tp.read_station(tmp_path / "n.xlsx", verbose=0)
    assert d["responder"].dropna().str.startswith("0").all()


def test_bad_input():
    with pytest.raises(tp.Abort, match="station data"):
        tp.run_monitor(42, verbose=0)
    with pytest.raises(tp.Abort, match="Cannot detect"):
        tp.prep_visits(pd.DataFrame({"a": [1]}), verbose=0)
    with pytest.raises(tp.Abort, match="not found"):
        tp.read_station("/no/such/file.csv", verbose=0)


def test_input_not_modified():
    raw = tp.load_example("nedap")
    before = raw.copy()
    v = tp.prep_visits(raw, verbose=0)
    pd.testing.assert_frame_equal(raw, before)
    v2 = v.copy()
    tp.run_monitor(v2, verbose=0)
    pd.testing.assert_frame_equal(v, v2)


def test_misread_runs():
    loc = ["1"] * 10 + ["2"] * 2 + ["1"] * 10
    keep = misread_runs(loc, 2)
    assert keep.sum() == 20 and not keep[10:12].any()
    moved = ["1"] * 10 + ["2"] * 10
    assert misread_runs(moved, 2).all()


def test_helpers():
    assert natural_order(["10", "2", "1", None]) == ["1", "2", "10"]
    assert r_round(0.15, 1) == 0.1        # as in R, not 0.2
    assert r_round(2.5, 0) == 2.0


# ---- tables --------------------------------------------------------------------

def test_tables_cover_every_day(mon):
    assert mon.stations.groupby("location").size().eq(5).all()
    assert len(mon.hours) == 24 * mon.stations["location"].nunique()
    assert mon.pigs.groupby("responder").size().eq(5).all()
    assert set(mon.pigs["status"]) <= {"ok", "low_feed", "no_visit"}
    with pytest.raises(tp.Abort, match="house_width"):
        tp.run_monitor(tp.load_example("nedap"), house_width=0, verbose=0)


def test_wide_table(mon):
    w = tp.wide_table(mon.stations, "feed_kg")
    assert list(w.columns)[0] == "location" and "total" in w.columns
    assert w.shape[1] == 1 + 5 + 1
    assert "mean" in tp.wide_table(mon.stations, "weight_kg").columns
    assert list(tp.wide_table(mon.hours, "n_visits").columns)[1:25] == [f"{h:02d}" for h in range(24)]
    with pytest.raises(tp.Abort, match="value"):
        tp.wide_table(mon.stations, "nope")


def test_end_date_default_is_last_full_day():
    v = tp.prep_visits(tp.load_example("nedap"), verbose=0)
    today = pd.Timestamp.today().normalize()
    shifted = v.copy()
    shifted["date"] = shifted["date"] + (today - shifted["date"].max())
    shifted["entry_time"] = shifted["entry_time"] + (today - v["date"].max())
    mon = tp.run_monitor(shifted, days=3, verbose=0)
    assert mon.settings["end_date"] == today - pd.Timedelta(days=1)


# ---- outputs ---------------------------------------------------------------------

def test_plots_ascii_and_saved(mon, tmp_path):
    plots = []
    for kind in ("trend", "intake", "heatmap", "weight", "hours"):
        p = tp.plot_monitor(mon, kind)
        assert [x.location for x in p] == ["101", "102"]
        for x in p:
            texts = [t.get_text() for t in x.figure.texts]
            assert all(t.isascii() for t in texts), texts
        plots += p
    res = tp.save_monitor_plots(plots, tmp_path, verbose=0)
    assert res["saved"].all() and len(res) == 10
    with pytest.raises(tp.Abort, match="Unknown station"):
        tp.plot_monitor(mon, "trend", locations="999")


def test_report(mon, tmp_path):
    f = tp.write_monitor_report(mon, tmp_path, verbose=0)
    html = f.read_text(encoding="utf-8")
    assert 'id="p-0"' in html and "Station 101" in html and "Station 102" in html
    assert "{{" not in html
    assert len(list((tmp_path / "img").glob("*.png"))) == 2 * 4


def test_excel_and_csv(mon, tmp_path):
    from openpyxl import load_workbook
    xl = tp.write_monitor_tables(mon, tmp_path, verbose=0)
    wb = load_workbook(xl)
    assert len(wb.sheetnames) == 16 and "Feed kg" in wb.sheetnames
    ws = wb["Feed kg"]
    rng = [str(r.sqref) for r in ws.conditional_formatting]
    assert rng == ["B2:G3"]        # the 5 days and the total, not the station column
    csv = tp.write_monitor_tables(mon, tmp_path, format="csv", verbose=0)
    assert len(csv) == 6
    back = pd.read_csv(csv[1], encoding="utf-8-sig")
    assert len(back) == len(mon.stations)


def test_cli_and_schedule(tmp_path):
    from tidypptsdm.cli import main
    ex = tmp_path / "exports"
    assert main(["example", str(ex), "--station", "fire"]) == 0
    assert main(["run", str(ex), "--out", str(tmp_path / "out"), "--days", "5", "--format", "csv", "-q"]) == 0
    day = next((tmp_path / "out").iterdir())
    assert (day / "index.html").exists() and (day / "monitor_alerts.csv").exists()
    script = tp.schedule_monitor(ex, tmp_path / "out", days=5, low_feed_kg=1, register=False, verbose=0)
    text = script.read_text(encoding="utf-8")
    assert "--days 5" in text and "--low-feed-kg 1" in text and " run " in text
    with pytest.raises(tp.Abort, match="time"):
        tp.schedule_monitor(ex, tmp_path, time="25:00", register=False, verbose=0)
    with pytest.raises(tp.Abort, match="Unknown argument"):
        tp.schedule_monitor(ex, tmp_path, nope=1, register=False, verbose=0)


def test_gui_builds():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    from tidypptsdm.gui import App
    app = App(root)
    assert app.b_run["text"].endswith("运行监控")
    root.destroy()
