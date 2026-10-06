"""Status LED transition check 0.1.0; finishes in searching state."""
import serial,time
p=serial.Serial('/dev/ttyACM0',115200,timeout=.15,write_timeout=2);time.sleep(1.5)
for state in ('searching','ready','processing','searching'):
    p.write(f'led {state}\n'.encode());time.sleep(.3)
    reply=p.read(4000).decode(errors='replace');print(state,reply,flush=True)
    if f'OK led={state}' not in reply:raise RuntimeError(f'No acknowledgment for {state}')
    time.sleep(2.3)
p.close()
