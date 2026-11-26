#!/bin/sh
set -eu

sudo raspi-config nonint do_hostname pivr180
echo "Hostname is set to pivr180. Reboot to apply."
