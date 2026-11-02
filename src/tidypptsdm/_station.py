"""Read NEDAP and FIRE exports and map their columns to the standard fields.

A port of ``read_station()`` and ``station_format()`` of the R package
tidypptsda. The standard fields and their units:

=============  ========  ====================================
field          unit      meaning
=============  ========  ====================================
responder      text      transponder number as recorded
location       text      station (feeder) ID
entry_time     clock     entrance time (time-zone naive)
exit_time      clock     exit time
duration       s         occupation time of the visit
feed_intake    g         feed intake of the visit
weight         kg        body weight
trough_in      g         trough weight at entrance (FIRE)
trough_out     g         trough weight at exit (FIRE)
topup          g         feed dispensed during the visit (FIRE)
breed          text      breed (optional)
=============  ========  ====================================
"""

from __future__ import annotations

import csv
import datetime
import io
import os
import re
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from ._messages import Abort, local_verbose, msg, plural

STATIONS = ("nedap", "fire")

FIELD_TYPES = {
    "responder": "text",
    "location": "text",
    "entry_time": "time",
    "exit_time": "time",
    "duration": "duration",
    "feed_intake": "mass_g",
    "weight": "mass_kg",
    "trough_in": "mass_g",
    "trough_out": "mass_g",
    "topup": "mass_g",
    "breed": "text",
}

FIELD_DESCRIPTIONS = {
    "responder": "Transponder number",
    "location": "Station (feeder) ID",
    "entry_time": "Entrance time",
    "exit_time": "Exit time",
    "duration": "Occupation time",
    "feed_intake": "Feed intake of the visit",
    "weight": "Body weight",
    "trough_in": "Trough weight at entrance",
    "trough_out": "Trough weight at exit",
    "topup": "Feed dispensed during the visit",
    "breed": "Breed",
}

STATION_FIELDS = {
    "nedap": ["responder", "location", "entry_time", "exit_time", "duration",
              "feed_intake", "weight", "breed"],
    "fire": ["responder", "location", "entry_time", "exit_time", "feed_intake",
             "weight", "trough_in", "trough_out", "topup", "breed"],
}

STATION_REQUIRED = {
    "nedap": ["responder", "location", "entry_time", "feed_intake", "weight"],
    "fire": ["responder", "location", "entry_time", "exit_time", "feed_intake",
             "weight", "trough_in", "trough_out"],
}

BUILTIN_FORMATS = {
    "nedap": [
        ("responder", "responder", "-"),
        ("location", "location", "-"),
        ("entry_time", "visit_time", "-"),
        ("exit_time", "-", "-"),
        ("duration", "duration", "s"),
        ("feed_intake", "feed_intake", "g"),
        ("weight", "weight", "auto"),
        ("breed", "breed", "-"),
    ],
    "fire": [
        ("responder", "Tag", "-"),
        ("location", "Location", "-"),
        ("entry_time", "Date,Entry", "-"),
        ("exit_time", "Date,Exit", "-"),
        ("feed_intake", "Consumed", "kg"),
        ("weight", "Weight", "kg"),
        ("trough_in", "Ent Wt", "kg"),
        ("trough_out", "Ext Wt", "kg"),
        ("topup", "Topup Amount", "kg"),
        ("breed", "breed", "-"),
    ],
}

STD_COLS = ["responder", "location", "entry_time", "exit_time", "duration",
            "feed_intake", "weight", "trough_in", "trough_out", "topup"]

DEFAULT_PATTERN = r"\.(csv|txt|xlsx)$"

TIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
    "%Y/%m/%d %H:%M:%S.%f", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M",
    "%Y-%m-%d", "%Y/%m/%d",
]


# ---- formats -------------------------------------------------------------------

def check_station(station: str) -> str:
    if not isinstance(station, str) or station.lower() not in STATIONS:
        raise Abort(f"`station` must be 'nedap' or 'fire', not {station!r}.")
    return station.lower()


def builtin_format(station: str) -> pd.DataFrame:
    return pd.DataFrame(BUILTIN_FORMATS[station], columns=["field", "column", "unit"])


def station_format(station: str = "nedap", file: str | os.PathLike | None = None) -> pd.DataFrame:
    """The built-in station format of a station type.

    Args:
        station: ``"nedap"`` or ``"fire"``.
        file: Optional path. The format is written there as a tab-separated
            text file, a template to edit for exports with other column names
            and to pass to ``read_station(format=)``.

    Returns:
        A DataFrame with one row per field: ``field``, ``column``, ``unit``,
        ``required`` and ``description``.

    In the format, ``column`` is the column name or its position (``"6"``);
    alternatives are separated by ``|`` (``"Tag|耳标号"``); two columns joined
    with ``,`` give a date and a clock time (``"Date,Entry"``); ``-`` means
    the export has no such column. ``unit`` is ``kg``, ``g`` or ``auto`` for
    masses, ``s`` or ``min`` for the duration, and ``-`` or a ``strptime``
    format such as ``%d/%m/%Y %H:%M`` for times.
    """
    station = check_station(station)
    fmt = builtin_format(station)
    fmt["required"] = fmt["field"].isin(STATION_REQUIRED[station])
    fmt["description"] = fmt["field"].map(FIELD_DESCRIPTIONS)
    if file is not None:
        header = [
            f"# tidypptsdm station format: {station.upper()}",
            "# One line per field, separated by tabs: field, column, unit.",
            "# column: column name or position; alternatives with |; date,time joined with ,; - if absent.",
            "# unit: kg / g / auto for masses, s / min for duration, - or a strptime format for times.",
            "# Required fields: " + ", ".join(STATION_REQUIRED[station]) + ".",
        ]
        with open(file, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(header) + "\n")
            fmt[["field", "column", "unit"]].to_csv(f, sep="\t", index=False, lineterminator="\n")
        msg(f"Station format written to {file}", "success")
    return fmt


def as_station_format(fmt, station: str) -> pd.DataFrame:
    """Read and check a user format: a file path, a DataFrame or a dict."""
    if isinstance(fmt, (str, os.PathLike)):
        path = Path(fmt)
        if not path.exists():
            raise Abort(f"Format file not found: {path}.")
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]
        if len(lines) < 2:
            raise Abort(f"Format file {path} has no fields.")
        out = pd.read_csv(io.StringIO("\n".join(lines)), sep="\t", dtype=str,
                          keep_default_na=False)
    elif isinstance(fmt, dict):
        out = pd.DataFrame({"field": list(fmt), "column": list(fmt.values())})
    elif isinstance(fmt, pd.DataFrame):
        out = fmt.copy()
    else:
        raise Abort("`format` must be a file path, a DataFrame or a dict {field: column}.")
    out.columns = [str(c).strip().lower() for c in out.columns]
    if not {"field", "column"} <= set(out.columns):
        raise Abort(f"`format` must have columns 'field' and 'column'; found {list(out.columns)}.")
    if "unit" not in out.columns:
        out["unit"] = "-"
    out = out[["field", "column", "unit"]].astype(str).apply(lambda s: s.str.strip())
    out.loc[out["column"].isin(["", "nan", "None"]), "column"] = "-"
    out.loc[out["unit"].isin(["", "nan", "None"]), "unit"] = "-"
    allowed = STATION_FIELDS[station]
    bad = sorted(set(out["field"]) - set(allowed))
    if bad:
        raise Abort(f"Unknown field(s) for {station.upper()}: {bad}. Fields: {allowed}.")
    if out["field"].duplicated().any():
        raise Abort(f"Field(s) given twice: {sorted(out['field'][out['field'].duplicated()])}.")
    given = set(out.loc[out["column"] != "-", "field"])
    missing = [f for f in STATION_REQUIRED[station] if f not in given]
    if missing:
        raise Abort(f"The format has no column for required field(s) {missing}.")
    if station == "nedap" and not given & {"duration", "exit_time"}:
        raise Abort("A NEDAP format needs 'duration' or 'exit_time'.")
    for _, row in out.iterrows():
        t = FIELD_TYPES[row["field"]]
        u = row["unit"]
        ok = (u in ("-", "kg", "g", "auto") if t.startswith("mass")
              else u in ("-", "s", "min") if t == "duration"
              else True if t == "time" else u == "-")
        if not ok:
            raise Abort(f"Unknown unit {u!r} for {row['field']}. Masses: kg, g or auto; "
                        "duration: s or min; times: - or a strptime format.")
    extra = [f for f in allowed if f not in set(out["field"])]
    if extra:
        out = pd.concat([out, pd.DataFrame({"field": extra, "column": "-", "unit": "-"})])
    return out.set_index("field").loc[allowed].reset_index()


# ---- column specs ----------------------------------------------------------------

def resolve_spec(spec: str, header: Sequence[str]) -> list[str] | None:
    """Resolve "Tag|耳标号", "6" or "Date,Entry" against the column names."""
    if spec is None or spec in ("", "-"):
        return None
    header = [str(h) for h in header]
    key = [h.strip().lower() for h in header]
    out = []
    for part in [p.strip() for p in spec.split(",")]:
        hit = None
        for alt in [a.strip() for a in part.split("|")]:
            if alt in header:
                hit = alt
            elif alt.lower() in key:
                hit = header[key.index(alt.lower())]
            elif re.fullmatch(r"[0-9]+", alt) and 1 <= int(alt) <= len(header):
                hit = header[int(alt) - 1]
            if hit is not None:
                break
        if hit is None:
            return None
        out.append(hit)
    return out


def format_fits(fmt: pd.DataFrame, header: Sequence[str], station: str) -> bool:
    found = {f for f, c in zip(fmt["field"], fmt["column"]) if resolve_spec(c, header)}
    ok = set(STATION_REQUIRED[station]) <= found
    if station == "nedap":
        ok = ok and bool(found & {"duration", "exit_time"})
    return ok


def detect_station(data: pd.DataFrame) -> str:
    header = list(data.columns)
    is_nedap = format_fits(builtin_format("nedap"), header, "nedap")
    is_fire = format_fits(builtin_format("fire"), header, "fire")
    if is_nedap and not is_fire:
        return "nedap"
    if is_fire and not is_nedap:
        return "fire"
    raise Abort(
        "Cannot detect the station type from the column names.\n"
        "  NEDAP export columns: responder, location, visit_time, duration, feed_intake, weight.\n"
        "  FIRE export columns: Tag, Location, Date, Entry, Exit, Ent Wt, Ext Wt, Consumed, Weight.\n"
        "  Set `station`, and `format` if the columns have other names (see station_format())."
    )


# ---- value conversion ------------------------------------------------------------

def _as_text(x: pd.Series) -> pd.Series:
    out = x.astype("string").str.strip()
    out = out.mask(out == "")
    # numbers read as floats (e.g. from Excel) lose their ".0"
    return out.str.replace(r"^(-?\d+)\.0+$", r"\1", regex=True).astype(object).where(out.notna(), None)


def _as_number(x: pd.Series, field: str, source: str) -> pd.Series:
    if pd.api.types.is_numeric_dtype(x):
        return x.astype(float)
    txt = x.astype("string").str.strip()
    y = pd.to_numeric(txt, errors="coerce")
    bad = txt.notna() & (txt != "") & y.isna()
    if bad.any():
        ex = list(pd.unique(txt[bad]))[:3]
        raise Abort(f"Field '{field}' in {source} has values that are not numbers: {ex}. "
                    "Check the column in the format (see station_format()).")
    return y.astype(float)


def _to_unit(x: pd.Series, unit: str, target: str) -> pd.Series:
    if unit in ("-", "auto"):
        if unit == "-":
            unit = target
        else:
            pos = x[(x > 0) & x.notna()]
            unit = "kg" if len(pos) > 0 and pos.median() < 1000 else "g"
    if unit == target:
        return x
    return x * 1000 if unit == "kg" else x / 1000


# Time zone notes of the current read, printed once by read_station() /
# prep_visits().
TZ_NOTES: set[str] = set()

_TZ_MARK = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


def resolve_time_zone(time_zone="local"):
    """The time zone to show visit times in: "local" (this computer), or a
    name such as "Asia/Shanghai" or "UTC"."""
    if time_zone is None or time_zone == "local":
        return datetime.datetime.now().astimezone().tzinfo
    m = re.fullmatch(r"(?:UTC)?([+-])(\d{1,2}):?(\d{2})?", str(time_zone).strip())
    if m:   # a fixed offset such as "+08:00" or "UTC+8": no time zone data needed
        mins = int(m.group(2)) * 60 + int(m.group(3) or 0)
        return datetime.timezone(datetime.timedelta(minutes=mins if m.group(1) == "+" else -mins))
    try:
        pd.Timestamp("2024-01-01", tz=time_zone)
    except Exception as e:  # noqa: BLE001
        raise Abort(f"Unknown time zone {time_zone!r}; use 'local' or a name such as 'Asia/Shanghai'.") from e
    return time_zone


def _tz_label(tz) -> str:
    if isinstance(tz, str):
        return tz
    off = datetime.datetime.now(tz).utcoffset() or datetime.timedelta(0)
    mins = int(off.total_seconds() // 60)
    sign = "+" if mins >= 0 else "-"
    return f"UTC{sign}{abs(mins) // 60:02d}:{abs(mins) % 60:02d}"


def clock_time(x: pd.Series, time_zone="local") -> pd.Series:
    """Date-times as time-zone naive clock times.

    Time-zone aware values (e.g. read from ``2025-01-24T00:34:17Z``) are
    converted to the clock time of ``time_zone`` first, so that a day runs
    from local midnight to midnight: 00:34 UTC becomes 08:34 in Beijing.
    """
    if isinstance(x.dtype, pd.DatetimeTZDtype):
        tz = resolve_time_zone(time_zone)
        if str(x.dt.tz) != str(tz):
            TZ_NOTES.add(f"Visit times with time zone {x.dt.tz} converted to {_tz_label(tz)}"
                         + (" (the time zone of this computer)" if time_zone in (None, "local") else ""))
        return x.dt.tz_convert(tz).dt.tz_localize(None)
    return pd.to_datetime(x)


def _parse_time(cols: pd.DataFrame, unit: str, field: str, source: str,
                time_zone="local") -> pd.Series:
    if cols.shape[1] == 1 and pd.api.types.is_datetime64_any_dtype(cols.iloc[:, 0]):
        return clock_time(cols.iloc[:, 0], time_zone).astype("datetime64[ns]")

    def piece(s: pd.Series, k: int) -> pd.Series:
        if pd.api.types.is_datetime64_any_dtype(s):
            s = clock_time(s, time_zone)
            return s.dt.strftime("%Y-%m-%d" if k == 0 else "%H:%M:%S")
        return s.astype("string").str.strip()

    parts = [piece(cols.iloc[:, k], k) for k in range(cols.shape[1])]
    txt = parts[0]
    for p in parts[1:]:
        txt = txt + " " + p
    txt = txt.mask(txt.isna() | txt.str.contains(r"(?:^|\s)(?:NA|nan|<NA>)(?:\s|$)", regex=True) | (txt == ""))
    present = txt.notna()
    if unit != "-":
        out = pd.to_datetime(txt, format=unit, errors="coerce")
    else:
        out = None
        first = txt[present]
        # the format that reads most of the first values (a few broken values
        # must not hide the format: they are reported below, the rest is read)
        sample = first.head(200)
        best, best_ok = None, 0.0
        for fmt in TIME_FORMATS:
            ok = pd.to_datetime(sample, format=fmt, errors="coerce").notna().mean() if len(sample) else 0.0
            if ok > best_ok:
                best, best_ok = fmt, ok
        if best is not None and best_ok >= 0.9:
            out = pd.to_datetime(txt, format=best, errors="coerce")
        if out is None and len(first):
            # ISO 8601: 2025-01-24T00:34:17Z, 2025-01-24T08:34:17+08:00, ...
            if sample.str.contains("T").mean() >= 0.9 or sample.str.contains(_TZ_MARK).mean() >= 0.9:
                aware = sample.str.contains(_TZ_MARK).mean() >= 0.9
                try:
                    out = pd.to_datetime(txt, format="ISO8601", errors="coerce", utc=aware)
                except (ValueError, TypeError):
                    out = None
                if out is not None and aware:
                    out = clock_time(out, time_zone)
        if out is None:
            out = pd.Series(pd.NaT, index=txt.index)
    bad = present & out.isna()
    if bad.any():
        ex = list(txt[bad].head(2))
        col = " + ".join(f"'{c}'" for c in cols.columns)
        raise Abort(f"Field '{field}' (column {col}) in {source}: cannot read {int(bad.sum())} value(s) as time, "
                    f"e.g. {ex}. Give the time format as unit in the station format, "
                    "e.g. '%d/%m/%Y %H:%M:%S'.")
    return out.astype("datetime64[ns]")


def apply_format(dt: pd.DataFrame, fmt: pd.DataFrame, station: str, source: str = "data",
                 time_zone="local") -> pd.DataFrame:
    """Map the columns of one export to the standard fields."""
    header = list(dt.columns)
    n = len(dt)
    out = pd.DataFrame(index=pd.RangeIndex(n))
    dt = dt.reset_index(drop=True)
    missing_req = []
    for field, column, unit in zip(fmt["field"], fmt["column"], fmt["unit"]):
        cols = resolve_spec(column, header)
        if cols is None:
            if column != "-" and field in STATION_REQUIRED[station]:
                missing_req.append(f"{field} ({column})")
            continue
        t = FIELD_TYPES[field]
        if t == "text":
            val = _as_text(dt[cols[0]])
        elif t == "time":
            val = _parse_time(dt[cols], unit, field, source, time_zone)
        elif t == "duration":
            val = _as_number(dt[cols[0]], field, source) * (60 if unit == "min" else 1)
        elif t == "mass_g":
            val = _to_unit(_as_number(dt[cols[0]], field, source), unit, "g")
        else:
            val = _to_unit(_as_number(dt[cols[0]], field, source), unit, "kg")
        out[field] = val.values
    if station == "nedap" and not {"duration", "exit_time"} & set(out.columns):
        missing_req.append("duration or exit_time")
    if missing_req:
        raise Abort(f"{source} has no column for required field(s): {missing_req}.\n"
                    f"  Columns in the data: {header}.\n"
                    f"  Is station = '{station}' correct? For other column names give a "
                    "`format` (see station_format()).")
    for col in STD_COLS:
        if col not in out.columns:
            if col in ("entry_time", "exit_time"):
                out[col] = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")
            elif col in ("responder", "location"):
                out[col] = None
            else:
                out[col] = np.nan
    order = STD_COLS + (["breed"] if "breed" in out.columns else [])
    return out[order]


# ---- reading files -------------------------------------------------------------------

def resolve_files(files, pattern: str = DEFAULT_PATTERN) -> list[Path]:
    if isinstance(files, (str, os.PathLike)):
        files = [files]
    files = [Path(f) for f in files]
    if not files:
        raise Abort("`files` must be file paths or a folder.")
    if len(files) == 1 and files[0].is_dir():
        folder = files[0]
        rx = re.compile(pattern, re.IGNORECASE)
        found = sorted(p for p in folder.rglob("*") if p.is_file() and rx.search(p.name))
        if not found:
            raise Abort(f"No files matching {pattern!r} in {folder}.")
        return found
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise Abort(f"File(s) not found: {missing}.")
    names = [f.name for f in files]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise Abort(f"File names must be unique: {dup}.")
    return files


def _sniff_sep(path: Path) -> str:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        head = f.read(64 * 1024)
    try:
        return csv.Sniffer().sniff(head.splitlines()[0] if head else ",", delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def read_raw_file(path: Path, sheet=0) -> pd.DataFrame:
    """Read one export with every column as text (keeps leading zeros)."""
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return pd.read_excel(path, sheet_name=sheet, dtype=str)
    if ext == ".xls":
        raise Abort(f"{path.name}: .xls files are not supported; save the file as .xlsx or .csv.")
    encodings = ["utf-8-sig", "gb18030"]
    last = None
    for enc in encodings:
        try:
            return pd.read_csv(path, sep=_sniff_sep(path), dtype=str, encoding=enc,
                               keep_default_na=True, skipinitialspace=True)
        except UnicodeDecodeError as e:
            last = e
    raise Abort(f"Cannot read {path.name}: {last}")


def read_station(files, station: str | None = None, format=None,
                 pattern: str = DEFAULT_PATTERN, sheet=0, time_zone: str = "local",
                 verbose: int = 1) -> pd.DataFrame:
    """Read NEDAP or FIRE exports into one standard table.

    Args:
        files: A folder (all files matching ``pattern``, also in subfolders)
            or one or more file paths. CSV and TXT (separator detected) and
            Excel ``.xlsx`` files are read.
        station: ``"nedap"``, ``"fire"`` or ``None`` to detect the type from
            the column names of the first file.
        format: ``None`` for the built-in format, or a station format: the
            path of a tab-separated format file, a DataFrame with columns
            ``field``, ``column`` and ``unit``, or a dict ``{field: column}``.
            See [station_format()][tidypptsdm.station_format].
        pattern: Regular expression for file names when ``files`` is a folder.
        sheet: Sheet name or index for Excel files.
        time_zone: Times written with a time zone, such as
            ``2025-01-24T00:34:17Z`` (UTC), are converted to the clock time of
            this time zone, so that days run from local midnight to midnight.
            ``"local"`` (default): the time zone of this computer; or a name
            such as ``"Asia/Shanghai"``. Times without a time zone are taken
            as they are.
        verbose: 0 (silent), 1 (summary) or 2 (details per file).

    Returns:
        A DataFrame with the standard fields (feed intake in g, body weight
        in kg, duration in s) plus ``source_file``. ``df.attrs["station"]``
        holds the station type.
    """
    with local_verbose(verbose):
        paths = resolve_files(files, pattern)
        if station is not None:
            station = check_station(station)
        if format is not None and station is None:
            raise Abort("Set `station` when `format` is given.")
        msg(f"Reading {plural(len(paths), 'file')}", "h1")
        tables = {}
        for p in paths:
            t = read_raw_file(p, sheet)
            msg(f"{p.name}: {len(t):,} rows, {t.shape[1]} columns", "info", level=2)
            tables[p.name] = t
        if station is None:
            station = detect_station(next(iter(tables.values())))
            msg(f"Detected station type '{station}'", "info")
        fmt = as_station_format(format, station) if format is not None else builtin_format(station)
        resolve_time_zone(time_zone)
        TZ_NOTES.clear()
        parts = []
        for name, t in tables.items():
            std = apply_format(t, fmt, station, source=name, time_zone=time_zone)
            std["source_file"] = name
            parts.append(std)
        out = pd.concat(parts, ignore_index=True)
        for note in sorted(TZ_NOTES):
            msg(note, "info")
        out.attrs["station"] = station
        out.attrs["ppt_standard"] = True
        msg(f"Read {len(out):,} rows from {plural(len(paths), 'file')} ({station.upper()})", "success")
        return out
