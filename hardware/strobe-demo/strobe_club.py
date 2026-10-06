"""Strobe club visibility 0.2.1. Never promote shaft reflections to club metrics."""
import cv2
import numpy as np

VERSION='0.2.1'

def analyze_single_flash(rows,ball,trigger_timestamp):
    """Experimental head-centroid speed: one known flash per triggered frame.

    Scale assumes the head is at the resting ball's depth. Image direction is
    deliberately not called attack angle. Rotation and depth can bias speed.
    """
    result=analyze_club(rows,ball,trigger_timestamp)
    before=[row for row in rows if row['meta']['SensorTimestamp']<trigger_timestamp]
    if len(before)<5:return result
    images=[row['raw'].astype('float32')/64 for row in before]
    background=np.median(np.stack(images[:3]),axis=0)
    differences=[np.abs(image-background) for image in images]
    persistent=np.mean(np.stack([d>20 for d in differences]),axis=0)>.6
    bx,by,r=ball;samples=[]
    for i,(row,diff) in enumerate(zip(before,differences)):
        mask=(diff>20).astype('uint8')*255
        mask[persistent]=0
        mask[:max(0,int(by-2*r))]=0;mask[min(400,int(by+2*r)):]=0
        mask[:,min(640,int(bx+r)):]=0
        cv2.circle(mask,(round(bx),round(by)),round(r*1.2),0,-1)
        # Remove the thin vertical shaft before measuring the broader head.
        # A connected shaft otherwise makes the head component too tall.
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((1,7),'uint8'))
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),'uint8'))
        count,labels,stats,centres=cv2.connectedComponentsWithStats(mask)
        candidates=[]
        for n in range(1,count):
            x,y,w,h,area=stats[n]
            if area<max(60,r*r*.12) or w<r*.6 or h>r*2.5 or x<=3:continue
            candidates.append((area,centres[n]))
        # Multiple head-like blobs are ambiguous; do not silently pick a foot.
        if len(candidates)!=1:continue
        area,point=candidates[0]
        samples.append({'frame':i,'timestamp':row['meta']['SensorTimestamp'],
                        'point':point.tolist(),'area':int(area)})
    runs=[];run=[]
    for sample in samples:
        if run and (sample['frame']!=run[-1]['frame']+1 or abs(sample['area']/run[-1]['area']-1)>.35):
            runs.append(run);run=[]
        run.append(sample)
    runs.append(run)
    run=max(runs,key=len)
    result['headCandidates']=samples
    if len(run)<3:
        result['reason']=f'Only {len(run)} consecutive pre-departure head candidates; need at least 3.'
        return result
    times=np.asarray([s['timestamp'] for s in run],float)/1e9
    intervals=np.diff(times)
    if np.any(intervals<=0) or np.max(intervals)>.02:
        result['reason']='Club track has missing or invalid timing.';return result
    points=np.asarray([s['point'] for s in run])
    design=np.column_stack((times-times.mean(),np.ones(len(times))))
    coefficients=np.linalg.lstsq(design,points,rcond=None)[0]
    residual=float(np.sqrt(np.mean(np.sum((design@coefficients-points)**2,axis=1))))
    velocity=coefficients[0]*.04267/(2*r)
    speed=float(np.linalg.norm(velocity))
    if residual>2.5 or not 1<speed<80 or coefficients[0,0]<=0:
        result['reason']='Head candidates do not follow a consistent forward path.';return result
    result.update(status='experimental image-plane estimate',clubSpeedMps=round(speed,2),
                  attackAngleDeg=None,imagePathAngleDeg=round(float(np.degrees(np.arctan2(-velocity[1],velocity[0]))),1),
                  fitResidualPx=round(residual,3),track=run,
                  scaleAssumption='Clubhead at resting ball depth; geometric centre unverified.',
                  reason='Attack angle unavailable: ground-relative 3D club path not measured.')
    return result

def analyze_club(rows,ball,trigger_timestamp,stereo_synchronized=False):
    """Record pre-departure shaft evidence without asserting impact or head identity.

    Capture-trigger time is a conservative boundary, not a known impact time.
    A shaft segment's endpoint is not the clubhead geometric centre. Multiple
    reflections can belong to one exposure; sensor timestamps cannot time them.
    """
    result={'version':VERSION,'clubSpeedMps':None,'attackAngleDeg':None,
            'status':'unavailable','candidateFrames':[],
            'stereoSynchronized':stereo_synchronized,
            'reason':'No verified, timed clubhead-centre track before impact.',
            'requirements':['Identify the same clubhead feature across flashes before impact.',
                            'Match each feature to its flash time.',
                            'Verify camera geometry and ground orientation for attack angle.']}
    if len(rows)<3:return result
    images=[row['raw'].astype('float32')/64 for row in rows]
    background=np.median(np.stack(images[:2]),axis=0)
    bx,by,r=ball
    for i,(row,image) in enumerate(zip(rows,images)):
        if row['meta']['SensorTimestamp']>=trigger_timestamp:continue
        mask=(image-background>25).astype('uint8')*255
        cv2.circle(mask,(round(bx),round(by)),round(r*1.2),0,-1)
        mask[:max(0,int(by-180))]=0
        mask[min(mask.shape[0],int(by+r*2)):]=0
        mask[:,min(mask.shape[1],int(bx+r*1.2)):]=0
        lines=cv2.HoughLinesP(mask,1,np.pi/180,20,minLineLength=35,maxLineGap=5)
        segments=[]
        if lines is not None:
            for x1,y1,x2,y2 in lines[:,0]:
                if abs(y2-y1)<abs(x2-x1)*1.5 or max(y1,y2)<by-r*2:continue
                segments.append([int(x1),int(y1),int(x2),int(y2)])
        if segments:
            result['candidateFrames'].append({'frame':i,'sensorTimestamp':row['meta']['SensorTimestamp'],
                                            'shaftSegments':segments,'feature':'shaft reflection; head identity unverified'})
    if not result['candidateFrames']:
        result['reason']='No clear pre-departure shaft evidence; clubhead track unavailable.'
    if not stereo_synchronized:
        result['requirements'].append('Synchronize both views before attempting stereo club measurements.')
    return result
