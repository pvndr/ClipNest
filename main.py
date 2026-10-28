"""ClipNest entry point.

Keep this file thin: it only hands control to :mod:`clipnest.app`.
Run with:  python main.py
"""

from clipnest.app import main

if __name__ == "__main__":
    raise SystemExit(main())
