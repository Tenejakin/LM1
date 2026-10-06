"""Full saved-shot review 0.1.1 under the user's level-camera assumption."""
import json,math,sys,html
from pathlib import Path
import cv2,numpy as np
from launch_angle_review import review

VERSION='0.1.1'

def pair_metrics(a,b,scale):
    dt=(b['timestamp']-a['timestamp'])/1e9
    if dt<=0:return None
    delta=np.asarray(b['point'][:2])-a['point'][:2]
    velocity=delta*scale/dt
    return {'intervalMs':round(dt*1000,3),'speedMps':round(float(np.linalg.norm(velocity)),2),
            'angleDeg':round(math.degrees(math.atan2(-velocity[1],velocity[0])),2),
            'horizontalVelocityMps':round(float(velocity[0]),2),'verticalVelocityMps':round(float(-velocity[1]),2)}

def extract(root):
    summary=json.loads((root/'summary.json').read_text())
    ball=review(root);r=summary['ballReferences'][0][2];scale=.04267/(2*r)
    track=ball['track'];pairs=[pair_metrics(a,b,scale) for a,b in zip(track,track[1:])]
    if track:
        duration=(track[-1]['timestamp']-track[0]['timestamp'])/1e6
        displacement=(np.asarray(track[-1]['point'][:2])-track[0]['point'][:2])*scale
    else:duration=0;displacement=np.zeros(2)
    club=summary['cameras'][0].get('clubAnalysis',{})
    candidates=club.get('headCandidates',[]);club_pairs=[]
    for a,b in zip(candidates,candidates[1:]):
        if b['frame']!=a['frame']+1:continue
        metric=pair_metrics(a,b,scale)
        if metric:
            metric.update(frames=[a['frame'],b['frame']],status='provisional; club feature identity unverified',
                          areaRatio=round(b['area']/a['area'],3),points=[a['point'],b['point']])
            metric['smashFactorProvisional']=round(pairs[0]['speedMps']/metric['speedMps'],2) if pairs and metric['speedMps'] else None
            club_pairs.append(metric)
    shaft=[]
    for item in club.get('candidateFrames',[]):
        angles=[]
        for x1,y1,x2,y2 in item['shaftSegments']:
            if y1>y2:x1,y1,x2,y2=x2,y2,x1,y1
            angles.append(math.degrees(math.atan2(x1-x2,y2-y1)))
        if angles:shaft.append({'frame':item['frame'],'leanFromImageVerticalDeg':round(float(np.median(angles)),1),
                               'status':'shaft reflection orientation; not dynamic loft'})
    # Find the last clearly stationary ball before the first moving centre.
    bracket=None
    if track:
        bx,by,_=summary['ballReferences'][0]
        for meta in reversed(summary['cameras'][0]['metadata']):
            if meta['SensorTimestamp']>=track[0]['timestamp']:continue
            raw=cv2.imread(str(root/'cam0'/f'raw-{meta["frame"]:03}.png'),-1).astype('float32')/64
            left=max(0,int(bx-2*r));top=max(0,int(by-2*r))
            crop=np.clip((raw[top:min(400,int(by+2*r)),left:min(640,int(bx+2*r))]-18)/4,0,255).astype('uint8')
            circles=cv2.HoughCircles(cv2.medianBlur(crop,5),cv2.HOUGH_GRADIENT,1,30,param1=60,param2=22,minRadius=int(r*.65),maxRadius=int(r*1.25))
            if circles is not None and any(math.hypot(x+left-bx,y+top-by)<r*.35 for x,y,rr in circles[0]):
                bracket={'lastStationaryFrame':meta['frame'],'firstMovingFrame':track[0]['frame'],
                         'intervalMs':round((track[0]['timestamp']-meta['SensorTimestamp'])/1e6,3),
                         'status':'departure bracket, not exact impact time'}
                break
    fits=ball['fits'];warnings=[]
    if len(fits)>1 and abs(fits[0]['launchAngleDeg']-fits[-1]['launchAngleDeg'])>5:
        warnings.append('Initial angle and longer path disagree; motion may be nonlinear or a centre may be mismatched.')
    if track and track[-1]['point'][2]/track[0]['point'][2]<.85:
        warnings.append('Apparent ball radius changes substantially; constant-depth speed scale may be biased.')
    if len(track)<3:warnings.append('Two-point estimate has no additional position for consistency checking.')
    return {'version':VERSION,'capture':root.name,'captureVersion':summary['version'],
            'assumptions':['Image horizontal is ground horizontal; image-up is vertical.',
                           'Distance scale uses the resting ball diameter; club is assumed at ball depth.'],
            'ball':{'fits':ball['fits'],'track':track,'intervals':pairs,'warnings':warnings,'observedDurationMs':round(duration,3),
                    'horizontalDisplacementM':round(float(displacement[0]),3),'verticalDisplacementM':round(float(-displacement[1]),3),
                    'radiusChangeRatio':round(track[-1]['point'][2]/track[0]['point'][2],3) if track else None,
                    'departureBracket':bracket},
            'clubProvisionalPairs':club_pairs,'shaftOrientation':shaft,
            'unavailable':['spin rate','spin axis','calibrated 3D speed and direction','face angle','dynamic loft','verified impact location'],
            'clubWarning':'Two candidates can be different reflections. Provisional attack angle and smash factor do not validate their identity.'}

def write_report(root,out):
    out.mkdir(parents=True,exist_ok=True);records=[]
    for directory in sorted(root.glob('capture-*')):
        if not (directory/'summary.json').exists():continue
        summary=json.loads((directory/'summary.json').read_text())
        if summary['version']!='0.7.1':continue
        record=extract(directory);records.append(record)
        rows=record['ball']['track'];image_path=None
        if rows:
            first=rows[0];raw=cv2.imread(str(directory/'cam0'/f'raw-{first["frame"]:03}.png'),-1).astype('float32')/64
            image=cv2.cvtColor(np.clip((raw-18)/4,0,255).astype('uint8'),cv2.COLOR_GRAY2BGR)
            for item in rows:
                x,y,r=item['point'];cv2.circle(image,(round(x),round(y)),round(r),(0,255,0),1)
                cv2.putText(image,str(item['frame']),(round(x),round(y)),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,255,255),1)
            image_path=record['capture']+'.jpg';cv2.imwrite(str(out/image_path),image)
        record['preview']=image_path
    (out/'data.json').write_text(json.dumps({'version':VERSION,'shots':records},indent=2))
    body=[]
    for number,record in enumerate(records,1):
        fits=record['ball']['fits'];first=fits[0] if fits else None
        heading=f'Shot {number}: '+(f'{first["projectedBallSpeedMps"]} m/s, {first["launchAngleDeg"]}° launch' if first else 'Ball track unresolved')
        body.append('<section><h2>'+html.escape(heading)+'</h2><p>'+html.escape(record['capture'])+'</p>')
        b=record['ball']
        body.append('<p>'+str(len(b['track']))+' ball positions; '+str(b['observedDurationMs'])+' ms observed flight. Horizontal displacement '+str(b['horizontalDisplacementM'])+' m; vertical displacement '+str(b['verticalDisplacementM'])+' m.</p>')
        if b['departureBracket']:body.append('<p>Ball departure interval: '+str(b['departureBracket']['intervalMs'])+' ms.</p>')
        for pair in record['clubProvisionalPairs']:
            body.append('<p>Provisional club: '+str(pair['speedMps'])+' m/s; assumed attack '+str(pair['angleDeg'])+'°; provisional smash '+str(pair['smashFactorProvisional'])+'. Feature identity remains unverified.</p>')
        for warning in b['warnings']:body.append('<p>'+html.escape(warning)+'</p>')
        if record['preview']:body.append('<img src="'+record['preview']+'">')
        body.append('<details><summary>All extracted data and assumptions</summary><pre>'+html.escape(json.dumps(record,indent=2))+'</pre></details></section>')
    document='<meta charset="utf-8"><title>LM1 shot review '+VERSION+'</title><style>body{font:16px system-ui;background:#111d26;color:#edf3f8;max-width:900px;margin:30px auto}section{border-top:1px solid #456;padding:20px}img{max-width:100%}pre{white-space:pre-wrap}summary{cursor:pointer}</style><h1>Saved shot review '+VERSION+'</h1><p>Projected estimates using a level camera and ball-depth scale. Green circles show the tracked ball centres. Club pairs are provisional; reflection identity is unverified.</p>'+''.join(body)
    (out/'index.html').write_text(document,encoding='utf-8')
    print(json.dumps([{'shot':i+1,'capture':r['capture'],'ball':r['ball']['fits'],'clubPairs':r['clubProvisionalPairs'],'departure':r['ball']['departureBracket']} for i,r in enumerate(records)],indent=2))

if __name__=='__main__':write_report(Path(sys.argv[1]),Path(sys.argv[2]))
