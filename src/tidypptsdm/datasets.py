"""Example datasets: raw exports of NEDAP and FIRE stations.

The same data as ``tidypptsda::nedap`` and ``tidypptsda::fire`` in R.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pandas as pd

from ._messages import Abort


def load_example(station: str = "nedap") -> pd.DataFrame:
    """Load an example export.

    Args:
        station: ``"nedap"``: 31,863 visits at two NEDAP stations, 30 pigs,
            2024-02-19 to 2024-05-25. Body weight in g, duration in s,
            ``responder`` empty for 211 unidentified visits.
            ``"fire"``: 9,794 visits at two FIRE stations, 26 pigs,
            2023-12-19 to 2024-02-22. Masses in kg, ``Tag`` 0 for 51
            unidentified visits; 68 visits cross midnight.

    Returns:
        The raw export as a DataFrame, as read from the CSV file (all
        columns as text, like [read_station()][tidypptsdm.read_station]).
    """
    if station not in ("nedap", "fire"):
        raise Abort(f"`station` must be 'nedap' or 'fire', not {station!r}.")
    with resources.as_file(resources.files("tidypptsdm") / "data" / f"{station}.csv.gz") as f:
        return pd.read_csv(f, dtype=str)


def write_example(folder, station: str = "nedap") -> Path:
    """Write an example export as a CSV file into ``folder``, to try the
    functions that read files (``run_monitor(folder)``, the GUI).

    Returns:
        The path of the written file.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{station}_example.csv"
    load_example(station).to_csv(out, index=False)
    return out
