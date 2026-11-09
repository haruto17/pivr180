#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

uv venv --clear --system-site-packages --python /usr/bin/python3
uv sync --python /usr/bin/python3
# Not `uv run`: it would replace this venv before the check if .python-version differs from the OS Python.
.venv/bin/python -c "import picamera2; from libcamera import controls; controls.rpi.SyncModeEnum.Server"
echo "picamera2 is available in $(pwd)/.venv"
