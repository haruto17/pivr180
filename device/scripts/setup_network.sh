#!/bin/sh
set -eu

passphrase=${PIVR180_AP_PASSPHRASE:-}
if [ ${#passphrase} -lt 8 ] || [ ${#passphrase} -gt 63 ]; then
    echo "Set PIVR180_AP_PASSPHRASE to the access point passphrase (8 to 63 characters)." >&2
    exit 1
fi

sudo raspi-config nonint do_hostname pivr180

if nmcli connection show pivr180-ap > /dev/null 2>&1; then
    sudo nmcli connection delete pivr180-ap
fi
# Not activated here: switching wlan0 to the access point would drop the SSH session running this script.
sudo nmcli connection add type wifi ifname wlan0 con-name pivr180-ap ssid pivr180 \
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
echo "Hostname is set to pivr180 and the pivr180-ap profile is added. Reboot to apply."
