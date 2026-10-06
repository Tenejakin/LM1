"""Bridge validation 0.1.0: replay real captures; never open cameras or serial."""
import asyncio
import json
import os
from pathlib import Path
import sys

from app_bridge import convert
from full_shot_review import extract

async def main():
    root=Path('/home/lm1/strobe-demo-v0.6.0/captures')
    out=Path('/home/lm1/app-bridge-validation-v0.1.0')
    os.environ.update(PINPOINT_LIGHT_CONTROL='none',PINPOINT_CAPTURE_BACKEND='camera',
                      PINPOINT_ROLLING_CAPTURE_PATH=str(out))
    sys.path.insert(0,'/opt/pinpoint')
    from pinpoint_protocol import PinpointProtocol
    from ball_detector import capture_frame_preview
    events=[]
    async def send(message): events.append(message)
    protocol=PinpointProtocol(send); protocol.club_id='lob-wedge'
    for path in sorted(root.glob('capture-*/summary.json'))[-10:]:
        capture=convert(path.parent,extract(path.parent),out/path.parent.name)
        assert capture['measurements']['metrics']['clubSpeedMps']['value'] is None
        assert capture['measurements']['metrics']['spinRpm']['value'] is None
        assert capture['measurements']['metrics']['startDirectionDeg']['confidence']==.05
        await protocol._finish_camera_capture(capture,path.parent.name)
        frame=capture_frame_preview(path.parent.name,capture['imageFrameIndex'])
        assert frame['base64'] and frame['frameCount']==capture['frameCount']
    captures=[event['data'] for event in events if event['type']=='capture']
    assert len(captures)==10
    (out/'app-captures.json').write_text(json.dumps(captures))
    print(f'PASS: {len(captures)} real captures persisted, replayed and emitted through app protocol')

if __name__=='__main__':asyncio.run(main())
