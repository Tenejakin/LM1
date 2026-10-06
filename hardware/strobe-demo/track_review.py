"""Candidate review of retained slow wedge shots, version 0.1.0."""
from pathlib import Path
import cv2
import numpy as np

ROOT=Path('/home/lm1/strobe-demo-v0.1.1/captures')
for directory in sorted(ROOT.glob('capture-*')):
    if directory.name.endswith(('5314388623547','5565133525153')):continue
    print(directory.name)
    for camera,rest in ((0,(253,265)),(1,(267,192))):
        folder=directory/f'cam{camera}'
        paths=sorted(folder.glob('raw-*.png'))
        background=np.median(np.stack([cv2.imread(str(p),-1).astype('float32')/64 for p in paths[-5:]]),axis=0)
        tiles=[]
        for i in range(24,30):
            raw=cv2.imread(str(paths[i]),-1).astype('float32')/64
            diff=cv2.GaussianBlur(raw-background,(0,0),1.2)
            tile=cv2.cvtColor(np.clip(diff*.5,0,255).astype('uint8'),cv2.COLOR_GRAY2BGR)
            candidates=[]
            for threshold in (30,60,100,150,250):
                contours,_=cv2.findContours((diff>threshold).astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                for contour in contours:
                    area=cv2.contourArea(contour)
                    if not 600<area<6000:continue
                    m=cv2.moments(contour)
                    x,y=m['m10']/m['m00'],m['m01']/m['m00']
                    if x<rest[0]+25 or y>rest[1]+5 or y<30:continue
                    if all(np.hypot(x-c[0],y-c[1])>8 for c in candidates):
                        candidates.append((round(x,1),round(y,1),round(area),threshold))
                        cv2.circle(tile,(round(x),round(y)),24,(0,255,0),1)
                        cv2.putText(tile,f'{round(x)},{round(y)}',(round(x),round(y)),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,255,0),1)
            print(camera,i,candidates)
            cv2.putText(tile,f'C{camera} F{i}',(10,20),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,255),1)
            tiles.append(cv2.resize(tile,(480,300)))
        cv2.imwrite(str(directory/f'candidates-{camera}.jpg'),np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,6,3)]))
