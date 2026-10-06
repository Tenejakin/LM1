#!/usr/bin/env bash
set -euo pipefail

OFFLINE=false
case "${1:-}" in
  "") ;;
  --offline) OFFLINE=true ;;
  *)
    echo "Usage: sudo ./install.sh [--offline]"
    exit 2
    ;;
esac

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer with sudo: sudo ./install.sh"
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${OFFLINE}" == true ]]; then
  if [[ ! -x /opt/pinpoint/.venv/bin/python ]]; then
    echo "Offline update needs an existing LM1 installation in /opt/pinpoint/.venv."
    exit 1
  fi
  if ! command -v nmcli >/dev/null 2>&1; then
    echo "Offline update needs NetworkManager (nmcli), which is included in current Raspberry Pi OS."
    exit 1
  fi
  if ! /opt/pinpoint/.venv/bin/python -c 'import bless' >/dev/null 2>&1; then
    echo "Offline update needs the existing Bless Python dependency."
    exit 1
  fi
  if grep -Eq '^PINPOINT_CAMERA_SOURCE="?csi"?$' /etc/default/pinpoint 2>/dev/null; then
    if ! /opt/pinpoint/.venv/bin/python -c 'import cv2, picamera2; assert hasattr(cv2, "aruco") and hasattr(cv2.aruco, "DICT_APRILTAG_36h11")' >/dev/null 2>&1; then
      echo "Offline CSI update needs python3-opencv with AprilTag support and python3-picamera2 in the existing venv."
      exit 1
    fi
  fi
else
  apt-get update
  apt-get install -y python3 python3-venv python3-opencv python3-picamera2 bluez rfkill ffmpeg v4l-utils network-manager
fi

install -d -m 0755 /opt/pinpoint
install -d -m 0755 /var/lib/pinpoint
install -m 0644 "${SCRIPT_DIR}/pinpoint_ble.py" /opt/pinpoint/pinpoint_ble.py
install -m 0644 "${SCRIPT_DIR}/pinpoint_protocol.py" /opt/pinpoint/pinpoint_protocol.py
install -m 0644 "${SCRIPT_DIR}/wifi_manager.py" /opt/pinpoint/wifi_manager.py
install -m 0644 "${SCRIPT_DIR}/ball_detector.py" /opt/pinpoint/ball_detector.py
install -m 0644 "${SCRIPT_DIR}/launch_measurements.py" /opt/pinpoint/launch_measurements.py
install -m 0644 "${SCRIPT_DIR}/flight_model.py" /opt/pinpoint/flight_model.py
install -m 0644 "${SCRIPT_DIR}/capture_quality.py" /opt/pinpoint/capture_quality.py
install -m 0644 "${SCRIPT_DIR}/club_vision.py" /opt/pinpoint/club_vision.py
install -m 0644 "${SCRIPT_DIR}/club_stereo.py" /opt/pinpoint/club_stereo.py
install -m 0644 "${SCRIPT_DIR}/exposure_calibration.py" /opt/pinpoint/exposure_calibration.py
install -m 0644 "${SCRIPT_DIR}/lens_calibration.py" /opt/pinpoint/lens_calibration.py
install -m 0644 "${SCRIPT_DIR}/stereo_calibration.py" /opt/pinpoint/stereo_calibration.py
install -m 0644 "${SCRIPT_DIR}/target_line.py" /opt/pinpoint/target_line.py
install -m 0644 "${SCRIPT_DIR}/shot_coverage.py" /opt/pinpoint/shot_coverage.py
install -m 0644 "${SCRIPT_DIR}/rig_pose.py" /opt/pinpoint/rig_pose.py
install -m 0644 "${SCRIPT_DIR}/camera_source.py" /opt/pinpoint/camera_source.py
install -m 0644 "${SCRIPT_DIR}/apriltag_calibration.py" /opt/pinpoint/apriltag_calibration.py
install -m 0644 "${SCRIPT_DIR}/stereo_check.py" /opt/pinpoint/stereo_check.py
install -m 0644 "${SCRIPT_DIR}/readiness.py" /opt/pinpoint/readiness.py
install -m 0644 "${SCRIPT_DIR}/frame_uploader.py" /opt/pinpoint/frame_uploader.py
install -m 0644 "${SCRIPT_DIR}/ogs_bridge.py" /opt/pinpoint/ogs_bridge.py
install -m 0644 "${SCRIPT_DIR}/light_controller.py" /opt/pinpoint/light_controller.py
install -m 0644 "${SCRIPT_DIR}/raw_frames.py" /opt/pinpoint/raw_frames.py
install -m 0644 "${SCRIPT_DIR}/rejection_hints.py" /opt/pinpoint/rejection_hints.py
install -m 0644 "${SCRIPT_DIR}/strobe_copies.py" /opt/pinpoint/strobe_copies.py
install -m 0644 "${SCRIPT_DIR}/requirements.txt" /opt/pinpoint/requirements.txt
rm -f /opt/pinpoint/pinpoint_server.py

# Level-rig ground (service 0.54.0): write this unit's tilt and height once, from the saved tag
# calibrations, so the tag is no longer needed. An existing rig.json is never overwritten.
if [[ ! -f /var/lib/pinpoint/rig.json ]]; then
  (cd /opt/pinpoint && /opt/pinpoint/.venv/bin/python rig_pose.py --from-tags) \
    || echo "No rig.json written (no saved tag calibration); the level rig uses default constants until 'python rig_pose.py --set PITCH HEIGHT' is run."
fi

if [[ "${OFFLINE}" == false ]]; then
  python3 -m venv --clear --system-site-packages /opt/pinpoint/.venv
  /opt/pinpoint/.venv/bin/pip install --disable-pip-version-check --upgrade pip
  /opt/pinpoint/.venv/bin/pip install --disable-pip-version-check -r /opt/pinpoint/requirements.txt
fi

if ! /opt/pinpoint/.venv/bin/python -c 'import cv2; assert hasattr(cv2, "aruco") and hasattr(cv2.aruco, "DICT_APRILTAG_36h11")' >/dev/null 2>&1; then
  echo "LM1 AprilTag calibration requires an OpenCV build with aruco/AprilTag support."
  exit 1
fi

install -m 0644 "${SCRIPT_DIR}/systemd/pinpoint.service" /etc/systemd/system/pinpoint.service
install -m 0644 "${SCRIPT_DIR}/systemd/pinpoint-ogs-bridge.service" /etc/systemd/system/pinpoint-ogs-bridge.service
rm -f /etc/avahi/services/pinpoint.service

if [[ ! -f /etc/default/pinpoint ]]; then
  install -m 0644 /dev/null /etc/default/pinpoint
  {
    echo 'PINPOINT_NAME="LM1 PRO"'
    echo 'PINPOINT_BLE_NAME="LM1 PRO"'
    echo 'PINPOINT_CAPTURE_BACKEND=simulator'
  } >> /etc/default/pinpoint
else
  sed -i 's/^PINPOINT_NAME="Pinpoint LM · Raspberry Pi"$/PINPOINT_NAME="LM1 PRO"/' /etc/default/pinpoint
  sed -i 's/^PINPOINT_BLE_NAME="Pinpoint LM"$/PINPOINT_BLE_NAME="LM1 PRO"/' /etc/default/pinpoint
fi

if ! grep -q '^PINPOINT_AUTO_BALL_DETECTION=' /etc/default/pinpoint; then
  echo 'PINPOINT_AUTO_BALL_DETECTION=true' >> /etc/default/pinpoint
fi
if ! grep -q '^PINPOINT_BALL_ROI=' /etc/default/pinpoint; then
  echo 'PINPOINT_BALL_ROI="0,0.30,0.50,0.98"' >> /etc/default/pinpoint
elif grep -Eq '^PINPOINT_BALL_ROI="?0\.05,0\.30,0\.95,0\.98"?$' /etc/default/pinpoint; then
  # Migrate only the former built-in zone. Leave user-defined placement zones alone.
  sed -i 's/^PINPOINT_BALL_ROI=.*$/PINPOINT_BALL_ROI="0,0.30,0.50,0.98"/' /etc/default/pinpoint
fi
if ! grep -q '^PINPOINT_APRILTAG_ID=' /etc/default/pinpoint; then
  echo 'PINPOINT_APRILTAG_ID=0' >> /etc/default/pinpoint
fi
if ! grep -q '^PINPOINT_APRILTAG_SIZE_MM=' /etc/default/pinpoint; then
  echo 'PINPOINT_APRILTAG_SIZE_MM=100' >> /etc/default/pinpoint
fi
if ! grep -q '^PINPOINT_CAPTURE_RETENTION=' /etc/default/pinpoint; then
  echo 'PINPOINT_CAPTURE_RETENTION=100' >> /etc/default/pinpoint
fi
if ! grep -q '^PINPOINT_BLE_PREVIEW=' /etc/default/pinpoint; then
  echo 'PINPOINT_BLE_PREVIEW=true' >> /etc/default/pinpoint
fi
if ! grep -q '^PINPOINT_BLE_PREVIEW_INTERVAL_SECONDS=' /etc/default/pinpoint; then
  echo 'PINPOINT_BLE_PREVIEW_INTERVAL_SECONDS=3' >> /etc/default/pinpoint
fi
if ! grep -q '^PINPOINT_WIFI_PROVISIONING=' /etc/default/pinpoint; then
  echo 'PINPOINT_WIFI_PROVISIONING=true' >> /etc/default/pinpoint
fi
if ! grep -q '^PINPOINT_WIFI_INTERFACE=' /etc/default/pinpoint; then
  echo 'PINPOINT_WIFI_INTERFACE=wlan0' >> /etc/default/pinpoint
fi

if ! grep -q '^PINPOINT_CAMERA_DEVICE=' /etc/default/pinpoint; then
  CAMERA_DEVICE="$(find /dev/v4l/by-id -maxdepth 1 -type l -name '*-video-index0' 2>/dev/null | sort | head -n 1 || true)"
  if [[ -n "${CAMERA_DEVICE}" ]]; then
    {
      printf 'PINPOINT_CAMERA_DEVICE="%s"\n' "${CAMERA_DEVICE}"
      echo 'PINPOINT_CAMERA_RESOLUTION=1280x720'
      echo 'PINPOINT_CAMERA_FPS=30'
      echo 'PINPOINT_EXPOSURE_US=15700'
    } >> /etc/default/pinpoint
  fi
fi

rfkill unblock bluetooth
systemctl enable --now bluetooth.service
bluetoothctl power on
systemctl daemon-reload
systemctl enable pinpoint.service
systemctl restart pinpoint.service
systemctl enable pinpoint-ogs-bridge.service
systemctl restart pinpoint-ogs-bridge.service

echo
echo "LM1 PRO BLE service is installed and running."
if [[ "${OFFLINE}" == true ]]; then
  echo "Offline update reused the existing system and Python packages."
fi
echo "Check it with: systemctl status pinpoint --no-pager"
echo "OpenGolfSim bridge: ws://<LM1 address>:3112 (systemctl status pinpoint-ogs-bridge --no-pager)"
echo "The mobile app should now discover a nearby device named LM1 PRO."
