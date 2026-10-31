"""tidypptsdm: daily monitoring of pig performance testing stations.

The Python version of the R package tidypptsdm: read NEDAP or FIRE exports,
compute the daily tables per station, house, pig and hour, list the alerts
of the last day, and write an HTML report and an Excel workbook.
"""

from ._messages import Abort
from ._monitor import (Monitor, monitor_hours, monitor_houses, monitor_pigs,
                       monitor_stations, run_monitor, wide_table)
from ._plots import StationPlot, plot_monitor, save_monitor_plots
from ._prep import prep_visits
from ._report import write_monitor_report
from ._schedule import monitor_to_folder, schedule_monitor, unschedule_monitor
from ._station import read_station, station_format
from ._tables import write_monitor_tables
from .datasets import load_example, write_example

from ._version import __version__

__all__ = [
    "Abort", "Monitor", "StationPlot", "load_example", "monitor_hours",
    "monitor_houses", "monitor_pigs", "monitor_stations", "monitor_to_folder",
    "plot_monitor", "prep_visits", "read_station", "run_monitor",
    "save_monitor_plots", "schedule_monitor", "station_format",
    "unschedule_monitor", "wide_table", "write_example",
    "write_monitor_report", "write_monitor_tables",
]
