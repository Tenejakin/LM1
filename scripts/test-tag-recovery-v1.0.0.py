"""Offline latest-shot tag-recovery experiment v1.0.0, no capture modifications."""
from pathlib import Path
import json
import cv2
import numpy as np
root = Path(__file__).resolve().parents[1]
capture = root / 'tmp/capture-1789515962500510189'
out = root / 'output/tag-recovery-v1.0.0'
out.mkdir(parents=True, exist_ok=True)
d = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11))
clahe = cv2.createCLAHE(clipLimit=2, tileGridSize=(8,8))
results = {name:[] for name in ['raw','bilateral','bilateral-4x','clahe','nonlocal-clahe']}
for i,p in enumerate(sorted(capture.glob('frame-*.jpg'))):
    im = cv2.imread(str(p),0)
    bilateral = cv2.bilateralFilter(im,5,12,3)
    variants = {'raw':im,'bilateral':bilateral,
        'bilateral-4x':np.clip(bilateral.astype(float)*4,0,255).astype(np.uint8),
        'clahe':clahe.apply(im),
        'nonlocal-clahe':clahe.apply(cv2.fastNlMeansDenoising(im,None,3,7,21))}
    for name,image in variants.items():
        _,ids,_ = d.detectMarkers(image)
        if ids is not None and 0 in ids:
            results[name].append(i)
        if i==150:
            cv2.imwrite(str(out/(name+'.png')),image)
report={'version':'1.0.0','captureId':capture.name,'framesTested':i+1,
        'groundTagDetectedFrames':results,'detector':'OpenCV AprilTag 36h11; offline diagnostic, not live pose validation'}
(out/'report.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
