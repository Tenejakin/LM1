"""Strobe Lab saved-data replay 0.1.0; never rewrites capture metadata."""
import argparse
import json
from pathlib import Path
import cv2
from demo import VERSION, frame_track, view


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('root',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    report=[]
    for directory in sorted(args.root.glob('capture-*')):
        summary=json.loads((directory/'summary.json').read_text())
        item={'capture':directory.name,'sourceVersion':summary['version'],'analysisVersion':VERSION,'views':[]}
        for index,camera in enumerate(summary['cameras']):
            rows=[{'raw':cv2.imread(str(directory/f'cam{index}'/f'raw-{m["frame"]:03}.png'),-1),'meta':m} for m in camera['metadata']]
            result=frame_track(rows,summary['ballReferences'][index])
            item['views'].append({'camera':index,'actualExposureUs':rows[0]['meta']['ExposureTime'],
                                 'before':camera['analysis']['best'],'after':result['best'],'reason':result['reason'],
                                 'candidateFrames':sum(c>0 for c in result.get('candidateCounts',[])),
                                 'rejections':result.get('rejections',[])})
            fit=result['best']
            if fit:
                for frame,point in zip(fit['frames'],fit['points']):
                    image=view(rows[frame]['raw'])
                    cv2.circle(image,(round(point[0]),round(point[1])),23,(0,255,0),2)
                    cv2.imwrite(str(args.out/f'{directory.name}-c{index}-f{frame}.jpg'),image)
        report.append(item)
        print(json.dumps(item),flush=True)
    (args.out/'report.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':main()
