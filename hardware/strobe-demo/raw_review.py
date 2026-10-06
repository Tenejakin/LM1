"""Raw departure contrast inspection, version 0.1.0."""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT=Path('/home/lm1/strobe-demo-v0.1.1/captures')
for directory in sorted(ROOT.glob('capture-*')):
    tiles=[]
    for camera in (0,1):
        folder=directory/f'cam{camera}'
        paths=sorted(folder.glob('raw-*.png'))
        background=np.median(np.stack([cv2.imread(str(p),-1).astype('float32')/64 for p in paths[-5:]]),axis=0)
        for i in range(22,28):
            if i>=len(paths):continue
            raw=cv2.imread(str(paths[i]),-1).astype('float32')/64
            diff=np.clip(raw-background,0,None)
            cropped=diff[30:310,200:640]
            peak=np.percentile(cropped,99.7)
            tile=cv2.cvtColor(np.clip(cropped*255/max(peak,1),0,255).astype('uint8'),cv2.COLOR_GRAY2BGR)
            cv2.putText(tile,f'C{camera} f{i} peak {peak:.0f}',(8,20),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,0),1)
            tiles.append(tile)
    if tiles:
        cv2.imwrite(str(directory/'contrast.jpg'),np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,len(tiles),3)]))
    summary=json.loads((directory/'summary.json').read_text())
    print(directory.name,[(len(c['metadata']),len(c['analysis']['hypotheses'])) for c in summary['cameras']])
