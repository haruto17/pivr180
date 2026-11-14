#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/pivr180-capture ]; then
    echo "$(pwd)/.venv/bin/pivr180-capture not found. Run ./scripts/setup_pi_venv.sh first." >&2
    exit 1
fi

unit=$(mktemp)
trap 'rm -f "$unit"' EXIT
sed -e "s|@USER@|$(id -un)|g" -e "s|@DEVICE_DIR@|$(pwd)|g" systemd/pivr180-capture.service.in > "$unit"

sudo install -m 644 "$unit" /etc/systemd/system/pivr180-capture.service
sudo systemctl daemon-reload
sudo systemctl enable pivr180-capture.service
sudo systemctl restart pivr180-capture.service
echo "pivr180-capture.service is enabled and started"
