"""Stationary off/on microburst comparison 0.1.1; verify ending controller state."""
import json,time,threading
from pathlib import Path
import cv2,numpy as np,serial
from picamera2 import Picamera2
OUT=Path('/home/lm1/strobe-demo-v0.5.2/microburst-bench-v0.1.1');OUT.mkdir(parents=True,exist_ok=True)
port=serial.Serial('/dev/ttyACM0',115200,timeout=.1,write_timeout=2)
time.sleep(.5);lock=threading.Lock();done=threading.Event();report=[]
def command(line):
    with lock:
        port.reset_input_buffer();port.write((line+'\n').encode());time.sleep(.12)
        reply=port.read(4096).decode(errors='replace')
        if 'rejected:' in reply or 'ERR ' in reply:raise RuntimeError(reply)
        return reply.strip()
def heartbeat():
    while not done.wait(.5):command('ping')
def grab(cam,n):
    images=[];meta=None
    for i in range(n+12):
        request=cam.capture_request()
        try:raw=request.make_array('raw').view('<u2')[:,:640].copy();meta=request.get_metadata()
        finally:request.release()
        if i>=12:images.append(raw)
    return np.stack(images),meta
try:
    for line in ('trig off','stop','f 1 1000','rate 250','p 2','f 3 3'):command(line)
    threading.Thread(target=heartbeat,daemon=True).start()
    for index in (0,1):
        cam=Picamera2(index)
        try:
            cam.configure(cam.create_video_configuration(main={'size':(640,400),'format':'YUV420'},raw={'size':(640,400),'format':'R10'},sensor={'output_size':(640,400),'bit_depth':10},controls={'FrameRate':242,'AeEnable':False,'ExposureTime':100,'AnalogueGain':4.},buffer_count=6));cam.start()
            command('mode flat');flat,_=grab(cam,8)
            image=np.clip(np.median(flat,axis=0)/64-16,0,255).astype('uint8')
            circles=cv2.HoughCircles(cv2.GaussianBlur(image,(5,5),1),cv2.HOUGH_GRADIENT,1.2,35,param1=60,param2=20,minRadius=18,maxRadius=30)
            anchor=((253,265),(267,192))[index]
            candidates=[] if circles is None else [c for c in circles[0] if abs(c[0]-anchor[0])<85 and abs(c[1]-anchor[1])<75]
            if not candidates:raise RuntimeError(f'Camera {index}: ball not located in flat reference')
            x,y,r=min(candidates,key=lambda c:(c[0]-anchor[0])**2+(c[1]-anchor[1])**2)
            yy,xx=np.mgrid[:400,:640];mask=(xx-x)**2+(yy-y)**2<(r*.65)**2
            cam.set_controls({'ExposureTime':9})
            command('mode off');off,meta=grab(cam,180)
            for line in ('stop','f 1 1000','rate 250','p 2','f 3 3','mode strobe'):command(line)
            before=command('show');on,meta=grab(cam,600);after=command('show')
            verified=all('STROBE | rate 250' in s and '3 flashes of 2 us' in s and 'spacings (us): 3 3' in s for s in (before,after))
            a=off[:,mask].mean(axis=1)/64;b=on[:,mask].mean(axis=1)/64
            threshold=float(a.mean()+max(2.,5*a.std()))
            brightest=int(np.argmax(b));baseline=np.median(off,axis=0).astype('uint16')
            for name,raw in (('off',baseline),('brightest',on[brightest])):
                cv2.imwrite(str(OUT/f'cam{index}-{name}-raw.png'),raw)
                preview=cv2.cvtColor(np.clip((raw/64-16)*4,0,255).astype('uint8'),cv2.COLOR_GRAY2BGR)
                cv2.circle(preview,(round(float(x)),round(float(y))),round(float(r)),(0,255,0),1)
                cv2.imwrite(str(OUT/f'cam{index}-{name}.jpg'),preview)
            np.savez_compressed(OUT/f'cam{index}-ball-signals.npz',off=a,on=b)
            row={'camera':index,'ball':[float(x),float(y),float(r)],'actualExposureUs':meta['ExposureTime'],'gain':meta['AnalogueGain'],'offFrames':len(a),'onFrames':len(b),'offMeanCounts':float(a.mean()),'offStdCounts':float(a.std()),'onMedianCounts':float(np.median(b)),'onMaxCounts':float(b.max()),'brightFrameThresholdCounts':threshold,'brightFrames':int(np.sum(b>threshold)),'offFramesAboveThreshold':int(np.sum(a>threshold)),'controller':command('show')}
            row.update(controllerBefore=before,controllerAfter=after,endingPatternVerified=verified)
            report.append(row);print(json.dumps(row),flush=True)
        finally:cam.stop();cam.close()
finally:
    done.set();command('mode flat');port.close();(OUT/'report.json').write_text(json.dumps(report,indent=2))
