"""Console messages with three verbosity levels, as in the R packages.

0: silent, 1: summary (default), 2: details. Messages go to stderr so that
the standard output stays free for data.
"""

from __future__ import annotations

import contextlib
import sys
from typing import Iterator

_state = {"verbose": 1}

_SYMBOLS = {
    "info": "i",
    "success": "v",
    "warning": "!",
    "danger": "x",
}


class Abort(ValueError):
    """Error raised for bad input, with a message meant for the user."""


def check_verbose(verbose: int) -> int:
    if verbose not in (0, 1, 2) or isinstance(verbose, bool):
        raise Abort("`verbose` must be 0 (silent), 1 (summary) or 2 (details).")
    return int(verbose)


@contextlib.contextmanager
def local_verbose(verbose: int) -> Iterator[int]:
    """Set the verbosity until the block exits."""
    verbose = check_verbose(verbose)
    old = _state["verbose"]
    _state["verbose"] = verbose
    try:
        yield verbose
    finally:
        _state["verbose"] = old


def current_verbose() -> int:
    return _state["verbose"]


def _write(text: str) -> None:
    stream = sys.stderr
    if stream is None:  # a windowed exe without console and without a log file
        return
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:  # e.g. a Windows console in a legacy code page
        enc = getattr(stream, "encoding", None) or "ascii"
        stream.write(text.encode(enc, "replace").decode(enc) + "\n")
    stream.flush()


def msg(text: str, kind: str = "info", level: int = 1) -> None:
    """Print a message if the verbosity is at least `level`."""
    if _state["verbose"] < level:
        return
    if kind == "h1":
        line = "-" * max(0, 72 - len(text) - 4)
        _write(f"\n-- {text} {line}")
    else:
        _write(f"{_SYMBOLS.get(kind, 'i')} {text}")


def bullets(lines: list[tuple[str, str]], level: int = 1) -> None:
    """Print indented lines, each with a kind ("danger", "warning", ...)."""
    if _state["verbose"] < level:
        return
    for kind, text in lines:
        _write(f"  {_SYMBOLS.get(kind, '*')} {text}")


def plural(n: int, word: str, plural_word: str | None = None) -> str:
    """`3 pigs`, `1 pig`."""
    return f"{n:,} {word if n == 1 else (plural_word or word + 's')}"
