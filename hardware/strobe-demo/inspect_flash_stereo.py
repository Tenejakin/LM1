"""Read-only stereo rejection evidence 0.1.0."""
import json,sys,math
from pathlib import Path
import cv2,numpy as np
sys.path.insert(0,'/opt/pinpoint')
from stereo_check import _camera,_ray,_triangulate
from stereo_calibration import fixed_secondary_pose

root=Path(sys.argv[1]);summary=json.loads((root/'summary.json').read_text())
record=json.loads((root/'review.json').read_text())
lenses=[json.loads(Path('/var/lib/pinpoint/'+name).read_text()) for name in ('intrinsics.json','intrinsics-secondary.json')]
inputs=[(np.array(l['cameraMatrix']),np.array(l['distCoeffs'])) for l in lenses]
rotation=np.array([[1,0,0],[0,0,-1],[0,1,0]])
lower_input=(*inputs[0],rotation,np.zeros(3));pose=fixed_secondary_pose(lower_input,inputs[1],(640,400),(0,1))
cameras=[_camera(*lower_input),_camera(*inputs[1],pose['rotation'],pose['translation'])]
for frame,first in [(0,summary['ballReferences'][0][:2])]+[(p['frame'],p['point'][:2]) for p in record['ball']['track']]:
    raw=cv2.imread(str(root/'cam1'/f'raw-{frame:03}.png'),-1)
    image=np.clip((raw.astype('float32')/64-18)/4,0,255).astype('uint8')
    circles=cv2.HoughCircles(cv2.medianBlur(image,5),cv2.HOUGH_GRADIENT,1,30,param1=60,param2=18,minRadius=14,maxRadius=47)
    candidates=[] if circles is None else list(circles[0])
    for contour in cv2.findContours((image>150).astype('uint8')*255,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
        area=cv2.contourArea(contour);per=cv2.arcLength(contour,True);r=math.sqrt(area/math.pi)
        if per>0 and 4*math.pi*area/per**2>.75 and 14<r<47:
            m=cv2.moments(contour);candidates.append((m['m10']/m['m00'],m['m01']/m['m00'],r))
    evidence=[]
    for x,y,r in candidates:
        point,gap=_triangulate(_ray(cameras[0],first),_ray(cameras[1],(float(x),float(y))))
        depths=[float((c['R']@point+c['t'])[2]) for c in cameras]
        expected=.021335*cameras[1]['K'][0,0]/depths[1]
        evidence.append(dict(pixel=[float(x),float(y)],radius=float(r),gapMm=round(gap*1000,2),
                             depths=depths,radiusError=round(float(r/expected-1),3)))
    print(json.dumps(dict(frame=frame,primary=list(first),candidates=evidence)))
