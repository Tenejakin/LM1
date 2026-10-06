"""Launch-angle replay 0.2.0: preserve up to twelve outgoing ball positions."""
import json,math,sys
from pathlib import Path
import cv2,numpy as np

def review(root):
    summary=json.loads((root/'summary.json').read_text());camera=summary['cameras'][0]
    bx,by,r=summary['ballReferences'][0];track=[];evidence=[]
    for meta in camera['metadata']:
        if meta['SensorTimestamp']<summary['triggerSensorTimestamp']:continue
        raw=cv2.imread(str(root/'cam0'/f'raw-{meta["frame"]:03}.png'),-1).astype('float32')/64
        image=cv2.medianBlur(np.clip((raw-18)/4,0,255).astype('uint8'),5)
        circles=cv2.HoughCircles(image,cv2.HOUGH_GRADIENT,1,40,param1=60,param2=22,minRadius=int(r*.65),maxRadius=int(r*1.25))
        points=[] if circles is None else [[float(x),float(y),float(radius)] for x,y,radius in circles[0] if x>bx+r*.4 and y<by+r*.3]
        evidence.append({'frame':meta['frame'],'candidates':points})
        if not points:
            if track:break
            continue
        if len(track)<2:
            origin=track[-1]['point'] if track else [bx,by]
            choices=[p for p in points if p[0]>origin[0]]
            if not choices:continue
            point=min(choices,key=lambda p:math.hypot(p[0]-origin[0],p[1]-origin[1]))
        else:
            a,b=track[-2:];dt=meta['SensorTimestamp']-b['timestamp']
            prediction=np.array(b['point'][:2])+(np.array(b['point'][:2])-a['point'][:2])*dt/(b['timestamp']-a['timestamp'])
            point=min(points,key=lambda p:np.linalg.norm(np.array(p[:2])-prediction))
            if np.linalg.norm(np.array(point[:2])-prediction)>r:break
        track.append({'frame':meta['frame'],'timestamp':meta['SensorTimestamp'],'point':point})
        if len(track)>=12:break
    fits=[]
    for n in (2,min(4,len(track))):
        if n<2 or n>len(track) or any(f['samples']==n for f in fits):continue
        samples=track[:n];times=np.array([p['timestamp'] for p in samples],float)/1e9;xy=np.array([p['point'][:2] for p in samples])
        design=np.column_stack((times-times.mean(),np.ones(n)));coeff=np.linalg.lstsq(design,xy,rcond=None)[0]
        velocity=coeff[0];residual=float(np.sqrt(np.mean(np.sum((xy-design@coeff)**2,axis=1))))
        fits.append({'samples':n,'launchAngleDeg':round(math.degrees(math.atan2(-velocity[1],velocity[0])),2),
                     'projectedBallSpeedMps':round(float(np.linalg.norm(velocity))*.04267/(r*2),2),'residualPx':round(residual,2)})
    return {'version':'0.2.0','capture':root.name,'assumption':'Image horizontal is ground horizontal, image up is vertical; ball-depth scale.',
            'track':track,'fits':fits,'candidateEvidence':evidence}

if __name__=='__main__':
    for path in sys.argv[1:]:print(json.dumps(review(Path(path)),indent=2))
