"""Install LM1 service 0.30.0 and its verified dual OV9281 profile on the Pi.

Run as root: python3 setup-dual-camera-v1.0.0.py /path/to/raspberry_pi
The enclosure's lower impact camera must be CAM0, with the upper camera on CAM1.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

if os.geteuid() != 0:
    raise SystemExit('Run this setup with sudo on the Raspberry Pi.')
source = Path(sys.argv[1]).resolve()
names = ['camera_source.py', 'ball_detector.py', 'pinpoint_protocol.py', 'pinpoint_ble.py']
for name in names:
    if not (source / name).is_file():
        raise SystemExit('Missing service file: ' + name)
supported = ('SERVICE_VERSION = "0.30.0"', 'SERVICE_VERSION = "0.31.0"')
if not any(version in (source / 'pinpoint_protocol.py').read_text() for version in supported):
    raise SystemExit('This setup requires service 0.30.0 or 0.31.0.')
backup = Path('/var/lib/pinpoint/backups') / ('pre-dual-0.30.0-%d' % time.time_ns())
backup.mkdir(parents=True, mode=0o700)
target = Path('/opt/pinpoint')
environment = Path('/etc/default/pinpoint')
for name in names:
    shutil.copy2(target / name, backup / name)
shutil.copy2(environment, backup / 'pinpoint.env')
shutil.copy2('/boot/firmware/config.txt', backup / 'config.txt')
settings = {'PINPOINT_DUAL_CAMERA': 'true', 'PINPOINT_CAMERA_SOURCE': 'csi',
            'PINPOINT_CAMERA_INDEX': '0', 'PINPOINT_SECONDARY_CAMERA_INDEX': '1',
            'PINPOINT_CAMERA_RESOLUTION': '640x400', 'PINPOINT_CAMERA_BIT_DEPTH': '10',
            'PINPOINT_CAMERA_FPS': '242', 'PINPOINT_CAMERA_SYNC_TOLERANCE_US': '250'}
lines = [line for line in environment.read_text().splitlines()
         if line.split('=', 1)[0] not in settings]
lines += ['# Dual OV9281 profile v1.0.0: lower CAM0 / upper CAM1; verified 242 fps']
lines += [key + '=' + value for key, value in settings.items()]
subprocess.run(['systemctl', 'stop', 'pinpoint'], check=True)
try:
    for name in names:
        shutil.copy2(source / name, target / name)
    environment.write_text('\n'.join(lines) + '\n')
    subprocess.run(['systemctl', 'start', 'pinpoint'], check=True)
except Exception:
    for name in names:
        shutil.copy2(backup / name, target / name)
    shutil.copy2(backup / 'pinpoint.env', environment)
    subprocess.run(['systemctl', 'restart', 'pinpoint'], check=False)
    raise
print('Installed service 0.30.0, dual-camera profile v1.0.0. Backup: ' + str(backup))
