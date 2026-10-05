"""
PyInstaller entry — seeds user AppData workspace then starts Flask.
"""

from __future__ import annotations

import os
import sys


def _bootstrap_env() -> None:
    os.environ.setdefault("GAME_DEV_OS_HOST", "127.0.0.1")
    os.environ.setdefault("GAME_DEV_OS_PORT", "5137")
    os.environ.setdefault("GAME_DEV_OS_DEBUG", "0")

    if not os.environ.get("GAME_DEV_OS_DATA_DIR"):
        base = os.path.join(os.path.expanduser("~"), "GameDevOS")
        os.environ["GAME_DEV_OS_DATA_DIR"] = base


def main() -> None:
    _bootstrap_env()

    from services import media_utils as mu

    mu.seed_user_workspace()

    from run_server import main as run_flask

    run_flask()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[game-dev-os-server] fatal: {exc}", file=sys.stderr)
        raise
