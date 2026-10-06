"""Nine-microsecond raw shot review 0.1.0; display scaling only."""
import argparse,json
from pathlib import Path
import cv2,numpy as np
p=argparse.ArgumentParser();p.add_argument('capture',type=Path);p.add_argument('--out',type=Path,required=True);args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
s=json.loads((args.capture/'summary.json').read_text());tiles=[];report=[]
for camera in (0,1):
    paths=sorted((args.capture/f'cam{camera}').glob('raw-*.png'))
    background=np.median([cv2.imread(str(q),-1).astype(float)/64 for q in paths[-5:]],axis=0)
    samples=[]
    for i in range(18,min(38,len(paths))):
        raw=cv2.imread(str(paths[i]),-1).astype('float32')/64
        diff=raw-background
        smooth=cv2.boxFilter(diff.astype('float32'),-1,(15,15))
        region=smooth[40:350,300:620];_,peak,_,where=cv2.minMaxLoc(region)
        x,y=where[0]+300,where[1]+40
        image=cv2.cvtColor(np.clip((raw-16)*8,0,255).astype('uint8'),cv2.COLOR_GRAY2BGR)
        image=cv2.resize(image,(320,200))
        cv2.putText(image,f'C{camera} f{i} +{peak:.1f} counts',(5,18),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,255,255),1)
        tiles.append(image);samples.append({'frame':i,'peak15pxMeanAboveBackground':round(peak,2),'peakPosition':[x,y]})
    report.append({'camera':camera,'samples':samples})
cv2.imwrite(str(args.out/'brightened-contact.jpg'),np.vstack([np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)]))
(args.out/'review.json').write_text(json.dumps({'version':'0.1.0','capture':s['name'],'previewScale':8,'views':report},indent=2))
print(json.dumps(report),flush=True)
