"""Night shot contrast review 0.1.1; preserves raw images, reports circle candidates."""
import sys,json
from pathlib import Path
import cv2,numpy as np
from demo import fit_copies
root=Path(sys.argv[1]); summary=json.loads((root/'summary.json').read_text())
tiles=[]
for j,camera in enumerate(summary['cameras']):
    paths=sorted((root/f'cam{j}').glob('raw-*.png'))
    images=[cv2.imread(str(p),-1).astype('float32')/64 for p in paths]
    background=np.median(np.stack(images[-3:]),axis=0)
    for i,raw in enumerate(images):
        diff=np.maximum(raw-background,0)
        image=np.clip(diff*3,0,255).astype('uint8')
        tile=cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)
        dt=(camera['metadata'][i]['SensorTimestamp']-summary['triggerSensorTimestamp'])/1e6
        cv2.putText(tile,f'C{j} f{i} {dt:+.1f}ms',(8,22),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,0),1)
        cv2.imwrite(str(root/f'contrast-c{j}-f{i}.jpg'),tile)
        if (j,i) in ((0,4),(1,3)):
            roi=cv2.GaussianBlur(image[100:260,310:530],(5,5),1)
            circles=cv2.HoughCircles(roi,cv2.HOUGH_GRADIENT,1,30,param1=60,param2=16,minRadius=18,maxRadius=27)
            points=[] if circles is None else [[float(x+310),float(y+100),float(r)] for x,y,r in circles[0]]
            print(json.dumps({'camera':j,'frame':i,'circleCandidates':points,'fit':fit_copies([p[:2] for p in points],summary['ballReferences'][j][2]*2,summary['pattern']) if len(points)==3 else None}),flush=True)
        tiles.append(cv2.resize(tile,(320,200)))
    while len(tiles)%4:tiles.append(np.zeros((200,320,3),'uint8'))
cv2.imwrite(str(root/'contrast-all.jpg'),np.vstack([np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)]))
