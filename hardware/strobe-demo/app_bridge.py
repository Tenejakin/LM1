"""Strobe app bridge 0.5.0. Capture health, recorded timing and longer shot sequences."""
import asyncio
import base64
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
import sys
from urllib.request import urlopen

import cv2
import numpy as np

VERSION = '0.5.0'
ROOT = Path(os.getenv('STROBE_CAPTURE_ROOT', '/home/lm1/strobe-demo-v0.6.0/captures'))
DEST = Path(os.getenv('STROBE_APP_CAPTURE_ROOT', '/var/lib/pinpoint/strobe-app-captures'))
URL = os.getenv('STROBE_DEMO_URL', 'http://127.0.0.1:3113')


def metric(value, unit, reason, confidence=.4):
    return dict(value=value, unit=unit, status='estimated' if value is not None else 'unavailable',
                reason=reason, confidence=confidence if value is not None else 0)


def convert(source, review, destination):
    """Adapt real saved image-plane observations to the existing app protocol."""
    summary = json.loads((source / 'summary.json').read_text())
    ball = review['ball']; track = ball['track']; fits = ball['fits']
    first = fits[0] if fits else {}
    metadata = summary['cameras'][0]['metadata']
    frame = track[0]['frame'] if track else metadata[-1]['frame']
    destination.mkdir(parents=True, exist_ok=True)
    # Preserve frame indexes for app frame requests. The independent second camera
    # is deliberately not presented as a synchronized stereo pair.
    preview = None
    for item in metadata:
        raw = cv2.imread(str(source / 'cam0' / f'raw-{item["frame"]:03}.png'), -1)
        if raw is None:
            raise ValueError('Missing primary raw frame')
        image = np.clip((raw.astype('float32') / 64 - 18) / 4, 0, 255).astype('uint8')
        ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 65])
        if not ok:
            raise ValueError('Could not encode shot image')
        (destination / f'frame-{item["frame"]:04}.jpg').write_bytes(encoded.tobytes())
        if item['frame'] == frame:
            preview = base64.b64encode(encoded).decode()
    if preview is None:
        raise ValueError('Moving frame missing from metadata')
    reason = 'Provisional image-plane estimate; level camera and resting-ball diameter scale assumed.'
    metrics = {
        'ballSpeedMps': metric(first.get('projectedBallSpeedMps'), 'm/s', reason),
        'launchAngleDeg': metric(first.get('launchAngleDeg'), 'deg', reason),
        'startDirectionDeg': metric(0 if fits else None, 'deg',
            'Direction is unmeasured. Zero is assumed solely for the app flight model.', .05),
    }
    for key, unit in [('clubSpeedMps','m/s'), ('smashFactor','ratio'), ('attackAngleDeg','deg'),
                      ('clubPathDeg','deg'), ('spinRpm','rpm'), ('spinAxisDeg','deg'),
                      ('strikeXmm','mm'), ('strikeYmm','mm')]:
        metrics[key] = metric(None, unit, 'Not verified by this strobe capture.')
    stereo = review.get('stereoFlash') or {}
    stereo_ball = stereo.get('ball')
    stereo_club = stereo.get('club')
    if stereo_ball:
        basis = 'Calibrated stereo rays at the inferred shared flash; level camera and image-right target line assumed. Requires reference validation.'
        confidence=.2 if stereo_ball.get('maxRayGapMm',0)>6 else .5
        if confidence==.2:basis+=' Ray mismatch exceeds 6 mm; calibration bias can change the direction sign. Low-confidence estimate.'
        metrics.update(ballSpeedMps=metric(stereo_ball['speedMps'],'m/s',basis,confidence),
                       launchAngleDeg=metric(stereo_ball['angleDeg'],'deg',basis,confidence),
                       startDirectionDeg=metric(stereo_ball['directionDeg'],'deg',basis,min(.45,confidence)))
    if stereo_club:
        details = stereo_club['diagnostics']
        basis = (f"Provisional {details.get('point','club feature')} stereo track in {details['acceptedFrames']} pre-departure frames; "
                 'feature travels with the club but may differ from face-centre speed. Level camera assumed; contact time inferred.')
        confidence=.2 if details['acceptedFrames']==2 else .35
        if details['acceptedFrames']==2:basis+=' Two points cannot check identity or swing curvature.'
        metrics.update(clubSpeedMps=metric(stereo_club['speedMps'],'m/s',basis,confidence),
                       attackAngleDeg=metric(stereo_club['angleDeg'],'deg',basis,confidence),
                       clubPathDeg=metric(stereo_club['directionDeg'],'deg',basis,confidence))
        speed=metrics['ballSpeedMps']['value']
        if speed is not None:
            metrics['smashFactor']=metric(speed/stereo_club['speedMps'],'ratio',
                'Ratio of estimated ball and club-feature speeds. '+basis,min(.3,confidence))
    elif stereo.get('warnings'):
        for key in ('clubSpeedMps','smashFactor','attackAngleDeg','clubPathDeg'):
            metrics[key]['reason']=' '.join(stereo['warnings'])
    mono_pair=None
    if not stereo_club and summary.get('version') in ('0.9.1','0.10.0'):
        # The user accepts two-position arithmetic under the level-camera
        # assumption. Keep the unverified feature identity visible in the grade.
        pairs=[*review.get('clubProvisionalPairs',[]),*(review.get('shaftHead') or {}).get('pairs',[])]
        for pair in reversed(pairs):
            speed=pair['speedMps'];ball_speed=metrics['ballSpeedMps']['value']
            if (0<pair['intervalMs']<=25 and 1<speed<80 and pair['horizontalVelocityMps']>0
                and -60<pair['angleDeg']<40 and ball_speed is not None and .4<ball_speed/speed<2.2):
                mono_pair=pair;break
        if mono_pair:
            basis=('Two-point image-plane club-feature estimate; feature identity is unverified. '
                   'Level camera and club at resting-ball depth assumed. Rotation and changing reflections can bias the result.')
            confidence=.15
            if mono_pair.get('templateScore') is not None:
                confidence=.25
                basis+=f" Shaft-guided head-region patch correlation {mono_pair['templateScore']:.3f}; interval velocity before departure, not exact impact velocity."
            metrics.update(clubSpeedMps=metric(mono_pair['speedMps'],'m/s',basis,confidence),
                           attackAngleDeg=metric(mono_pair['angleDeg'],'deg',basis,confidence),
                           smashFactor=metric(metrics['ballSpeedMps']['value']/mono_pair['speedMps'],'ratio',
                               'Estimated ball speed divided by projected club-feature speed. '+basis,min(confidence,metrics['ballSpeedMps']['confidence'])))
            metrics['clubPathDeg']['reason']='Only a side-view club pair was resolved; left/right club path needs the same feature triangulated in both cameras.'
    bracket = ball.get('departureBracket') or {}
    timestamps = [item['SensorTimestamp'] for item in metadata]
    interval = np.median(np.diff(timestamps)) / 1e9 if len(timestamps) > 1 else 0
    captured_at = datetime.fromtimestamp(int(source.name.split('-')[-1]) / 1e9, timezone.utc).isoformat()
    result = dict(id=source.name, captureId=source.name, capturedAt=captured_at, clubId='lob-wedge',
        mode='full-shot', classification='motion-observed' if fits else 'unconfirmed-departure',
        frameCount=len(metadata), captureDurationMs=(timestamps[-1]-timestamps[0])/1e6,
        measuredFps=1/interval if interval else None, impactFrameIndex=None,
        coarseDepartureFrameIndex=frame, lastStationaryFrameIndex=bracket.get('lastStationaryFrame'),
        firstMovingFrameIndex=bracket.get('firstMovingFrame', frame if track else None),
        imageFrameIndex=frame, image=dict(mimeType='image/jpeg',base64=preview),
        warnings=[reason, ('Direction uses calibrated paired views and an assumed target line.' if stereo_ball
                  else 'Direction is unmeasured; app uses an assumed 0 degrees.'), 'Spin and carry are modeled, not observed.',
                  'Departure bracket is not an exact impact timestamp.', *ball['warnings'], *stereo.get('warnings',[]),
                  *review.get('captureQuality',{}).get('warnings',[])],
        track=[dict(frameIndex=p['frame'],x=p['point'][0],y=p['point'][1],score=.4) for p in track],
        measurements=dict(method='strobe-common-flash-stereo-v1' if stereo_ball else 'strobe-image-plane-v1', metrics=metrics,
            shotEvidence=dict(status='motion-only',clubFrames=0,
                reason='Ball motion observed; club identity and contact remain unverified.')),
        strobeBridgeVersion=VERSION)
    if mono_pair:
        result['warnings'].append('Club speed, smash and attack use an unverified two-point side-view feature; club path remains unavailable.')
    (destination / 'strobe-review.json').write_text(json.dumps(review))
    if review.get('captureQuality'):
        (destination / 'raw-quality.json').write_text(json.dumps(review['captureQuality'],indent=2))
    manifest = {key: result[key] for key in ('frameCount','impactFrameIndex','coarseDepartureFrameIndex',
                 'lastStationaryFrameIndex','firstMovingFrameIndex')}
    manifest.update(frameTimesMs=[(t-timestamps[0])/1e6 for t in timestamps],
                    ballReference=summary['ballReferences'][0])
    (destination / 'capture.json').write_text(json.dumps(manifest))
    return result


async def main():
    # These must be disabled before constructing the existing peripheral: only
    # the demo may open the cameras or serial controller.
    os.environ.update(PINPOINT_AUTO_BALL_DETECTION='false', PINPOINT_BLE_PREVIEW='false',
                      PINPOINT_LIGHT_CONTROL='none', PINPOINT_CAPTURE_BACKEND='camera',
                      PINPOINT_ROLLING_CAPTURE_PATH=str(DEST))
    sys.path.insert(0, '/opt/pinpoint')
    from pinpoint_ble import PinpointBlePeripheral
    from pinpoint_protocol import CommandError
    from full_shot_review import extract
    from stereo_flash_review import review as stereo_review
    from shaft_head_review import review as shaft_head_review
    from raw_capture_quality import analyze as capture_quality

    class BridgePeripheral(PinpointBlePeripheral):
        def _start_ball_monitor(self):
            pass

    peripheral = BridgePeripheral(asyncio.get_running_loop())
    protocol = peripheral.protocol
    protocol.club_id = 'lob-wedge'
    original_status = protocol.status
    original_command = protocol._handle_command
    original_summary = protocol._capture_summary
    demo_status = {}
    pending_updates=[]
    client_connected=False

    async def handle_command(command):
        nonlocal client_connected
        allowed = {'status','listShots','listPutts','listCaptures','setClub','arm','disarm',
                   'latestCapturePreview','captureFrame','captureClip','captureContactSheet',
                   'captureFrameUploadStatus','uploadCaptureFrames'}
        if command.get('type') not in allowed:
            raise CommandError('This command is unavailable while the strobe demo owns the cameras. Stop the demo and use the normal service for calibration.')
        if command.get('type') == 'arm' and command.get('mode', 'full-shot') != 'full-shot':
            raise CommandError('The current strobe demo supports full-shot chips only.')
        await original_command(command)
        if command.get('type')=='status':
            client_connected=True
            # A reconnect completes notification setup before sending status.
            # Hold revised existing shots until then, so no fragments are lost.
            while pending_updates:
                analysis=pending_updates.pop(0)
                await peripheral.send_message(dict(type='capture',data=protocol._capture_summary(analysis)))

    protocol._handle_command = handle_command

    def capture_summary(capture):
        result=original_summary(capture)
        stereo=(capture.get('measurements') or {}).get('method')=='strobe-common-flash-stereo-v1'
        if stereo:
            tracking=result['measurements']['tracking']
            tracking.update(status='stereo-matched',source='stereo')
        return result

    protocol._capture_summary=capture_summary

    def status():
        result = original_status()
        timing = (demo_status.get('timing') or [{}])[0]
        result.update(automaticCapture=True, cameraConnected=bool(demo_status) and not demo_status.get('error'),
                      fps=round(1000/timing['medianIntervalMs']) if timing.get('medianIntervalMs') else 0,
                      exposureUs=timing.get('exposureUs',1491), strobeBridgeVersion=VERSION)
        camera = result.setdefault('camera', {})
        detection = camera.setdefault('ballDetection', {})
        detection['state'] = 'detected' if protocol.ball_present else 'searching'
        return result

    protocol.status = status
    stopped = asyncio.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(name, stopped.set)
    await peripheral.start()
    known = {p.parent.name for p in DEST.glob('capture-*/analysis.json')}
    previous_state = None
    try:
        while not stopped.is_set():
            try:
                def read_status():
                    with urlopen(URL + '/status', timeout=3) as response:
                        return json.load(response)
                demo_status = await asyncio.to_thread(read_status)
                completed = sorted(ROOT.glob('capture-*/summary.json'))[-10:]
                for path in completed:
                    source = path.parent
                    summary = json.loads(path.read_text())
                    previous=None
                    if source.name in known:
                        previous=json.loads((DEST/source.name/'analysis.json').read_text())
                        if previous.get('strobeBridgeVersion')==VERSION or summary.get('version') not in ('0.9.1','0.10.0'):
                            continue
                    if summary.get('version') not in ('0.7.1','0.8.0','0.9.0','0.9.1','0.10.0'):
                        continue
                    # New summaries precede review completion. Wait until the demo
                    # finishes saving; older captures can be reviewed offline.
                    if demo_status.get('state') == 'saving and inspecting':
                        continue
                    review_path = source / 'review.json'
                    review = json.loads(review_path.read_text()) if review_path.exists() else await asyncio.to_thread(extract, source)
                    review['captureQuality']=await asyncio.to_thread(capture_quality,source,review['ball']['track'])
                    try:
                        review['shaftHead']=await asyncio.to_thread(shaft_head_review,source)
                    except Exception as error:
                        review['shaftHead']=dict(pairs=[],failure=str(error))
                    try:
                        review['stereoFlash']=await asyncio.to_thread(stereo_review,source,review['ball'])
                    except Exception as error:
                        review['stereoFlash']=dict(ball=None,club=None,warnings=['Stereo review unavailable: '+str(error)])
                    analysis = await asyncio.to_thread(convert, source, review, DEST/source.name)
                    if previous:
                        for key in ('capturedAt','clubId','bagClubId','bagClubName','mode'):
                            if key in previous:analysis[key]=previous[key]
                        (DEST/source.name/'analysis.json').write_text(json.dumps(analysis))
                        protocol.captures=[analysis if c['id']==source.name else c for c in protocol.captures]
                        if source.name in {c.get('name') for c in demo_status.get('captures',[])}:
                            if client_connected:
                                await peripheral.send_message(dict(type='capture',data=protocol._capture_summary(analysis)))
                            else:
                                pending_updates.append(analysis)
                    elif source.name not in {c.get('name') for c in demo_status.get('captures', [])}:
                        # Backfill preserves the original shot time and wedge selection.
                        (DEST/source.name/'analysis.json').write_text(json.dumps(analysis))
                        protocol.captures.insert(0, analysis)
                        del protocol.captures[protocol.capture_retention:]
                    else:
                        protocol.ball_present = False
                        await protocol._finish_camera_capture(analysis, source.name)
                    known.add(source.name)
                    logging.info('Registered strobe capture %s (%s)', source.name, analysis['classification'])
                state = demo_status.get('state')
                if state != previous_state:
                    protocol.ball_present = bool(state and state.startswith('armed'))
                    protocol.state = ('armed' if protocol.ball_present else 'processing'
                                      if state in ('capturing','saving and inspecting') else 'ready')
                    await peripheral.send_message(dict(type='ballPresence', data=dict(present=protocol.ball_present)))
                    await peripheral.send_message(dict(type='status', data=status()))
                    previous_state = state
            except Exception:
                logging.exception('Strobe bridge poll failed; will retry')
                demo_status = {}
                if previous_state != 'offline':
                    protocol.ball_present = False
                    protocol.state = 'ready'
                    await peripheral.send_message(dict(type='status', data=status()))
                    previous_state = 'offline'
            try:
                await asyncio.wait_for(stopped.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass
    finally:
        await peripheral.stop()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
