"""Three-copy illumination bench 0.1.0; preserves linear raw data."""
import json,time,threading
from pathlib import Path
import cv2,numpy as np,serial
from picamera2 import Picamera2
OUT=Path('/home/lm1/strobe-demo-v0.4.0/bench'); OUT.mkdir(parents=True,exist_ok=True)
port=serial.Serial('/dev/ttyACM0',115200,timeout=.1,write_timeout=2)
time.sleep(.5)
lock=threading.Lock(); done=threading.Event()
def command(line):
    with lock:
        port.reset_input_buffer();port.write((line+'\n').encode());time.sleep(.12)
        reply=port.read(4096).decode(errors='replace')
        if 'rejected:' in reply or 'ERR ' in reply:raise RuntimeError(reply)
        return reply
def heartbeat():
    while not done.wait(.5):command('ping')
def grab(cam):
    rows=[]
    for i in range(24):
        req=cam.capture_request()
        try:raw=req.make_array('raw').view('<u2')[:,:640].copy();meta=req.get_metadata()
        finally:req.release()
        if i>=12:rows.append(raw)
    return np.median(rows,axis=0).astype('uint16'),meta
report=[]
try:
    for line in ('trig off','stop','f 1 1000','rate 50','p 100','i 5000 6500'):print(command(line),flush=True)
    threading.Thread(target=heartbeat,daemon=True).start()
    for index in (0,1):
        cam=Picamera2(index)
        try:
            cam.configure(cam.create_video_configuration(main={'size':(640,400),'format':'YUV420'},raw={'size':(640,400),'format':'R10'},sensor={'output_size':(640,400),'bit_depth':10},controls={'FrameRate':50,'AeEnable':False,'ExposureTime':19500,'AnalogueGain':1.},buffer_count=6));cam.start()
            command('mode off');off,meta=grab(cam);cv2.imwrite(str(OUT/f'cam{index}-off-raw.png'),off)
            for pulse in (100,250,500):
                command(f'p {pulse}');command('mode strobe');on,meta=grab(cam)
                cv2.imwrite(str(OUT/f'cam{index}-p{pulse}-raw.png'),on)
                cv2.imwrite(str(OUT/f'cam{index}-p{pulse}.jpg'),np.clip(on/64-16,0,255).astype('uint8'))
                a=off.astype(float)/64;b=on.astype(float)/64
                # Fixed usual-placement ROI; report full distribution without assuming a ball is present.
                x,y=((253,265),(267,192))[index];roi=np.s_[y-35:y+35,x-60:x+60]
                row={'camera':index,'pulseUs':pulse,'exposureUs':meta['ExposureTime'],'gain':meta['AnalogueGain'],'ambientRoiP90':float(np.percentile(a[roi],90)),'onRoiP90':float(np.percentile(b[roi],90)),'addedRoiP90':float(np.percentile((b-a)[roi],90)),'roiClippedFraction':float(np.mean(b[roi]>=1000))}
                report.append(row);print(json.dumps(row),flush=True)
        finally:cam.stop();cam.close()
finally:
    done.set();command('mode flat');port.close();(OUT/'report.json').write_text(json.dumps(report,indent=2))
