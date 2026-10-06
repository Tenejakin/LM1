"""Extended-save replay validation 0.1.0; runs outside live camera ownership."""
import json,sys
from pathlib import Path
import cv2
import demo

source=Path(sys.argv[1]);out=Path(sys.argv[2]);summary=json.loads((source/'summary.json').read_text())
instance=demo.Demo(out);instance.ball=summary['ballReferences'];instance.trigger_ns=summary['triggerSensorTimestamp']
for j,camera in enumerate(summary['cameras']):
    instance.rows[j].extend({'raw':cv2.imread(str(source/f'cam{j}'/f'raw-{meta["frame"]:03}.png'),-1),'meta':meta} for meta in camera['metadata'])
demo.CLUB_MODE=True;demo.COPY_MODE=False;demo.PRE=24
instance.save_capture()
saved=out/instance.captures[-1]['name'];review=json.loads((saved/'review.json').read_text())
assert len(review['ball']['track'])>=3,review
assert review['ball']['fits'][0]['projectedBallSpeedMps']>0
assert (saved/'contact.jpg').is_file()
assert instance.captures[-1]['extractedData'] is not None
assert instance.state=='waiting for stationary ball'
print(json.dumps({'validationVersion':'0.1.0','demoVersion':demo.VERSION,'saved':str(saved),'ballFits':review['ball']['fits'],'passed':True}))
