#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

uv venv --clear --system-site-packages --python /usr/bin/python3
uv sync
uv run python -c "import picamera2; from libcamera import controls; controls.rpi.SyncModeEnum.Server"
echo "picamera2 is available in $(pwd)/.venv"
