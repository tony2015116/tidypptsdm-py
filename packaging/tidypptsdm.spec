# PyInstaller spec: build with `pyinstaller packaging/tidypptsdm.spec`
# (from the repository root, with the package installed: pip install .[exe]).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

here = Path(SPECPATH)
datas = collect_data_files("tidypptsdm")
icon = str(here.parent / "docs" / "assets" / "favicon.ico") if sys.platform.startswith("win") else None

a = Analysis(
    [str(here / "tidypptsdm_app.py")],
    datas=datas,
    hiddenimports=["tidypptsdm.gui", "openpyxl.cell._writer"],
    excludes=["IPython", "jupyter", "notebook", "pytest", "scipy", "PyQt5", "PyQt6", "PySide2",
              "PySide6", "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_qt5agg",
              "matplotlib.backends.backend_webagg", "matplotlib.backends.backend_gtk3agg"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="tidypptsdm",
    console=False,          # a window app; scheduled runs write a log file instead
    icon=icon,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="tidypptsdm", upx=False)
