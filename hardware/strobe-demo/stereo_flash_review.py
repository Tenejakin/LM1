"""Common-flash stereo review 0.2.0; recorded pulse timing and calibration snapshots."""
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

VERSION = '0.2.0'


def flash_pairs(primary, secondary, delay_us=1000, pulse_us=250):
    """Pair only a complete primary flash inside one secondary exposure."""
    result = []; used = set()
    for first in primary:
        start = first['SensorTimestamp'] + delay_us*1000
        end = start + pulse_us*1000
        if delay_us+pulse_us > first['ExposureTime']:
            continue
        choices = [second for second in secondary if second['frame'] not in used
                   and second['SensorTimestamp'] <= start
                   and second['SensorTimestamp'] + second['ExposureTime']*1000 >= end]
        if len(choices) != 1:
            continue
        second = choices[0]; used.add(second['frame'])
        result.append((first, second, (start+end)/2/1e9))
    return result


def velocity_metrics(velocity):
    x, away, up = velocity
    return dict(speedMps=float(np.linalg.norm(velocity)),
                angleDeg=math.degrees(math.atan2(up, math.hypot(x,away))),
                directionDeg=-math.degrees(math.atan2(away,x)))


def review(root, ball_review):
    sys.path.insert(0, '/opt/pinpoint')
    from stereo_check import _camera, _ray, _triangulate, _project
    from stereo_calibration import fixed_secondary_pose, fingerprint
    import club_stereo
    from launch_measurements import ball_background
    summary = json.loads((root/'summary.json').read_text())
    output = dict(version=VERSION, ball=None, club=None, warnings=[], pairs=[])
    if summary.get('version') not in ('0.9.0','0.9.1','0.10.0'):
        output['warnings'].append('Older secondary exposure mostly missed the flash; no common-flash stereo estimate.')
        return output
    calibration=root/'calibration'
    snapshot=all((calibration/name).exists() for name in ('intrinsics.json','intrinsics-secondary.json','active.json'))
    if not snapshot:calibration=Path('/var/lib/pinpoint')
    lenses = [json.loads((calibration/name).read_text())
              for name in ('intrinsics.json','intrinsics-secondary.json')]
    inputs = [(np.asarray(l['cameraMatrix'],float),np.asarray(l['distCoeffs'],float)) for l in lenses]
    # User-confirmed reference: image right is forward, image up is vertical.
    # The third horizontal axis points away from the cameras, so right is negative y.
    world_to_camera = np.array([[1,0,0],[0,0,-1],[0,1,0]],float)
    lower_input = (*inputs[0],world_to_camera,np.zeros(3))
    if snapshot:
        saved=json.loads((calibration/'active.json').read_text())
        lens_data=[dict(cameraMatrix=k.tolist(),distCoeffs=d.tolist()) for k,d in inputs]
        if not saved.get('passed') or fingerprint(lens_data,(640,400),(0,1))!=saved['fingerprint']:
            raise ValueError('Capture calibration snapshot does not match lenses or camera order')
        rotation=np.asarray(saved['rotation'],float);translation=np.asarray(saved['translationM'],float)
        if rotation.shape!=(3,3) or translation.shape!=(3,) or not np.all(np.isfinite(translation)) or not np.allclose(rotation.T@rotation,np.eye(3),atol=1e-5) or not np.isclose(np.linalg.det(rotation),1,atol=1e-5):
            raise ValueError('Invalid capture calibration snapshot')
        pose=dict(rotation=rotation@lower_input[2],translation=rotation@lower_input[3]+translation)
    else:
        pose = fixed_secondary_pose(lower_input, inputs[1], (640,400), (0,1))
    output['calibrationSource']='capture snapshot' if snapshot else 'current Pi calibration'
    if pose is None:
        raise ValueError('No valid fixed stereo calibration')
    lower = _camera(*lower_input)
    upper = _camera(*inputs[1],pose['rotation'],pose['translation'])
    pulse=summary.get('pattern',{}).get('pulseUs',250)
    pairs = flash_pairs(summary['cameras'][0]['metadata'],summary['cameras'][1]['metadata'],summary.get('flashDelayUs',1000),pulse)
    output['pairs'] = [dict(primary=a['frame'],secondary=b['frame'],flashTime=t) for a,b,t in pairs]
    if len(pairs)<3:
        output['warnings'].append('Too few exposures contain a complete shared flash.')
        return output
    frames = [[],[]];club_frames=[[],[]]
    for a,b,t in pairs:
        for index,meta in enumerate((a,b)):
            raw=cv2.imread(str(root/f'cam{index}'/f'raw-{meta["frame"]:03}.png'),-1)
            image=np.clip((raw.astype('float32')/64-18)/4,0,255).astype('uint8')
            frames[index].append((t,image))
            club_frames[index].append((t,np.clip(18+(raw.astype('float32')/64-18)*250/pulse,0,255).astype('uint8')))
    primary_track={p['frame']:p for p in ball_review['track']}
    ball_points=[]; rest=None
    bx,by,r=summary['ballReferences'][0]

    def match(first_pixel, second_image):
        candidates=cv2.HoughCircles(cv2.medianBlur(second_image,5),cv2.HOUGH_GRADIENT,1,30,
                    param1=60,param2=18,minRadius=max(5,int(r*.5)),maxRadius=int(r*1.6))
        candidates=[] if candidates is None else list(candidates[0])
        # A saturated flash can make a clean filled disc whose sharp raster edge
        # loses Hough votes. Keep circular bright silhouettes as well, subject
        # to the same two-ray and radius checks below.
        mask=(second_image>150).astype('uint8')*255
        for contour in cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
            area=cv2.contourArea(contour);perimeter=cv2.arcLength(contour,True)
            if perimeter<=0 or 4*math.pi*area/perimeter**2<.75:continue
            radius=math.sqrt(area/math.pi)
            if not r*.5<radius<r*1.6:continue
            moments=cv2.moments(contour)
            if moments['m00']:
                candidates.append((moments['m10']/moments['m00'],moments['m01']/moments['m00'],radius))
        matches=[]
        for x,y,radius in candidates:
            point,gap=_triangulate(_ray(lower,first_pixel),_ray(upper,(float(x),float(y))))
            depths=[float((camera['R']@point+camera['t'])[2]) for camera in (lower,upper)]
            if min(depths)<=.15 or max(depths)>2.5 or gap>.012:continue
            predicted=.021335*upper['K'][0,0]/depths[1]
            if abs(radius/predicted-1)>.35:continue
            radius_error=abs(radius/predicted-1)
            matches.append((gap+.03*radius_error,gap,point,(float(x),float(y))))
        if not matches:return None
        best=min(matches,key=lambda m:m[0])
        return best[1:]

    for i,(a,b,t) in enumerate(pairs):
        if a['frame'] in primary_track:
            first=primary_track[a['frame']]['point'][:2]
            located=match(first,frames[1][i][1])
            if located:
                gap,point,pixel=located
                ball_points.append(dict(frameIndex=a['frame'],pairIndex=i,time=t,
                    positionM=point.tolist(),rayGapMm=gap*1000,secondaryPixel=pixel))
        elif not ball_points and t<summary['triggerSensorTimestamp']/1e9:
            located=match((bx,by),frames[1][i][1])
            if located:rest=located[1]
    output['ballTrack']=ball_points
    if len(ball_points)>=2:
        # Earliest two positions match the existing launch definition. Additional
        # positions check the track, rather than shifting the launch instant.
        first,second=ball_points[:2]
        dt=second['time']-first['time']
        if 0<dt<=.025:
            velocity=(np.asarray(second['positionM'])-first['positionM'])/dt
            metrics=velocity_metrics(velocity)
            if velocity[0]>0 and .5<metrics['speedMps']<90:
                metrics.update(samples=len(ball_points),frames=[p['frameIndex'] for p in ball_points],
                               maxRayGapMm=max(p['rayGapMm'] for p in ball_points))
                output['ball']=metrics
                if metrics['maxRayGapMm']>6:
                    output['warnings'].append('Stereo rays miss by up to '+str(round(metrics['maxRayGapMm'],1))+
                        ' mm: provisional 12 mm gate used; calibration bias may affect speed and direction.')
    if rest is not None and ball_points:
        impact=ball_points[0]['pairIndex']
        origin=rest-np.array([0,0,.021335])
        # Existing club gates use ground height, rather than camera height.
        club_lower=_camera(lower['K'],lower['D'],lower['R'],lower['R']@origin+lower['t'])
        club_upper=_camera(upper['K'],upper['D'],upper['R'],upper['R']@origin+upper['t'])
        try:
            def accept(velocity):
                speed=float(np.linalg.norm(velocity)); result=velocity_metrics(velocity)
                if velocity[0]<=0 or not .5<speed<80:return 'Not a forward club track'
                if not -60<result['angleDeg']<40:return 'Club attack angle outside supported range'
                ball_speed=(output.get('ball') or {}).get('speedMps')
                if ball_speed and not .4<ball_speed/speed<2.2:return 'Implausible smash factor'
                return None
            club=club_stereo.measure(club_frames[0],club_frames[1],impact,club_lower,club_upper,
                 ball_background(club_frames[0],impact),ball_background(club_frames[1],impact),rest-origin,accept=accept)
            metrics=velocity_metrics(club['velocity'])
            metrics.update(diagnostics=club['diagnostics'],frames=[pairs[p['frameIndex']][0]['frame'] for p in club['track']])
            output['club']=metrics
        except (ValueError,IndexError,np.linalg.LinAlgError,cv2.error) as error:
            output['warnings'].append('Club stereo: '+str(error))
            diagnostics=getattr(error,'diagnostics',{})
            output['clubDiagnostics']=diagnostics
            # Two same-feature positions give interval velocity, but cannot
            # validate an arc. Do not replace a rejected longer track with two
            # cherry-picked positions that merely happen to look plausible.
            if diagnostics.get('runsByPoint') and max(diagnostics['runsByPoint'].values())<3:
                import club_vision
                backgrounds=[ball_background(f,impact) for f in club_frames]
                window=range(max(0,impact-12),impact)
                ignores=[club_vision.persistent_change([burst[i][1] for i in window],background)
                         for burst,background in zip(club_frames,backgrounds)]
                views=[]
                for camera in (club_lower,club_upper):
                    depth=(camera['R']@(rest-origin)+camera['t'])[2]
                    views.append((_project(camera,[rest-origin])[0],.021335*camera['K'][0,0]/depth))
                candidates=[]
                for name,locate in (('hosel',club_stereo.hosel_pixel),('head',club_stereo.head_pixel)):
                    samples=[]
                    for i in window:
                        pixels=[locate(burst[i][1],background,*view,ignore)
                                for burst,background,view,ignore in zip(club_frames,backgrounds,views,ignores)]
                        if any(p is None for p in pixels):continue
                        point,gap=_triangulate(_ray(club_lower,pixels[0]),_ray(club_upper,pixels[1]))
                        if gap>.006 or not -.01<point[2]<.3:continue
                        samples.append((i,point,gap))
                    for a,b in zip(samples,samples[1:]):
                        if not 0<b[0]-a[0]<=2:continue
                        dt=pairs[b[0]][2]-pairs[a[0]][2]
                        if dt<=0:continue
                        velocity=(b[1]-a[1])/dt
                        if accept(velocity):continue
                        candidates.append((b[0],name,a,b,velocity))
                if candidates:
                    _,name,a,b,velocity=max(candidates,key=lambda item:item[0])
                    metrics=velocity_metrics(velocity)
                    metrics.update(frames=[pairs[i][0]['frame'] for i in (a[0],b[0])],
                        diagnostics=dict(point=name,acceptedFrames=2,model='two-point interval velocity',
                                         medianRayGapMm=(a[2]+b[2])*500,fitResidualMm=None))
                    output['club']=metrics
                    output['warnings'].append('Two-point club estimate cannot independently check feature identity or swing curvature.')
    else:
        output['warnings'].append('Resting ball or moving ball could not be paired for club geometry.')
    return output


if __name__=='__main__':
    root=Path(sys.argv[1]);record=json.loads((root/'review.json').read_text())
    print(json.dumps(review(root,record['ball']),indent=2))
