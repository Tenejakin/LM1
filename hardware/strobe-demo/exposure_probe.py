"""Read actual minimum exposure in the demo sensor mode; probe 0.1.0."""
import json
from picamera2 import Picamera2
for index in (0,1):
    cam=Picamera2(index)
    try:
        cam.configure(cam.create_video_configuration(main={'size':(640,400),'format':'YUV420'},raw={'size':(640,400),'format':'R10'},sensor={'output_size':(640,400),'bit_depth':10},controls={'FrameRate':242,'AeEnable':False,'ExposureTime':1,'AnalogueGain':1.}))
        print(json.dumps({'camera':index,'exposureControlRange':cam.camera_controls['ExposureTime']}),flush=True)
        cam.start()
        for i in range(12):
            request=cam.capture_request()
            try:meta=request.get_metadata()
            finally:request.release()
        print(json.dumps({'camera':index,'requestedUs':1,'actualUs':meta['ExposureTime'],'frameDurationUs':meta['FrameDuration']}),flush=True)
    finally:
        cam.stop();cam.close()
