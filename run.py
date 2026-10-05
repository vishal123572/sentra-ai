#!/usr/bin/env python3
import sys

if sys.version_info < (3, 10):
    raise SystemExit("SAT-SA requires Python 3.10 or newer.")

from app.server import main

if __name__ == "__main__":
    main()
