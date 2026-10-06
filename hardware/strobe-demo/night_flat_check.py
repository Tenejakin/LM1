"""Steady-IR camera diagnostic 0.1.0; raw capture with measured exposure."""
import json,time
from pathlib import Path
import cv2,numpy as np,serial
from picamera2 import Picamera2
out=Path('/home/lm1/night-flat-v0.1.0');out.mkdir(exist_ok=True)
with serial.Serial('/dev/ttyACM0',115200,timeout=.2) as port:
    time.sleep(.5)
    for command in ('trig off','mode flat','led searching'):
        port.write((command+'\n').encode());time.sleep(.2);port.read(4096)
    for j in (0,1):
        cam=Picamera2(j)
        try:
            cam.configure(cam.create_video_configuration(main={'size':(640,400),'format':'YUV420'},raw={'size':(640,400),'format':'R10'},sensor={'output_size':(640,400),'bit_depth':10},controls={'FrameRate':50,'AeEnable':False,'ExposureTime':19500,'AnalogueGain':4.},buffer_count=6))
            cam.start()
            for _ in range(15):
                req=cam.capture_request()
                try:raw=req.make_array('raw').view('<u2')[:,:640].copy();meta=req.get_metadata()
                finally:req.release()
            counts=raw.astype(float)/64
            cv2.imwrite(str(out/f'cam{j}-raw.png'),raw)
            cv2.imwrite(str(out/f'cam{j}.jpg'),np.clip((counts-16)/4,0,255).astype('uint8'))
            print(json.dumps({'camera':j,'exposureUs':meta['ExposureTime'],'gain':meta['AnalogueGain'],'rawCountsPercentiles':np.percentile(counts,[1,50,99,100]).tolist()}),flush=True)
        finally:cam.stop();cam.close()
