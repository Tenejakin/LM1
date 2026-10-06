"""ESP32 wiring diagnostic 0.1.0; no camera-trigger enable."""
import serial,time
p=serial.Serial('/dev/ttyACM0',115200,timeout=.2,write_timeout=2)
time.sleep(.5)
for cmd in ('help','show','strobe on','ping'):
    p.write((cmd+'\n').encode());time.sleep(.3);print(cmd,p.read(8000).decode(errors='replace'),flush=True)
for _ in range(5):
    p.write(b'ping\n');time.sleep(.7);print(p.read(4000).decode(errors='replace'),flush=True)
p.write(b'strobe off\n');p.close()
