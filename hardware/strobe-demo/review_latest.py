"""Saved-shot rejection audit 0.1.0; read-only, no live capture changes."""
import inspect
import json
from pathlib import Path
import cv2
import numpy as np
import demo

source=inspect.getsource(demo.frame_track).replace('    tracks=[]','    return {"candidates":candidates}\n    tracks=[]')
namespace=dict(demo.__dict__)
exec(source,namespace)
extract=namespace['frame_track']
root=Path('/home/lm1/strobe-demo-v0.2.0/captures')
report=[]
for directory in sorted(root.glob('capture-*')):
    summary=json.loads((directory/'summary.json').read_text())
    entry={'capture':directory.name,'views':[]}
    for index,camera in enumerate(summary['cameras']):
        rows=[{'raw':cv2.imread(str(directory/f'cam{index}'/f'raw-{m["frame"]:03}.png'),-1),'meta':m} for m in camera['metadata']]
        found=extract(rows,summary['ballReferences'][index])['candidates']
        points=[p for candidates in found for p in candidates]
        details=[]
        for a,b in zip(points,points[1:]):
            if b['frame']!=a['frame']+1:continue
            dt=(b['timestamp']-a['timestamp'])/1e9
            v=np.array([b['x']-a['x'],b['y']-a['y']])/dt
            diameter=summary['ballReferences'][index][2]*2
            speed=float(np.linalg.norm(v))*42.67/diameter/1000
            details.append({'frames':[a['frame'],b['frame']],'speedMps':round(speed,2),
                            'blurMm':round(speed*rows[b['frame']]['meta']['ExposureTime']/1000,2),
                            'sizeRatio':round(b['diameter']/a['diameter'],3)})
        entry['views'].append({'camera':index,'points':[{k:round(v,2) if isinstance(v,float) else v for k,v in p.items()} for p in points],
                               'intervalChecks':details,'originalBest':camera['analysis']['best']})
    report.append(entry)
print(json.dumps(report,indent=2))
Path('/home/lm1/strobe-demo-v0.2.0/shot-review-v0.1.0.json').write_text(json.dumps(report,indent=2))
