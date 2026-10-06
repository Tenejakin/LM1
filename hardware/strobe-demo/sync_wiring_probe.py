"""Trigger/strobe wiring probe 0.1.0; restores free-running cameras."""
import os,time,threading,subprocess,json
os.environ['LIBCAMERA_RPI_CONFIG_FILE']='/home/lm1/ov9281-sync-reference/ov9281_libcamera/timeout.yaml'
from picamera2 import Picamera2
import serial
tool='/home/lm1/ov9281-sync-reference/ov9281_libcamera/ov9281_trigger'
p=serial.Serial('/dev/ttyACM0',115200,timeout=.1,write_timeout=2);time.sleep(1)
cams=[];counts=[0,0];running=True
def cmd(s):
    p.write((s+'\n').encode());time.sleep(.15);r=p.read(5000).decode(errors='replace');print(s,r,flush=True)
def reader(j,c):
    while running:
        try:
            req=c.capture_request();counts[j]+=1;req.release()
        except Exception:return
def observe(label):
    before=counts[:];start=time.monotonic()
    for _ in range(4):cmd('ping');time.sleep(.35)
    print(json.dumps({'phase':label,'seconds':time.monotonic()-start,'frames':[counts[j]-before[j] for j in (0,1)]}),flush=True)
try:
    cmd('trig off');cmd('mode off');cmd('strobe on')
    for j in (0,1):
        c=Picamera2(j);cams.append(c)
        c.configure(c.create_video_configuration(main={'size':(640,400),'format':'YUV420'},sensor={'output_size':(640,400),'bit_depth':10},controls={'FrameRate':120,'AeEnable':False,'ExposureTime':1000,'AnalogueGain':1.},buffer_count=6));c.start()
        threading.Thread(target=reader,args=(j,c),daemon=True).start()
    observe('free-running')
    for bus in (10,11):subprocess.run([tool,str(bus),'1'],check=True)
    time.sleep(.3);observe('external mode, trigger off')
    for s in ('stop','f 1 1000','rate 20','tw 100','trig on','light off','go'):cmd(s)
    observe('external mode, GPIO6 trigger 20 Hz')
finally:
    cmd('trig off');cmd('stop')
    for bus in (10,11):subprocess.run([tool,str(bus),'0'])
    time.sleep(.2);running=False
    for c in cams:c.stop();c.close()
    cmd('strobe off');cmd('light on');cmd('mode flat');p.close()
