"""Night shot replay 0.1.0: evaluate saved captures without changing evidence."""
import sys,json
from pathlib import Path
import cv2
from demo import VERSION,analyze_frames
root=Path(sys.argv[1]);summary=json.loads((root/'summary.json').read_text())
report={'reviewVersion':VERSION,'capture':root.name,'cameras':[]}
for j,camera in enumerate(summary['cameras']):
    rows=[{'raw':cv2.imread(str(root/f'cam{j}'/f'raw-{m["frame"]:03}.png'),-1),'meta':m} for m in camera['metadata']]
    result=analyze_frames(rows,summary['ballReferences'][j],summary['pattern'])
    report['cameras'].append(result)
print(json.dumps(report,indent=2))
