#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer with sudo: sudo ./install.sh"
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

apt-get update
apt-get install -y python3 python3-venv bluez rfkill

install -d -m 0755 /opt/pinpoint
install -d -m 0755 /var/lib/pinpoint
install -m 0644 "${SCRIPT_DIR}/pinpoint_ble.py" /opt/pinpoint/pinpoint_ble.py
install -m 0644 "${SCRIPT_DIR}/pinpoint_protocol.py" /opt/pinpoint/pinpoint_protocol.py
install -m 0644 "${SCRIPT_DIR}/requirements.txt" /opt/pinpoint/requirements.txt
rm -f /opt/pinpoint/pinpoint_server.py

python3 -m venv --clear /opt/pinpoint/.venv
/opt/pinpoint/.venv/bin/pip install --disable-pip-version-check --upgrade pip
/opt/pinpoint/.venv/bin/pip install --disable-pip-version-check -r /opt/pinpoint/requirements.txt

install -m 0644 "${SCRIPT_DIR}/systemd/pinpoint.service" /etc/systemd/system/pinpoint.service
rm -f /etc/avahi/services/pinpoint.service

if [[ ! -f /etc/default/pinpoint ]]; then
  install -m 0644 /dev/null /etc/default/pinpoint
  {
    echo 'PINPOINT_NAME="Pinpoint LM · Raspberry Pi"'
    echo 'PINPOINT_BLE_NAME="Pinpoint LM"'
    echo 'PINPOINT_CAPTURE_BACKEND=simulator'
  } >> /etc/default/pinpoint
fi

rfkill unblock bluetooth
systemctl enable --now bluetooth.service
bluetoothctl power on
systemctl daemon-reload
systemctl enable pinpoint.service
systemctl restart pinpoint.service

echo
echo "Pinpoint BLE service 0.2.0 is installed and running."
echo "Check it with: systemctl status pinpoint --no-pager"
echo "The mobile app should now discover a nearby device named Pinpoint LM."
