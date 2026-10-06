"""Club visibility audit 0.1.0; shaft lines are evidence, not club speed."""
import json,sys
from pathlib import Path
import cv2,numpy as np
root=Path(sys.argv[1]);tiles=[];report=[]
for directory in sorted(root.glob('capture-*')):
    if not (directory/'summary.json').exists():continue
    summary=json.loads((directory/'summary.json').read_text())
    if summary['version']!='0.6.3':continue
    for j,camera in enumerate(summary['cameras']):
        images=[cv2.imread(str(directory/f'cam{j}'/f'raw-{m["frame"]:03}.png'),-1).astype('float32')/64 for m in camera['metadata']]
        background=np.median(np.stack(images[:2]),axis=0)
        bx,by,r=summary['ballReferences'][j]
        for i,raw in enumerate(images[:6]):
            diff=np.maximum(raw-background,0)
            mask=(diff>25).astype('uint8')*255
            cv2.circle(mask,(round(bx),round(by)),round(r*1.2),0,-1)
            mask[:max(0,int(by-180))]=0;mask[min(400,int(by+r*2)):]=0
            mask[:,min(640,int(bx+r*1.2)):]=0
            lines=cv2.HoughLinesP(mask,1,np.pi/180,threshold=20,minLineLength=35,maxLineGap=5)
            image=cv2.cvtColor(np.clip(diff*4,0,255).astype('uint8'),cv2.COLOR_GRAY2BGR)
            candidates=[]
            if lines is not None:
                for x1,y1,x2,y2 in lines[:,0]:
                    if abs(y2-y1)<abs(x2-x1)*1.5:continue
                    if max(y1,y2)<by-r*2:continue
                    candidates.append([int(x1),int(y1),int(x2),int(y2)])
                    cv2.line(image,(x1,y1),(x2,y2),(0,255,0),1)
            cv2.putText(image,f'{directory.name[-6:]} C{j} f{i}',(8,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,255,255),1)
            tiles.append(cv2.resize(image,(320,200)))
            report.append({'capture':directory.name,'camera':j,'frame':i,'shaftSegments':candidates})
out=root.parent/'club-audit-v0.1.0';out.mkdir(exist_ok=True)
while len(tiles)%4:tiles.append(np.zeros((200,320,3),'uint8'))
cv2.imwrite(str(out/'visibility.jpg'),np.vstack([np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)]))
(out/'report.json').write_text(json.dumps(report,indent=2))
print(json.dumps({'frames':len(report),'framesWithShaftEvidence':sum(bool(r['shaftSegments']) for r in report),'out':str(out)}))
