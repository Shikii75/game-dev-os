"""
Desktop / Electron entry — runs Flask without the debug reloader.
"""

from __future__ import annotations

import os

# Must be set before importing app (Flask reads env at run time).
os.environ.setdefault("GAME_DEV_OS_HOST", "127.0.0.1")
os.environ.setdefault("GAME_DEV_OS_PORT", "5137")
os.environ.setdefault("GAME_DEV_OS_DEBUG", "0")

# Dev / unpackaged: keep assets in project folder unless Electron sets AppData.
if not os.environ.get("GAME_DEV_OS_DATA_DIR"):
    _root = os.path.dirname(os.path.abspath(__file__))
    os.environ.setdefault("GAME_DEV_OS_DATA_DIR", _root)

from app import app  # noqa: E402


def main() -> None:
    host = os.environ.get("GAME_DEV_OS_HOST", "127.0.0.1")
    port = int(os.environ.get("GAME_DEV_OS_PORT", "5137"))
    debug = os.environ.get("GAME_DEV_OS_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    main()
