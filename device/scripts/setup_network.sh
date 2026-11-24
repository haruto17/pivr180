#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

sudo raspi-config nonint do_hostname pivr180

sudo install -m 644 networkmanager/pivr180-eth0.conf /etc/NetworkManager/conf.d/pivr180-eth0.conf

# Not left to a default route for multicast: the direct connection has none, and rpi.sync joins its multicast group without naming an interface.
set -- \
    connection.interface-name eth0 \
    connection.autoconnect yes \
    connection.autoconnect-priority -100 \
    ipv4.method shared \
    ipv4.addresses 10.42.1.1/24 \
    ipv4.routes 224.0.0.0/4
# Not activated or reapplied here: switching eth0 to the direct connection, or reapplying it, would drop the SSH session running this script.
if nmcli connection show pivr180-eth-direct > /dev/null 2>&1; then
    # Not delete and add: deleting the active profile drops an SSH session over the direct connection before it is added back.
    sudo nmcli connection modify pivr180-eth-direct "$@"
else
    sudo nmcli connection add type ethernet con-name pivr180-eth-direct "$@"
fi

# Not deleted first: deleting the active access point drops an SSH session over it, which would stop this script before the rest is saved.
if nmcli connection show pivr180-ap > /dev/null 2>&1; then
    sudo nmcli connection delete pivr180-ap
fi
echo "Hostname is set to pivr180, the pivr180-eth-direct profile is saved and pivr180-ap is removed. Reboot to apply."
