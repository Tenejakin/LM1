"""LM1 strobe prototype 0.4.0: unchanged wiring, raw capture, explicit timing estimates.

Standalone owner of both cameras and ESP32. Stop pinpoint before starting.
No hardware sync is claimed; camera streams are saved independently.
"""
import argparse
import os
import subprocess
import json
import math
import signal
import shutil
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
from strobe_club import analyze_club, analyze_single_flash
from full_shot_review import extract as extract_shot_data

VERSION = '0.10.0'
SYNC_CAMERA0 = False
CLUB_MODE = False
TRIGGER_TOOL = '/home/lm1/ov9281-sync-reference/ov9281_libcamera/ov9281_trigger'
MICROBURST = False
PULSE_US = 20
EXPOSURE_US = 250
GAIN = 4.
COPY_MODE = False
PREVIEW_COUNTS = 1
PATTERN = {'rateHz': 250, 'periodUs': 4000, 'pulseUs': 20, 'gapsUs': [250]*15,
           'mode':'short exposure pulsed illumination', 'dutyPercent':8.0}
CODED_PATTERN = {'rateHz':120,'periodUs':8333,'pulseUs':100,'gapsUs':[1500,2200]}
SIZE = (640, 400)
BALL_MM = 42.67
PRE = 24
POST_SECONDS = .18


def fit_copies(points, diameter, pattern=CODED_PATTERN):
    """Fit every cyclic flash phase without using an expected club speed to select it."""
    if len(points) < 3 or diameter <= 0:
        return None
    xy = np.asarray(points, dtype=float)
    direction = np.linalg.svd(xy-xy.mean(0), full_matrices=False)[2][0]
    if direction[0] < 0:
        direction = -direction
    ordered = xy[np.argsort(xy @ direction)]
    gaps = pattern['gapsUs'] + [pattern['periodUs']-sum(pattern['gapsUs'])]
    fits = []
    for phase in range(len(gaps)):
        times = np.r_[0, np.cumsum([gaps[(phase+i)%len(gaps)] for i in range(len(xy)-1)])] / 1e6
        design = np.column_stack((times-times.mean(), np.ones(len(times))))
        coefficients = np.linalg.lstsq(design, ordered, rcond=None)[0]
        residual = float(np.sqrt(np.mean(np.sum((design@coefficients-ordered)**2, axis=1))))
        velocity = coefficients[0] * BALL_MM / diameter / 1000
        speed = float(np.linalg.norm(velocity))
        if 5 < speed < 100:
            fits.append((residual, phase, speed, velocity, times))
    if not fits:
        return None
    fits.sort(key=lambda x:x[0])
    best = fits[0]
    runner = fits[1][0] if len(fits)>1 else float('inf')
    ambiguous = runner-best[0] < max(.8, best[0])
    angle = math.degrees(math.atan2(-best[3][1], best[3][0]))
    return {'speedMps': round(best[2], 2), 'imageAngleDeg': round(angle, 1),
            'residualPx': round(best[0], 3), 'phase': best[1], 'copies':len(xy),
            'ambiguous':ambiguous, 'accepted':bool(not ambiguous and best[0]<2.5 and -15<angle<80),
            'points':ordered.tolist(), 'relativeFlashTimesUs':(best[4]*1e6).tolist(),
            'status':'image-plane estimate', 'depthMeasured':False}


def analyze_frames(rows, ball, pattern=CODED_PATTERN):
    """Threshold sweep keeps the full raw record when ambient trails join flash copies."""
    background = np.median(np.stack([r['raw'].astype('float32')/64 for r in rows[-5:]]), axis=0)
    diameter = ball[2]*2
    records, best = [], None
    for i, row in enumerate(rows):
        difference = cv2.GaussianBlur(row['raw'].astype('float32')/64-background, (0,0), 1.2)
        # Touching flash silhouettes merge into one contour. Circle voting can
        # still recover their separate centres; retain the same timing gate.
        left=max(0,int(ball[0]+diameter*.5));top=20
        bottom=min(400,int(ball[1]+diameter))
        circle_image=np.clip(difference[top:bottom,left:]*3,0,255).astype('uint8')
        circles=cv2.HoughCircles(circle_image,cv2.HOUGH_GRADIENT,1,max(20,diameter*.6),
            param1=60,param2=16,minRadius=max(8,int(diameter*.36)),maxRadius=int(diameter*.56))
        if circles is not None and len(circles[0])==3:
            points=[[float(x+left),float(y+top)] for x,y,r in circles[0]]
            fit=fit_copies(points,diameter,pattern)
            if fit:
                item={'frame':i,'detector':'circle voting','sensorTimestamp':row['meta']['SensorTimestamp'],**fit}
                records.append(item)
                if fit['accepted'] and (best is None or (fit['copies'],-fit['residualPx'])>(best['copies'],-best['residualPx'])):
                    best=item
        positive = difference[max(0,int(ball[1]-220)):min(400,int(ball[1]+80)), max(0,int(ball[0]-30)):]
        peak = float(np.percentile(positive, 99.5))
        if peak < 18:
            continue
        for level in sorted(set([18., 30., 50., 80., peak*.35, peak*.55, peak*.75])):
            mask = (difference>level).astype('uint8')
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3,3),'uint8'))
            contours,_ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            points=[]
            for contour in contours:
                area=cv2.contourArea(contour)
                if not .22*math.pi*(diameter/2)**2 < area < 1.6*math.pi*(diameter/2)**2:
                    continue
                perimeter=cv2.arcLength(contour,True)
                if 4*math.pi*area/(perimeter*perimeter+1e-6)<.6:
                    continue
                m=cv2.moments(contour)
                x,y=m['m10']/m['m00'],m['m01']/m['m00']
                if x<ball[0]+diameter*.5 or y>ball[1]+diameter or y<20:
                    continue
                points.append([x,y])
            fit=fit_copies(points,diameter,pattern) if 3<=len(points)<=5 else None
            if fit:
                item={'frame':i,'thresholdCounts':round(level,2),'sensorTimestamp':row['meta']['SensorTimestamp'],**fit}
                records.append(item)
                if fit['accepted'] and (best is None or (fit['copies'],-fit['residualPx'])>(best['copies'],-best['residualPx'])):
                    best=item
    return {'best':best,'hypotheses':records,'reason':None if best else 'No unambiguous sequence of at least three flash copies resolved.'}


def frame_track(rows,ball,exposure_limit_us=1000):
    """Round, short-exposure ball silhouettes across sensor-timed frames.

    Require three consecutive positions, coherent departure from resting ball,
    stable size and low fit residual. Never treat the pulse train as extra frames.
    """
    if any(r['meta']['ExposureTime']>exposure_limit_us for r in rows):
        return {'best':None,'reason':'Exposure too long for silhouette frame tracking.','hypotheses':[]}
    background=np.median(np.stack([r['raw'].astype('float32')/64 for r in rows[-5:]]),axis=0)
    diameter=ball[2]*2
    disc=math.pi*ball[2]**2
    candidates=[]
    for i,row in enumerate(rows):
        diff=cv2.GaussianBlur(row['raw'].astype('float32')/64-background,(0,0),1.)
        found=[]
        # A ball is brighter than the mat and darker than the lit floor. Absolute
        # difference also joins the two halves when the ball crosses that boundary.
        for polarity,signal in (('bright',diff),('dark',-diff),('mixed',np.abs(diff))):
            for level in (15,25,40,60,90,130,180,250):
                mask=(signal>level).astype('uint8')
                if polarity=='mixed':
                    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),'uint8'))
                contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                for contour in contours:
                    area=cv2.contourArea(contour)
                    if not .5*disc<area<1.5*disc:continue
                    perimeter=cv2.arcLength(contour,True)
                    x,y,w,h=cv2.boundingRect(contour)
                    if 4*math.pi*area/(perimeter**2+1e-6)<.72 or max(w,h)/max(1,min(w,h))>1.4:continue
                    m=cv2.moments(contour)
                    cx,cy=m['m10']/m['m00'],m['m01']/m['m00']
                    if cx<ball[0]+diameter*.55 or cy>ball[1]+diameter*.25 or cy<ball[2] or cx>640-ball[2]:continue
                    if all(math.hypot(cx-p['x'],cy-p['y'])>diameter*.2 for p in found):
                        found.append({'x':cx,'y':cy,'diameter':math.sqrt(4*area/math.pi),'frame':i,
                                      'timestamp':row['meta']['SensorTimestamp'],'thresholdCounts':level,'polarity':polarity})
        candidates.append(found)
    tracks=[]
    rejections=[]
    for i,found in enumerate(candidates):
        for initial in found:
            track=[initial]
            for j in range(i+1,min(i+25,len(rows))):
                previous=track[-1]
                choices=[]
                for candidate in candidates[j]:
                    dx=candidate['x']-previous['x']
                    dy=candidate['y']-previous['y']
                    dt=(candidate['timestamp']-previous['timestamp'])/1e9
                    movement=math.hypot(dx,dy)
                    if dt<=0 or not diameter*.1<movement<diameter*4:continue
                    if dx<=0 or abs(dy)>dx*2:continue
                    if not .8<candidate['diameter']/initial['diameter']<1.2:continue
                    if len(track)>1:
                        a,b=track[-2:]
                        dt0=(b['timestamp']-a['timestamp'])/1e9
                        predicted=np.array([b['x'],b['y']])+np.array([b['x']-a['x'],b['y']-a['y']])*dt/dt0
                        error=float(np.linalg.norm(predicted-[candidate['x'],candidate['y']]))
                        if error>diameter*.3:continue
                    else:error=movement*.1
                    choices.append((error,candidate))
                if not choices:break
                track.append(min(choices,key=lambda c:c[0])[1])
            if len(track)<3:continue
            times=np.array([p['timestamp'] for p in track],dtype='float64')/1e9
            positions=np.array([[p['x'],p['y']] for p in track])
            design=np.column_stack((times-times.mean(),np.ones(len(times))))
            coefficients=np.linalg.lstsq(design,positions,rcond=None)[0]
            residual=float(np.sqrt(np.mean(np.sum((positions-design@coefficients)**2,axis=1))))
            velocity=coefficients[0]
            # Extrapolate the first two steps back to the resting ball; reject paths originating elsewhere.
            origin=np.array(ball[:2])
            offset=positions[0]-origin
            cross=abs(offset[0]*velocity[1]-offset[1]*velocity[0])/max(np.linalg.norm(velocity),1)
            speed=float(np.linalg.norm(velocity))*BALL_MM/diameter/1000
            blur=speed*max(rows[p['frame']]['meta']['ExposureTime'] for p in track)/1000
            failed=[]
            if residual>diameter*.08:failed.append('fit residual')
            if cross>diameter*.7:failed.append('path does not originate at resting ball')
            if not .5<speed<40:failed.append('speed outside prototype range')
            if blur>6:failed.append('exposure blur exceeds 6 mm')
            if failed:
                if len(rejections)<40:
                    rejections.append({'frames':[p['frame'] for p in track],'reasons':failed,
                                       'blurMm':round(blur,2),'residualPx':round(residual,2),'originDistancePx':round(cross,2)})
                continue
            tracks.append({'speedMps':round(speed,2),'imageAngleDeg':round(math.degrees(math.atan2(-velocity[1],velocity[0])),1),
                           'residualPx':round(residual,3),'samples':len(track),'points':positions.tolist(),
                           'frames':[p['frame'] for p in track],'sensorTimestamps':[p['timestamp'] for p in track],
                           'polarities':[p['polarity'] for p in track],
                           'blurUpperBoundMm':round(blur,2),'status':'image-plane estimate',
                           'source':'short-exposure sensor-timed silhouettes under pulsed IR',
                           'depthMeasured':False,'accepted':True})
    # Use the earliest valid interval: apparent speed changes as depth/perspective
    # changes. Disjoint later intervals are not competing launch measurements.
    tracks.sort(key=lambda t:(t['frames'][0],-t['samples'],t['residualPx']))
    best=tracks[0] if tracks else None
    if best:
        alternatives=[]
        best_positions=dict(zip(best['frames'],best['points']))
        for other in tracks[1:]:
            common=[(frame,point) for frame,point in zip(other['frames'],other['points']) if frame in best_positions]
            if len(common)>=2 and any(np.linalg.norm(np.array(point)-best_positions[frame])>diameter*.35 for frame,point in common):
                alternatives.append(other)
        if alternatives:return {'best':None,'reason':'Competing trajectories disagree.','hypotheses':tracks,'candidateCounts':[len(c) for c in candidates],'rejections':rejections}
    return {'best':best,'reason':None if best else 'No coherent run of three short-exposure ball silhouettes.',
            'hypotheses':tracks,'candidateCounts':[len(c) for c in candidates],'rejections':rejections}


def view(raw):
    # Brighten the short-exposure preview only; saved raw words remain unchanged.
    image=np.clip((raw.astype('float32')/64-16)/PREVIEW_COUNTS,0,255).astype('uint8')
    return cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)


def ball_present(raw,ball,min_contrast=70):
    """A bright centre must stand above a surrounding annulus; mat brightness cannot arm."""
    x,y,r=ball
    left,right=max(0,int(x-r*1.6)),min(640,int(x+r*1.6)+1)
    top,bottom=max(0,int(y-r*1.6)),min(400,int(y+r*1.6)+1)
    yy,xx=np.mgrid[top:bottom,left:right]
    radius=np.hypot(xx-x,yy-y)
    image=raw[top:bottom,left:right].astype('float32')/64
    centre=image[radius<r*.65]
    surround=image[(radius>r*1.2)&(radius<r*1.6)]
    if not centre.size or not surround.size:return False
    return bool(float(centre.mean())>float(np.median(surround))+min_contrast and float(np.percentile(surround,85))<float(centre.mean())*(.9 if min_contrast<70 else .7))


def result_points_for_frame(fit,frame):
    """Copy fits hold all points in one frame; tracks hold one per frame."""
    if not fit:return []
    if 'frames' in fit:
        return [fit['points'][fit['frames'].index(frame)]] if frame in fit['frames'] else []
    return fit['points'] if fit.get('frame')==frame else []


def reference_similarity(raw,reference,ball):
    x,y,r=ball
    region=(slice(max(0,int(y-r*1.3)),min(400,int(y+r*1.3))),slice(max(0,int(x-r*1.3)),min(640,int(x+r*1.3))))
    a=raw[region].astype('float32').ravel()
    b=reference[region].astype('float32').ravel()
    a-=a.mean()
    b-=b.mean()
    return float(np.dot(a,b)/max(1.,np.linalg.norm(a)*np.linalg.norm(b)))


def locate_ball(raw,anchor):
    """Locate a clear round resting ball near the placement area in one camera."""
    x,y,r=anchor
    left,right=max(0,int(x-70)),min(640,int(x+70))
    top,bottom=max(0,int(y-70)),min(400,int(y+70))
    image=np.clip((raw[top:bottom,left:right].astype('float32')/64-16)/PREVIEW_COUNTS,0,255).astype('uint8')
    image=cv2.GaussianBlur(image,(5,5),1)
    circles=cv2.HoughCircles(image,cv2.HOUGH_GRADIENT,1.2,35,param1=60,param2=20,minRadius=18,maxRadius=30)
    if circles is None:return None
    found=[]
    for cx,cy,radius in circles[0]:
        candidate=[float(cx+left),float(cy+top),float(radius)]
        if ball_present(raw,candidate):
            found.append(candidate)
    return min(found,key=lambda c:math.hypot(c[0]-x,c[1]-y)) if found else None


class Demo:
    def __init__(self,out):
        self.out=out
        out.mkdir(parents=True,exist_ok=True)
        self.stop=threading.Event()
        self.lock=threading.RLock()
        self.rows=[deque(maxlen=192),deque(maxlen=192)]
        self.cameras=[]
        self.threads=[]
        self.port=None
        self.state='starting'
        self.error=None
        self.ball=[[252.6,264.6,23.8],[267.,192.,23.4]]
        self.placement=[b[:] for b in self.ball]
        self.reference=None
        self.arm_requested=True
        self.manual_requested=False
        self.trigger_ns=None
        self.trigger_wall=None
        self.captures=[]
        self.preview=[b'',b'']
        self.timing=[{},{}]
        self.replies=[]

    def command(self,line):
        self.port.reset_input_buffer()
        self.port.write((line+'\n').encode())
        time.sleep(.12)
        reply=self.port.read(4096).decode(errors='replace')
        self.replies.append({'command':line,'reply':reply.strip()})
        if any(word in reply for word in ('rejected:','ERR ','failed')):
            raise RuntimeError(reply)
        return reply

    def start(self):
        import serial
        from picamera2 import Picamera2
        self.port=serial.Serial('/dev/ttyACM0',115200,timeout=.1,write_timeout=2)
        time.sleep(.5)
        commands=('trig off','stop','f 1 1000','rate 50','p 100','i 2500 4000','mode strobe','show') if COPY_MODE else ('trig off','stop','f 1 1000','rate 250',f'p {PULSE_US}','f 16 250','mode strobe','show')
        if CLUB_MODE:
            commands=('trig off','stop','f 1 1000',f'rate {PATTERN["rateHz"]}',f'p {PATTERN["pulseUs"]}','mode strobe','show')
        if MICROBURST:
            commands=('trig off','stop','f 1 1000','rate 250','p 2','f 3 3','mode strobe','show')
        for line in commands:
            self.command(line)
        for index in (0,1):
            camera=Picamera2(index)
            self.cameras.append(camera)
            camera.configure(camera.create_video_configuration(
                main={'size':SIZE,'format':'YUV420'},raw={'size':SIZE,'format':'R10'},
                sensor={'output_size':SIZE,'bit_depth':10},
                controls={'FrameRate':PATTERN['rateHz'] if CLUB_MODE and index==1 else 120 if COPY_MODE else 242,'AeEnable':False,'ExposureTime':(PATTERN['secondaryExposureUs'] if index==1 else 1500) if CLUB_MODE else 8000 if COPY_MODE else EXPOSURE_US,'AnalogueGain':4. if CLUB_MODE else 1. if COPY_MODE else GAIN},buffer_count=6))
            camera.start()
            thread=threading.Thread(target=self.read_camera,args=(index,camera),daemon=True)
            thread.start()
            self.threads.append(thread)
        self.state='waiting for stationary ball'
        if SYNC_CAMERA0:
            subprocess.run([TRIGGER_TOOL,'10','1'],check=True)
            for line in ('stop','tw 100','d 1000','trig on','light on','go'):
                self.command(line)
        self.out.joinpath('session.json').write_text(json.dumps({'version':VERSION,'pattern':PATTERN,
            'synchronized':False,'externallyTriggeredCameras':[0] if SYNC_CAMERA0 else [],'flashDelayUs':1000 if SYNC_CAMERA0 else 0,'cameraSize':SIZE,'esp32Replies':self.replies},indent=2))
        threading.Thread(target=self.monitor,daemon=True).start()
        threading.Thread(target=self.heartbeat,daemon=True).start()

    def read_camera(self,index,camera):
        try:
            count=0
            while not self.stop.is_set():
                request=camera.capture_request()
                try:
                    raw=request.make_array('raw').view('<u2')[:,:640].copy()
                    meta=request.get_metadata()
                    meta={k:meta.get(k) for k in ('SensorTimestamp','ExposureTime','FrameDuration','AnalogueGain')}
                finally:
                    request.release()
                with self.lock:
                    self.rows[index].append({'raw':raw,'meta':meta})
                    if count%60==0:
                        stamps=[r['meta']['SensorTimestamp'] for r in self.rows[index]]
                        intervals=np.diff(stamps)/1e6
                        self.timing[index]={'frames':count,'exposureUs':meta['ExposureTime'],
                            'gain':meta['AnalogueGain'],'medianIntervalMs':float(np.median(intervals)) if len(intervals) else None,
                            'largestIntervalMs':float(max(intervals)) if len(intervals) else None}
                if count%30==0:
                    image=view(raw)
                    x,y,r=self.ball[index]
                    cv2.circle(image,(round(x),round(y)),round(r),(0,200,0),1)
                    ok,jpg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,80])
                    if ok:self.preview[index]=jpg.tobytes()
                count+=1
        except Exception as e:
            self.error=f'Camera {index}: {e}'
            self.state='error'
            self.stop.set()

    def heartbeat(self):
        sent_led=None
        while not self.stop.wait(.7):
            try:
                led='processing' if self.state in ('capturing','saving and inspecting') else 'ready' if self.reference is not None else 'searching'
                if led!=sent_led:
                    self.command('led '+led)
                    sent_led=led
                self.port.write(b'ping\n')
                reply=self.port.read(2048).decode(errors='replace')
                if 'mode=flat' in reply or 'WATCHDOG' in reply:
                    raise RuntimeError('ESP32 left strobe mode')
            except Exception as e:
                self.error=str(e)
                self.state='error'
                print('ESP32 heartbeat error:',self.error,flush=True)
                self.stop.set()

    def monitor(self):
        stable_since=None
        last=None
        next_locate=0.
        try:
            while not self.stop.wait(.008):
                with self.lock:
                    if len(self.rows[0])<PRE or len(self.rows[1])<PRE:continue
                    row=self.rows[0][-1]
                    if row['meta']['SensorTimestamp']==last:continue
                    last=row['meta']['SensorTimestamp']
                    raw=row['raw']
                if not MICROBURST and self.reference is None and self.trigger_ns is None and time.monotonic()>=next_locate:
                    next_locate=time.monotonic()+.25
                    with self.lock:raw_pair=[self.rows[j][-1]['raw'] for j in (0,1)]
                    located=[locate_ball(raw_pair[j],self.placement[j]) for j in (0,1)]
                    required=located[:1] if SYNC_CAMERA0 else located
                    if not all(required):
                        stable_since=None
                        self.arming_reference=None
                        continue
                    # Camera 1's free-running short exposures can miss the burst.
                    # Use the triggered view to arm; retain its secondary reference.
                    located=[located[j] or self.ball[j] for j in (0,1)]
                    if any(math.hypot(located[j][0]-self.ball[j][0],located[j][1]-self.ball[j][1])>4 for j in (0,1)):
                        stable_since=None
                        self.arming_reference=None
                    self.ball=located
                x,y,r=self.ball[0]
                roi=raw[int(y-r*.65):int(y+r*.65),int(x-r*.65):int(x+r*.65)].astype('float32')/64
                level=float(roi.mean())
                if self.trigger_ns is not None:
                    if time.monotonic()-self.trigger_wall>=POST_SECONDS:
                        self.save_capture()
                        stable_since=None
                    continue
                if self.manual_requested:
                    self.manual_requested=False
                    self.trigger_ns=last
                    self.trigger_wall=time.monotonic()
                    self.state='capturing'
                    continue
                if self.reference is None:
                    if self.arm_requested and ball_present(raw,self.ball[0],3 if MICROBURST else 70):
                        stable_since=stable_since or time.monotonic()
                        # Frame brightness changes as flashes enter/leave the exposure; compare shape instead.
                        if not MICROBURST and getattr(self,'arming_reference',None) is not None and reference_similarity(raw,self.arming_reference,self.ball[0])<.93:
                            stable_since=time.monotonic()
                        self.arming_reference=raw
                        if time.monotonic()-stable_since>1.2:
                            # Retain two-view full reference, not just a brightness number.
                            with self.lock:
                                self.reference=[np.median(np.stack([q['raw'] for q in list(self.rows[j])[-8:]]),axis=0).astype('uint16') if MICROBURST else self.rows[j][-1]['raw'].copy() for j in (0,1)]
                            self.resting_level=float(self.reference[0][int(y-r*.65):int(y+r*.65),int(x-r*.65):int(x+r*.65)].mean()/64)
                            self.state='armed — take a chip' if MICROBURST else 'armed — take a wedge shot'
                            print(self.state,flush=True)
                    else:
                        stable_since=None
                        self.arming_reference=None
                    self.previous_level=level
                else:
                    similarity=reference_similarity(raw,self.reference[0],self.ball[0])
                    departed=level<self.resting_level-3 if MICROBURST else similarity<.8
                    if departed:
                        self.trigger_ns=last
                        self.trigger_wall=time.monotonic()
                        self.state='capturing'
                        print('departure trigger',last,'similarity',round(similarity,3),flush=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error=str(e)
            self.state='error'
            self.stop.set()

    def save_capture(self):
        self.state='saving and inspecting'
        destination=self.out/f'capture-{time.time_ns()}'
        destination.mkdir()
        with self.lock:
            streams=[list(q) for q in self.rows]
        summary={'version':VERSION,'pattern':PATTERN,'triggerSensorTimestamp':self.trigger_ns,
                 'synchronized':False,'ballReferences':self.ball,'cameras':[],'name':destination.name}
        summary.update(flashDelayUs=1000 if SYNC_CAMERA0 else 0,
                       timingSource='sensor exposure metadata; ESP flash phase inferred',
                       preCaptureFrames=PRE,postCaptureSeconds=POST_SECONDS)
        calibration=destination/'calibration'
        calibration.mkdir()
        for filename in ('intrinsics.json','intrinsics-secondary.json','rig.json','stereo/active.json'):
            source=Path('/var/lib/pinpoint')/filename
            if source.is_file():shutil.copyfile(source,calibration/source.name)
        contact=[]
        for index,rows in enumerate(streams):
            # Preserve timestamps from each sensor; never pair nearest frames as simultaneous.
            start=max(0,next((i for i,r in enumerate(rows) if r['meta']['SensorTimestamp']>=self.trigger_ns),len(rows)-1)-PRE)
            rows=rows[start:]
            folder=destination/f'cam{index}'
            folder.mkdir()
            metadata=[]
            if self.reference is not None:
                cv2.imwrite(str(folder/'reference.png'),self.reference[index])
            for i,row in enumerate(rows):
                cv2.imwrite(str(folder/f'raw-{i:03}.png'),row['raw'],[cv2.IMWRITE_PNG_COMPRESSION,1])
                metadata.append({'frame':i,**row['meta']})
            result=analyze_frames(rows,self.ball[index],PATTERN) if COPY_MODE else frame_track(rows,self.ball[index])
            club=analyze_single_flash(rows,self.ball[index],self.trigger_ns) if CLUB_MODE and index==0 else analyze_club(rows,self.ball[index],self.trigger_ns)
            summary['cameras'].append({'camera':index,'metadata':metadata,'analysis':result,'clubAnalysis':club})
            near=[i for i,r in enumerate(rows) if -12e6<r['meta']['SensorTimestamp']-self.trigger_ns<50e6]
            tiles=[]
            for i in near[:16]:
                tile=view(rows[i]['raw'])
                fit=result['best']
                for x,y in result_points_for_frame(fit,i):
                    cv2.circle(tile,(round(x),round(y)),23,(0,255,0),2)
                tile=cv2.resize(tile,(320,200))
                dt=(rows[i]['meta']['SensorTimestamp']-self.trigger_ns)/1e6
                cv2.putText(tile,f'C{index} f{i} {dt:+.1f}ms',(7,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,255,255),1)
                tiles.append(tile)
            if tiles:
                while len(tiles)%4:tiles.append(np.zeros_like(tiles[0]))
                contact.extend([np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)])
        if contact:cv2.imwrite(str(destination/'contact.jpg'),np.vstack(contact))
        destination.joinpath('summary.json').write_text(json.dumps(summary,indent=2))
        extracted=None
        if CLUB_MODE:
            try:
                extracted=extract_shot_data(destination)
                destination.joinpath('review.json').write_text(json.dumps(extracted,indent=2))
            except Exception as error:
                # A secondary review failure must not lose the raw capture.
                print('Extended review unavailable:',str(error),flush=True)
        self.captures.append({'name':destination.name,'results':[c['analysis']['best'] for c in summary['cameras']],
                             'clubResults':[c['clubAnalysis'] for c in summary['cameras']],'extractedData':extracted})
        print('saved',destination.name,json.dumps(self.captures[-1]['results']),flush=True)
        # A removal or occlusion is retained as a capture; the UI never calls it a measured shot.
        self.reference=None
        self.trigger_ns=None
        self.arm_requested=True
        self.state='waiting for stationary ball'

    def status(self):
        return {'version':VERSION,'state':self.state,'error':self.error,'pattern':PATTERN,
                'timing':self.timing,'captures':self.captures[-20:],
                'notice':'Primary externally triggered; secondary free-running. App estimates use shared-flash exposure matches where available. Club identity and calibration need validation; spin is unmeasured.' if CLUB_MODE else 'Unsynchronized cameras. Numbers are image-plane estimates; spin and direction unavailable.'}

    def close(self):
        self.stop.set()
        if SYNC_CAMERA0:
            if self.port:
                try:self.command('trig off')
                except Exception:pass
            subprocess.run([TRIGGER_TOOL,'10','0'])
            time.sleep(.2)
        for camera in self.cameras:
            try:camera.stop()
            except Exception:pass
        for thread in self.threads:thread.join(timeout=2)
        for camera in self.cameras:
            try:camera.close()
            except Exception:pass
        if self.port:
            try:
                self.command('mode flat')
                self.command('led searching')
            except Exception:pass
            self.port.close()


HTML='''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>LM1 Strobe Lab</title>
<style>body{font:17px system-ui;background:#101820;color:#eef5f7;max-width:1050px;margin:24px auto;padding:16px}h1{font-size:30px}button{padding:12px 20px;margin:8px;border:0;border-radius:8px;background:#a5e0bf;font-size:16px}img{max-width:100%;border-radius:8px}.views{display:flex;gap:12px}.views img{width:48%}#state{font-size:24px;color:#a5e0bf}small{color:#c1cbd0}a{color:#a5e0bf}pre{white-space:pre-wrap}</style>
<h1>LM1 Strobe Lab <small>v0.3.1</small></h1><p id="state">Connecting…</p>
<p>Place the ball inside the green circle. Wait for Armed, then take a wedge shot. Every departure is saved for review. Replace the ball and wait for the next Armed.</p>
<div class="views"><img id="c0"><img id="c1"></div>
<button onclick="fetch('/arm',{method:'POST'})">Re-arm</button><button onclick="fetch('/capture',{method:'POST'})">Save test capture</button>
<p><small>20 µs flashes every 250 µs • 250 µs exposure • 242 fps • raw images. Tracks follow bright and dark ball silhouettes. Positions are timed by the camera; speed and angle remain image-plane estimates.</small></p>
<div id="shots"></div><div id="club"></div><pre id="extracted"></pre><pre id="timing"></pre>
<script>async function dataRefresh(){try{let s=await(await fetch('/status')).json();let latest=s.captures.at(-1),d=latest&&latest.extractedData;if(!d)return;let b=d.ball,f=b.fits[0],lines=['Latest shot — projected estimates with a level camera'];if(f)lines.push('Ball: '+f.projectedBallSpeedMps+' m/s; launch '+f.launchAngleDeg+' degrees; '+b.track.length+' tracked positions');lines.push('Observed flight: '+b.observedDurationMs+' ms; horizontal displacement '+b.horizontalDisplacementM+' m; vertical displacement '+b.verticalDisplacementM+' m');if(b.departureBracket)lines.push('Ball departure interval: '+b.departureBracket.intervalMs+' ms');for(let c of d.clubProvisionalPairs)lines.push('Provisional club pair: '+c.speedMps+' m/s; assumed attack '+c.angleDeg+' degrees; provisional smash '+c.smashFactorProvisional+' (point identity unverified)');for(let warning of b.warnings)lines.push(warning);document.querySelector('#extracted').textContent=lines.join(String.fromCharCode(10))}catch(e){}}setInterval(dataRefresh,1500)</script>
<script>async function clubRefresh(){try{let s=await(await fetch('/status')).json();document.querySelector('#club').textContent=s.captures.length?(s.captures.at(-1).clubResults||[]).map((c,i)=>'Camera '+i+' club: '+(c.clubSpeedMps===null?'unavailable':c.clubSpeedMps+' m/s experimental projected speed')+'; '+c.reason).join(' | '):'Club review will appear after a capture.'}catch(e){}}setInterval(clubRefresh,1500)</script>
<script>async function refresh(){try{let s=await(await fetch('/status')).json();document.querySelector('#state').textContent=s.error||s.state;for(let j=0;j<2;j++)document.querySelector('#c'+j).src='/preview/'+j+'?t='+Date.now();document.querySelector('#timing').textContent=JSON.stringify(s.timing,null,2);document.querySelector('#shots').innerHTML=s.captures.slice().reverse().map(c=>'<p><a href="/captures/'+c.name+'/contact.jpg" target="_blank">'+c.name+'</a> — '+c.results.map((r,i)=>'Camera '+i+': '+(r?r.speedMps+' m/s, '+r.imageAngleDeg+'° image angle':'copies unresolved')).join(' | ')+'</p>').join('')}catch(e){document.querySelector('#state').textContent='Connection unavailable'}}setInterval(refresh,1500);refresh()</script>'''


def handler(demo):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,data,kind='application/json',code=200):
            self.send_response(code)
            self.send_header('Content-Type',kind)
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            path=self.path.split('?')[0]
            if path=='/':return self.send(HTML.encode(),'text/html; charset=utf-8')
            if path=='/status':return self.send(json.dumps(demo.status()).encode())
            if path in ('/preview/0','/preview/1'):return self.send(demo.preview[int(path[-1])],'image/jpeg')
            if path.startswith('/captures/'):
                candidate=(demo.out/path.removeprefix('/captures/')).resolve()
                if candidate.is_relative_to(demo.out.resolve()) and candidate.name in ('contact.jpg','summary.json','review.json') and candidate.is_file():
                    return self.send(candidate.read_bytes(),'image/jpeg' if candidate.suffix=='.jpg' else 'application/json')
            self.send(b'{}',code=404)
        def do_POST(self):
            if self.path=='/arm':
                if demo.trigger_ns is not None:return self.send(b'{"error":"capture in progress"}',code=409)
                demo.reference=None
                demo.arm_requested=True
                demo.state='waiting for stationary ball'
            elif self.path=='/capture':demo.manual_requested=True
            else:return self.send(b'{}',code=404)
            self.send(b'{"ok":true}')
    return Handler


def main():
    global COPY_MODE, PREVIEW_COUNTS, PATTERN, PRE, POST_SECONDS, HTML, EXPOSURE_US, GAIN, PULSE_US, MICROBURST, CLUB_MODE
    parser=argparse.ArgumentParser()
    parser.add_argument('--club-rate-hz',type=int,choices=(120,),default=120,
                        help='Verified trigger rate; higher rates currently lose alternate primary frames')
    parser.add_argument('--out',type=Path,default=Path('/home/lm1/strobe-demo-v0.5.3/captures'))
    parser.add_argument('--ball-reference',type=Path,help='Use measured stationary-ball positions from a bench report')
    parser.add_argument('--microburst',action='store_true',help='Three 2 us pulses starting at 0, 3 and 6 us')
    parser.add_argument('--pulse-us',type=int,default=20)
    parser.add_argument('--exposure-us',type=int,default=250)
    parser.add_argument('--gain',type=float,default=4.)
    parser.add_argument('--copies',action='store_true',help='Three flash copies within each long exposure')
    parser.add_argument('--club-mode',action='store_true',help='Externally triggered single-flash club visibility trial')
    parser.add_argument('--sync-camera0',action='store_true',help='External trigger on camera 0 only; camera 1 stays free-running')
    parser.add_argument('--port',type=int,default=3113)
    args=parser.parse_args()
    global SYNC_CAMERA0
    SYNC_CAMERA0=args.sync_camera0
    CLUB_MODE=args.club_mode
    if CLUB_MODE and (args.copies or args.microburst or not SYNC_CAMERA0):parser.error('club mode requires --sync-camera0 and excludes other burst modes')
    if SYNC_CAMERA0 and not (args.copies or CLUB_MODE):parser.error('external triggering requires copies or club mode')
    if SYNC_CAMERA0:
        os.environ['LIBCAMERA_RPI_CONFIG_FILE']='/home/lm1/ov9281-sync-reference/ov9281_libcamera/timeout.yaml'
    if args.microburst and args.copies:parser.error('microburst and long-exposure copies are separate modes')
    MICROBURST=args.microburst
    if MICROBURST:args.pulse_us=2;args.exposure_us=9
    if not 2<=args.pulse_us<=500:parser.error('pulse width must be 2..500 us')
    if not args.copies and args.pulse_us>25:parser.error('this repeating pattern limits pulse width to 25 us at 10% duty')
    PULSE_US=args.pulse_us
    EXPOSURE_US=args.exposure_us; GAIN=args.gain
    if not args.copies:
        HTML=HTML.replace('250 µs exposure',f'{EXPOSURE_US} µs exposure')
        HTML=HTML.replace('20 µs flashes',f'{PULSE_US} µs flashes')
        PATTERN={**PATTERN,'pulseUs':PULSE_US,'dutyPercent':250*16*PULSE_US/10000}
    if args.copies:
        COPY_MODE=True; PREVIEW_COUNTS=4; PRE=4
        PATTERN={'rateHz':50,'periodUs':20000,'pulseUs':100,'gapsUs':[2500,4000],'mode':'three copies within one exposure','dutyPercent':1.5}
        HTML=HTML.replace('20 µs flashes every 250 µs • 250 µs exposure • 242 fps • raw images. Tracks follow bright and dark ball silhouettes. Positions are timed by the camera; speed and angle remain image-plane estimates.', 'Three 100 µs flashes per 20 ms cycle • burst spans 6.6 ms • 8 ms exposure. Camera 0 uses external triggers; camera 1 is free-running. Measurements require three separated copies inside one image.')
    if CLUB_MODE:
        rate=args.club_rate_hz
        PRE=round(rate*.35);POST_SECONDS=.25
        pulse=250
        PATTERN={'rateHz':rate,'periodUs':round(1e6/rate),'pulseUs':pulse,'gapsUs':[],
                 'secondaryExposureUs':8000,
                 'mode':'single flash club visibility trial','dutyPercent':rate*pulse/10000}
        HTML=HTML.replace('<p><small>20 µs flashes', f'<p><small>Club visibility trial: {rate} captures/s, one {PATTERN["pulseUs"]} µs flash per trigger; camera shutters 1.5 / {PATTERN["secondaryExposureUs"]/1000:g} ms. Club measurements are provisional estimates.</small></p><p hidden><small>20 µs flashes')
    HTML=HTML.replace('v0.3.1','v'+VERSION)
    if MICROBURST:
        PATTERN={'rateHz':250,'periodUs':4000,'pulseUs':2,'gapsUs':[3,3],'mode':'three-pulse 8 us burst, unsynchronized','dutyPercent':0.15}
        HTML=HTML.replace('2 µs flashes every 250 µs','Three 2 µs pulses at 0 / 3 / 6 µs, burst repeated every 4 ms')
    demo=Demo(args.out)
    if args.ball_reference:
        records=json.loads(args.ball_reference.read_text())
        demo.ball=[next(item['ball'] for item in records if item['camera']==j) for j in (0,1)]
        demo.placement=[b[:] for b in demo.ball]
    server=ThreadingHTTPServer(('0.0.0.0',args.port),handler(demo))
    def stop(*_):demo.stop.set()
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    try:
        demo.start()
        server.timeout=.5
        while not demo.stop.is_set():server.handle_request()
    finally:
        print('Demo stopped:',demo.error or 'stop requested',flush=True)
        demo.close()
        server.server_close()


if __name__=='__main__':main()
