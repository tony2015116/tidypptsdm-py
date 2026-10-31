"""Excel workbook with colour scales, or CSV files (as write_monitor_tables() in R)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ._messages import Abort, local_verbose, msg, plural
from ._monitor import Monitor, wide_table

COLOURS = {
    "low": ("F8696B", "FFEB84", "63BE7B"),    # red for low values
    "high": ("63BE7B", "FFEB84", "F8696B"),   # red for high values
    "blue": ("FFFFFF", "9DC3E6", "2E75B6"),
}


def _sheets(mon: Monitor) -> list[tuple[str, pd.DataFrame, str | None, int]]:
    st = mon.stations
    return [
        ("Alerts", mon.alerts, None, 0),
        ("Stations", st, None, 1),
        ("Visits", wide_table(st, "n_visits"), "low", 1),
        ("Unidentified pct", wide_table(st, "pct_unidentified"), "high", 1),
        ("Feed kg", wide_table(st, "feed_kg"), "low", 1),
        ("Feed per pig kg", wide_table(st, "feed_per_pig_kg"), "low", 1),
        ("Occupation h", wide_table(st, "occupation_h"), "low", 1),
        ("Weight outliers pct", wide_table(st, "pct_weight_outlier"), "high", 1),
        ("Houses", mon.houses, None, 1),
        ("House feed per pig kg", wide_table(mon.houses, "feed_per_pig_kg"), "low", 1),
        ("House weight kg", wide_table(mon.houses, "weight_kg"), "blue", 1),
        ("Pigs", mon.pig_summary, None, 2),
        ("Pig feed kg", wide_table(mon.pigs, "feed_kg"), "low", 2),
        ("Pig days", mon.pigs, None, 2),
        ("Hours visits", wide_table(mon.hours, "n_visits"), "blue", 1),
        ("Hours feed kg", wide_table(mon.hours, "feed_kg"), "blue", 1),
    ]


def _cell(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime().date()
    if isinstance(v, np.generic):
        return v.item()
    return v


def _long_tables(mon: Monitor) -> dict[str, pd.DataFrame]:
    return {"alerts": mon.alerts, "stations": mon.stations, "houses": mon.houses,
            "pigs": mon.pig_summary, "pig_days": mon.pigs, "hours": mon.hours}


def write_monitor_tables(mon: Monitor, path, format: str = "xlsx", file: str = "monitor",
                         verbose: int = 1) -> Path | list[Path]:
    """Write the monitor tables to an Excel workbook or CSV files.

    The workbook has the long tables ``Alerts``, ``Stations``, ``Houses``,
    ``Pigs`` (pig summary) and ``Pig days``, and wide sheets (see
    [wide_table()][tidypptsdm.wide_table]) with a colour scale from red (a
    possible problem) over yellow to green: ``Visits``, ``Unidentified pct``
    (red for high), ``Feed kg``, ``Feed per pig kg``, ``Occupation h``,
    ``Weight outliers pct`` (red for high), ``House feed per pig kg``,
    ``House weight kg``, ``Pig feed kg``, ``Hours visits`` and
    ``Hours feed kg`` (blue scales).

    Args:
        mon: Result of [run_monitor()][tidypptsdm.run_monitor].
        path: Folder to write to (created if needed).
        format: ``"xlsx"`` (default) or ``"csv"``: the six long tables as
            ``<file>_alerts.csv`` and so on, UTF-8 with a byte order mark so
            that Excel shows Chinese text correctly.
        file: File name without extension, or prefix of the CSV files.
        verbose: 0 (silent) or 1.

    Returns:
        The path of the workbook, or the paths of the CSV files.
    """
    with local_verbose(verbose):
        if not isinstance(mon, Monitor):
            raise Abort("`mon` must be the result of run_monitor().")
        if format not in ("xlsx", "csv"):
            raise Abort("`format` must be 'xlsx' or 'csv'.")
        if not file:
            raise Abort("`file` must be a file name.")
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        if format == "csv":
            out = []
            for name, df in _long_tables(mon).items():
                f = path / f"{file}_{name}.csv"
                df2 = df.copy()
                if "date" in df2.columns:
                    df2["date"] = df2["date"].dt.strftime("%Y-%m-%d")
                df2.to_csv(f, index=False, encoding="utf-8-sig")
                out.append(f)
            msg(f"Wrote {plural(len(out), 'CSV file')} to {path}", "success")
            return out

        wb = Workbook()
        wb.remove(wb.active)
        head_font = Font(bold=True)
        head_fill = PatternFill("solid", fgColor="F2F2F2")
        head_border = Border(bottom=Side(style="thin", color="808080"))
        center = Alignment(horizontal="center")
        sheets = _sheets(mon)
        for name, df, scale, n_id in sheets:
            ws = wb.create_sheet(name)
            cols = list(df.columns)
            ws.append(cols)
            for c in ws[1]:
                c.font, c.fill, c.border, c.alignment = head_font, head_fill, head_border, center
            for row in df.itertuples(index=False):
                ws.append([_cell(v) for v in row])
            for j, col in enumerate(cols, start=1):
                if col == "date":
                    for (cell,) in ws.iter_rows(min_row=2, min_col=j, max_col=j):
                        cell.number_format = "yyyy-mm-dd"
                vals = [str(col)] + [("" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v))
                                     for v in df[col].head(500).tolist()]
                width = max(len(v) for v in vals) + 2
                ws.column_dimensions[get_column_letter(j)].width = min(max(width, 8), 60)
            ws.freeze_panes = ws.cell(row=2, column=n_id + 1)
            if scale and len(df) > 0 and len(cols) > n_id:
                lo, mid, hi = COLOURS[scale]
                rng = f"{get_column_letter(n_id + 1)}2:{get_column_letter(len(cols))}{len(df) + 1}"
                ws.conditional_formatting.add(rng, ColorScaleRule(
                    start_type="min", start_color=lo, mid_type="percentile", mid_value=50,
                    mid_color=mid, end_type="max", end_color=hi))
        out = path / f"{file}.xlsx"
        wb.save(out)
        msg(f"Wrote {out} ({len(sheets)} sheets)", "success")
        return out
