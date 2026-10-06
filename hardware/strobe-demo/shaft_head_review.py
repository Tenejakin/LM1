"""Shaft-guided head-region replay 0.3.0; normalize recorded flash energy for detection."""
import json,math,sys
from pathlib import Path
import cv2,numpy as np

VERSION='0.3.0'

def review(root):
    summary=json.loads((root/'summary.json').read_text());streams=[]
    pulse=summary.get('pattern',{}).get('pulseUs',250)
    for camera in summary['cameras']:
        index=camera['camera'];bx,by,r=summary['ballReferences'][index]
        images={m['frame']:np.clip(18+(cv2.imread(str(root/f'cam{index}'/f'raw-{m["frame"]:03}.png'),-1).astype('float32')/64-18)*250/pulse,0,255).astype('uint8')
                for m in camera['metadata']}
        background=np.median(np.stack([images[i] for i in sorted(images)[:3]]),axis=0).astype('uint8')
        times={m['frame']:m['SensorTimestamp'] for m in camera['metadata']}
        track=[]
        for item in camera.get('clubAnalysis',{}).get('candidateFrames',[]):
            frame=item['frame'];segments=item['shaftSegments'];estimates=[]
            for x1,y1,x2,y2 in segments:
                if abs(y2-y1)<35:continue
                estimates.append(x1+(by+r*.2-y1)*(x2-x1)/(y2-y1))
            if not estimates:continue
            shaft_x=float(np.median(estimates))
            left=0;right=min(640,round(bx+r*.3))
            top=max(0,round(by-r*1.4));bottom=min(400,round(by+r*1.6))
            if right<=left:continue
            mask=np.zeros_like(background)
            diff=cv2.subtract(images[frame],background)
            mask[top:bottom,left:right]=(diff[top:bottom,left:right]>8).astype('uint8')*255
            cv2.circle(mask,(round(bx),round(by)),round(r*1.05),0,-1)
            mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((1,7),'uint8'))
            mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),'uint8'))
            count,labels,stats,centres=cv2.connectedComponentsWithStats(mask)
            candidates=[]
            for n in range(1,count):
                x,y,w,h,area=stats[n];cx,cy=centres[n]
                if area<r*r*.08 or w<r*.6 or h<r*.2 or w/h<.9 or x<=3:continue
                if not shaft_x-r*2<cx<shaft_x+r*.3 or abs(cy-by)>r*1.5:continue
                candidates.append((-area,n))
            if not candidates:continue
            _,n=min(candidates);x,y,w,h,area=stats[n]
            # A component cut by the local window has a moving artificial centre.
            if x<=left+1 or x+w>=right-1 or y<=top+1 or y+h>=bottom-1:continue
            track.append(dict(frame=frame,timestamp=times[frame],point=centres[n].tolist(),area=int(area),
                              bounds=list(map(int,(x,y,w,h))),shaftX=shaft_x))
        streams.append(dict(camera=index,track=track))
        if index==0:primary_images=images
    result=dict(version=VERSION,cameras=streams,pairs=[])
    r=summary['ballReferences'][0][2];scale=.04267/(2*r)
    # Keep stationary pre-departure frames; reject a ball-clipped head region.
    trigger=summary['triggerSensorTimestamp']
    before=[m for m in summary['cameras'][0]['metadata'] if m['SensorTimestamp']<trigger]
    latest=before[-1]['frame'] if before else -1
    samples=[p for p in streams[0]['track'] if p['frame']<=latest]
    for a,b in zip(samples,samples[1:]):
        dt=(b['timestamp']-a['timestamp'])/1e9
        if b['frame']!=a['frame']+1 or not 0<dt<.025:continue
        bx,by,_=summary['ballReferences'][0]
        if any(p['bounds'][0]+p['bounds'][2]>=bx-r*1.05 for p in (a,b)):continue
        x,y,w,h=a['bounds'];margin=4
        left=max(0,x-margin);top=max(0,y-margin)
        template=primary_images[a['frame']][top:y+h+margin,left:x+w+margin]
        if template.std()<8:continue
        xx,yy,ww,hh=b['bounds'];pad=round(r*.6)
        sx=max(0,xx-pad);sy=max(0,yy-pad)
        search=primary_images[b['frame']][sy:min(400,yy+hh+pad),sx:min(640,xx+ww+pad)]
        if search.shape[0]<template.shape[0] or search.shape[1]<template.shape[1]:continue
        scores=cv2.matchTemplate(search,template,cv2.TM_CCOEFF_NORMED)
        _,score,_,location=cv2.minMaxLoc(scores)
        if score<.7:continue
        point=[sx+location[0]+a['point'][0]-left,sy+location[1]+a['point'][1]-top]
        velocity=(np.array(point)-a['point'])*scale/dt
        speed=float(np.linalg.norm(velocity));angle=math.degrees(math.atan2(-velocity[1],velocity[0]))
        if abs(angle)<1e-9:angle=0.
        if velocity[0]<=0 or not 1<speed<80 or not -60<angle<40:continue
        result['pairs'].append(dict(intervalMs=dt*1000,speedMps=speed,angleDeg=angle,
             horizontalVelocityMps=float(velocity[0]),verticalVelocityMps=float(-velocity[1]),
             frames=[a['frame'],b['frame']],points=[a['point'],point],templateScore=score,
             areaRatio=b['area']/a['area'],status='shaft-guided textured head feature; identity remains provisional'))
    return result

if __name__=='__main__':
    for path in [p for p in sys.argv[1:] if p!='--brief']:
        result=review(Path(path))
        if '--brief' in sys.argv[1:]:result=dict(capture=Path(path).name,pairs=result['pairs'])
        print(json.dumps(result,indent=2))
