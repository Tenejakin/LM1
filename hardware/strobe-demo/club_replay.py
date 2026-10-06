"""Club strobe replay 0.2.0; keep capture summaries and raw evidence unchanged."""
import json,sys
from pathlib import Path
import cv2
from strobe_club import analyze_club,analyze_single_flash
root=Path(sys.argv[1]);report=[]
for directory in sorted(root.glob('capture-*')):
    if not (directory/'summary.json').exists():continue
    summary=json.loads((directory/'summary.json').read_text())
    cameras=[]
    for j,camera in enumerate(summary['cameras']):
        rows=[{'raw':cv2.imread(str(directory/f'cam{j}'/f'raw-{m["frame"]:03}.png'),-1),'meta':m} for m in camera['metadata']]
        analyzer=analyze_single_flash if j==0 and summary['pattern']['mode']=='single flash club visibility trial' else analyze_club
        cameras.append(analyzer(rows,summary['ballReferences'][j],summary['triggerSensorTimestamp']))
    report.append({'capture':directory.name,'cameras':cameras})
if '--brief' in sys.argv:
    for item in report:
        print(json.dumps({'capture':item['capture'],'views':[{'speed':c['clubSpeedMps'],'reason':c['reason'],'headFrames':[s['frame'] for s in c.get('headCandidates',[])]} for c in item['cameras']]}))
else:print(json.dumps(report,indent=2))
