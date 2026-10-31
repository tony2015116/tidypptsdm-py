"""Tcl/Tk set-up and diagnosis for the desktop app (mainly the frozen exe)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def bundle_dir() -> Path | None:
    """Folder with the bundled files of the PyInstaller exe, else None."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


def setup_tcl_tk() -> None:
    """Point Tcl/Tk to the bundled script folders before tkinter starts.

    TCL_LIBRARY / TK_LIBRARY set by another program (R, Anaconda, QGIS ...)
    would make the bundled Tk load scripts of another version.
    """
    b = bundle_dir()
    if b is None:
        return
    if os.name == "nt":
        # Load the bundled Tcl/Tk DLLs by full path first. Otherwise Windows
        # may pick tcl86t.dll / tk86t.dll of another program on the PATH
        # (Anaconda, QGIS ...), whose version does not match the bundled
        # scripts ("Can't find a usable tk.tcl").
        import ctypes
        try:
            os.add_dll_directory(str(b))
        except (OSError, AttributeError):
            pass
        for name in ("tcl86t.dll", "tk86t.dll"):
            dll = b / name
            if dll.exists():
                try:
                    ctypes.WinDLL(str(dll))
                except OSError:
                    pass
    for var, sub in (("TCL_LIBRARY", "_tcl_data"), ("TK_LIBRARY", "_tk_data")):
        d = b / sub
        if d.is_dir():
            os.environ[var] = str(d)
        else:
            os.environ.pop(var, None)


def _required_tk_version(tk_dir: Path) -> str:
    try:
        for line in (tk_dir / "tk.tcl").read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
            if "package require" in line and "Tk" in line:
                return line.strip()
    except OSError as e:
        return f"cannot read tk.tcl: {e}"
    return "no 'package require Tk' line"


def _loaded_dlls() -> list[str]:
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    out = []
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetModuleHandleW.restype = wintypes.HMODULE
    k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k32.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    for name in ("tcl86t.dll", "tk86t.dll", "tcl90.dll", "tk90.dll"):
        h = k32.GetModuleHandleW(name)
        if h:
            buf = ctypes.create_unicode_buffer(1024)
            k32.GetModuleFileNameW(h, buf, 1024)
            out.append(f"{name} loaded from {buf.value}")
    return out


def diagnose() -> tuple[bool, list[str]]:
    """Try to start Tk and the app window. Returns (ok, report lines)."""
    lines = [f"python {sys.version.split()[0]} frozen={getattr(sys, 'frozen', False)}",
             f"executable {sys.executable}"]
    b = bundle_dir()
    if b is not None:
        lines.append(f"bundle {b}")
        for sub in ("_tcl_data", "_tk_data"):
            d = b / sub
            n = len(list(d.rglob("*"))) if d.is_dir() else 0
            lines.append(f"{sub}: {'present' if d.is_dir() else 'MISSING'}, {n} files")
        lines.append(f"tk.tcl: {_required_tk_version(b / '_tk_data')}")
        if os.name == "nt":
            for name in ("tcl86t.dll", "tk86t.dll", "_tkinter.pyd"):
                lines.append(f"bundled {name}: {'present' if (b / name).exists() else 'MISSING'}")
    for var in ("TCL_LIBRARY", "TK_LIBRARY"):
        lines.append(f"{var}={os.environ.get(var, '')}")
    ok = True
    try:
        import tkinter as tk
        import _tkinter
        lines.append(f"_tkinter TK_VERSION={_tkinter.TK_VERSION} TCL_VERSION={_tkinter.TCL_VERSION}")
        root = tk.Tk()
        root.withdraw()
        lines.append(f"Tk started: patchlevel {root.tk.call('info', 'patchlevel')}, "
                     f"tk_library {root.tk.eval('set tk_library')}")
        from .gui import App
        App(root)
        root.update()
        lines.append("app window built: ok")
        root.destroy()
    except Exception as e:  # noqa: BLE001 - this is a diagnosis
        ok = False
        lines.append(f"ERROR {type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}")
    lines += _loaded_dlls()
    return ok, lines


def show_error(title: str, text: str) -> None:
    """A message box that does not need Tk (Windows), else stderr."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    elif sys.stderr is not None:
        sys.stderr.write(f"{title}\n{text}\n")
