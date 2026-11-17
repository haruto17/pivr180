#!/bin/sh
set -eu

passphrase=${PIVR180_AP_PASSPHRASE:-}
if [ ${#passphrase} -lt 8 ] || [ ${#passphrase} -gt 63 ]; then
    echo "Set PIVR180_AP_PASSPHRASE to the access point passphrase (8 to 63 characters)." >&2
    exit 1
fi

sudo raspi-config nonint do_hostname pivr180

set -- \
    connection.interface-name wlan0 \
    802-11-wireless.ssid pivr180 \
    connection.autoconnect yes \
    connection.autoconnect-priority -100 \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    ipv4.method shared \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.proto rsn \
    wifi-sec.pairwise ccmp \
    wifi-sec.group ccmp \
    wifi-sec.psk "$passphrase"
# Not activated or reapplied here: switching wlan0 to the access point, or reapplying it, would drop the SSH session running this script.
if nmcli connection show pivr180-ap > /dev/null 2>&1; then
    # Not delete and add: deleting the active profile drops an SSH session over the access point before it is added back.
    sudo nmcli connection modify pivr180-ap "$@"
else
    sudo nmcli connection add type wifi con-name pivr180-ap "$@"
fi
echo "Hostname is set to pivr180 and the pivr180-ap profile is saved. Reboot to apply."
