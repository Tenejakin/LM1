"""Raw capture diagnostics 0.1.0: timing, flash coverage and clipped ball detail."""
import json,sys
from pathlib import Path
import cv2,numpy as np
from stereo_flash_review import flash_pairs

VERSION='0.1.0'

def analyze(root,ball_track=None):
    summary=json.loads((root/'summary.json').read_text());pattern=summary['pattern']
    period=pattern['periodUs'];pulse=pattern['pulseUs'];cameras=[]
    for camera in summary['cameras']:
        index=camera['camera'];meta=camera['metadata'];times=np.array([m['SensorTimestamp'] for m in meta],float)
        intervals=np.diff(times)/1000
        before=int(sum(t<summary['triggerSensorTimestamp'] for t in times))
        points=ball_track if index==0 and ball_track else []
        if not points:
            points=[dict(frame=m['frame'],point=summary['ballReferences'][index]) for m in meta[:3]]
        clipping=[]
        for p in points:
            raw=cv2.imread(str(root/f'cam{index}'/f'raw-{p["frame"]:03}.png'),-1)
            if raw is None:continue
            x,y,r=p['point'];yy,xx=np.ogrid[:raw.shape[0],:raw.shape[1]]
            region=(xx-x)**2+(yy-y)**2<(r*.65)**2
            values=raw[region].astype(float)/64
            if values.size:clipping.append(dict(frame=p['frame'],clippedFraction=float(np.mean(values>=1020)),
                                                 medianCounts=float(np.median(values))))
        cameras.append(dict(camera=index,frames=len(meta),preDepartureFrames=before,
            observedFps=float(1e6/np.median(intervals)) if len(intervals) else None,
            largestIntervalUs=float(max(intervals)) if len(intervals) else None,
            timingGaps=int(np.sum(intervals>period*1.5)),ballCore=clipping))
    pairs=flash_pairs(summary['cameras'][0]['metadata'],summary['cameras'][1]['metadata'],
                      summary.get('flashDelayUs',1000),pulse)
    result=dict(version=VERSION,capture=root.name,rateHz=pattern['rateHz'],pulseUs=pulse,
                cameras=cameras,inferredSharedFlashPairs=len(pairs),
                pairingFraction=len(pairs)/max(1,len(summary['cameras'][0]['metadata'])),
                note='Pairing is inferred from exposure metadata, not verified electrical feedback.')
    result['warnings']=[]
    for camera in cameras:
        if camera['observedFps'] is not None and camera['observedFps']<pattern['rateHz']*.9:
            result['warnings'].append(f"Camera {camera['camera']} delivered fewer frames than the configured flash rate.")
        if camera['timingGaps']:
            result['warnings'].append(f"Camera {camera['camera']} has {camera['timingGaps']} timing gaps.")
        if any(p['clippedFraction']>.05 for p in camera['ballCore']):
            result['warnings'].append(f"Camera {camera['camera']} clips more than 5% of a sampled ball core; texture may be lost.")
    if result['pairingFraction']<.8:
        result['warnings'].append('Fewer than 80% of primary frames have an inferred complete shared flash in the second view.')
    return result

if __name__=='__main__':
    for path in sys.argv[1:]:
        root=Path(path);review=json.loads((root/'review.json').read_text())
        print(json.dumps(analyze(root,review['ball']['track'])))
