#!/usr/bin/env bash
# Game Dev OS - one-step local setup for macOS / Linux.
# Usage:  ./setup.sh   (or: bash setup.sh)
# Creates .venv (if missing), upgrades pip, installs requirements.txt,
# and checks that the app imports cleanly.

set -euo pipefail
cd "$(dirname "$0")"

VENV_DIR=".venv"
VENV_PY="$VENV_DIR/bin/python"

if [ ! -x "$VENV_PY" ]; then
  PYTHON=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && \
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
      PYTHON="$candidate"
      break
    fi
  done
  if [ -z "$PYTHON" ]; then
    echo "Python 3.10+ not found. Install it from https://www.python.org/downloads/ and re-run." >&2
    exit 1
  fi
  echo "Creating virtual environment in $VENV_DIR ..."
  "$PYTHON" -m venv "$VENV_DIR"
else
  echo "Using existing virtual environment in $VENV_DIR"
fi

echo "Upgrading pip ..."
"$VENV_PY" -m pip install --upgrade pip

echo "Installing requirements.txt (rembg/onnxruntime are large; this can take a few minutes) ..."
"$VENV_PY" -m pip install -r requirements.txt

echo "Verifying install ..."
"$VENV_PY" -c "import flask, cv2, numpy, requests, imageio_ffmpeg, rembg; import app; print('All packages OK')"

echo
echo "Setup complete. To start the app:"
echo "  source .venv/bin/activate"
echo "  python app.py"
echo "Then open http://localhost:5000"
