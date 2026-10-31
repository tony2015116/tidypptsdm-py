"""Entry point of the exe: without arguments the desktop app opens;
with arguments it is the command line (`tidypptsdm.exe run ...`)."""

import multiprocessing
import sys

from tidypptsdm.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
