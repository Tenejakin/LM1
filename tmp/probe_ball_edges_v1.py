"""Offline edge-fit experiment v1.0.0; does not change device measurements."""
import sys, json, math
from pathlib import Path
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'raspberry_pi'))
from launch_measurements import RADIUS, find_ground_tag_pose


def fit_edge(frame, expected, radius, matrix, distortion):
    expected = np.asarray(expected, float)
    h,w=frame.shape
    x0,y0=np.maximum(0,np.floor(expected-radius*1.65)).astype(int)
    x1,y1=np.minimum([w,h],np.ceil(expected+radius*1.65)).astype(int)
    gray=cv2.GaussianBlur(frame[y0:y1,x0:x1],(3,3),.7)
    edges=cv2.Canny(gray,20,50)
    yy,xx=np.nonzero(edges)
    pixels=np.column_stack([xx+x0,yy+y0]).astype(float)
    if len(pixels)<25: return None
    gradx=cv2.Sobel(gray,cv2.CV_64F,1,0,ksize=3)[yy,xx]
    grady=cv2.Sobel(gray,cv2.CV_64F,0,1,ksize=3)[yy,xx]
    grad=np.column_stack([gradx,grady]); strength=np.linalg.norm(grad,axis=1); grad/=np.maximum(1,strength)[:,None]
    dist=np.linalg.norm(pixels-expected,axis=1)
    mask=(dist>radius*.45)&(dist<radius*1.5)
    pixels=pixels[mask]; grad=grad[mask]; strength=strength[mask]
    if len(pixels)<25: return None
    rays=cv2.undistortPoints(pixels.reshape(-1,1,2),matrix,distortion).reshape(-1,2)
    rays=np.column_stack([rays,np.ones(len(rays))]); rays/=np.linalg.norm(rays,axis=1)[:,None]
    f=(matrix[0,0]+matrix[1,1])/2
    best=None; rng=np.random.default_rng(42)
    triples=np.array([rng.choice(len(rays),3,replace=False) for _ in range(500)])
    normals=np.cross(rays[triples[:,1]]-rays[triples[:,0]],rays[triples[:,2]]-rays[triples[:,0]])
    normals/=np.maximum(np.linalg.norm(normals,axis=1),1e-15)[:,None]
    normals[normals[:,2]<0]*=-1
    cosines=np.sum(normals*rays[triples[:,0]],axis=1)
    angular=np.arccos(np.clip(cosines,-1,1))
    centers=cv2.projectPoints(normals,np.zeros(3),np.zeros(3),matrix,distortion)[0].reshape(-1,2)
    valid=(angular*f>radius*.6)&(angular*f<radius*1.4)&(np.linalg.norm(centers-expected,axis=1)<radius*.4)
    for axis,alpha,center in zip(normals[valid],angular[valid],centers[valid]):
        residual=np.abs(np.arccos(np.clip(rays@axis,-1,1))-alpha)*f
        delta=pixels-center; lengths=np.linalg.norm(delta,axis=1)
        outward=np.sum(grad*delta,axis=1)/np.maximum(lengths,1)
        inliers=(residual<1.0)&(outward<-.35)
        if inliers.sum()<20: continue
        bins=np.unique(((np.arctan2(delta[inliers,1],delta[inliers,0])+np.pi)*24/(2*np.pi)).astype(int)%24)
        if len(bins)<13: continue
        score=float(np.sum(np.minimum(strength[inliers],300)))/100+len(bins)*2
        if best is None or score>best[0]: best=(score,inliers)
    if best is None: return None
    inliers=best[1]
    for _ in range(3):
        pts=rays[inliers]
        weights=np.minimum(strength[inliers],300); mean=np.average(pts,axis=0,weights=weights)
        _,_,vh=np.linalg.svd((pts-mean)*np.sqrt(weights)[:,None],full_matrices=False)
        axis=vh[-1]
        if axis[2]<0: axis=-axis
        cosine=np.mean(pts@axis); alpha=math.acos(np.clip(cosine,-1,1))
        center=cv2.projectPoints(axis,np.zeros(3),np.zeros(3),matrix,distortion)[0].reshape(2)
        delta=pixels-center
        residual=np.abs(np.arccos(np.clip(rays@axis,-1,1))-alpha)*f
        outward=np.sum(grad*delta,axis=1)/np.maximum(np.linalg.norm(delta,axis=1),1)
        inliers=(residual<1)&(outward<-.35)
    if alpha<.002 or inliers.sum()<20: return None
    angles=(np.arctan2(delta[inliers,1],delta[inliers,0])+np.pi)*24/(2*np.pi)
    bins=np.unique(angles.astype(int)%24)
    if len(bins)<13: return None
    return {'camera':axis*RADIUS/math.sin(alpha),'center':center,'radius':alpha*f,
            'edge':pixels[inliers],'coverage':len(bins),'error':float(np.sqrt(np.mean(residual[inliers]**2)))}


if __name__=='__main__':
    root=Path(__file__).resolve().parent
    config=json.loads((root/'intrinsics-2026-09-15.json').read_text()); k=np.array(config['cameraMatrix']); d=np.array(config['distCoeffs'])
    selected=sys.argv[1:] or ['1789478965522399703','1789478160194449817','1789476032857983629','1789475651513192793']
    report=[]; tiles=[]
    for suffix in selected:
        p=root/f'capture-{suffix}'; m=json.loads((p/'capture.json').read_text()); a=json.loads((p/'analysis.json').read_text())
        frames=[(t/1000,cv2.imread(str(p/f'frame-{i:04d}.jpg'),0)) for i,t in enumerate(m['frameTimesMs'])]
        pose=find_ground_tag_pose(frames,m['impactFrameIndex'],0,.1,k,d)
        r,t=pose['rotation'],pose['translation']; sr=min(m['ballBounds'][2:])/2
        print(p.name,'camera height',(-r.T@t)[2])
        results=[]
        hints=a['track']; hints=[h for h in hints if h['frameIndex']>=m['impactFrameIndex']-4]
        for hint in hints:
            i=hint['frameIndex']; result=fit_edge(frames[i][1],[hint['x'],hint['y']],sr,k,d)
            if result is None:
                print(i,'no fit'); results.append({'frameIndex':i,'status':'no-fit'}); continue
            world=r.T@(result['camera']-t)
            print(i,'radius',round(result['radius'],1),'center',result['center'].round(1),'z',round(world[2]*1000,1),'bins',result['coverage'])
            results.append({'frameIndex':i,'positionM':world.tolist(),'centerPx':result['center'].tolist(),'radiusPx':result['radius'],'coverage':result['coverage'],'edgeErrorPx':result['error']})
            if i in [m['impactFrameIndex']-3,m['impactFrameIndex'],m['impactFrameIndex']+3,m['impactFrameIndex']+6]:
                im=cv2.cvtColor(frames[i][1],cv2.COLOR_GRAY2BGR)
                for point in result['edge']: cv2.circle(im,tuple(np.round(point).astype(int)),1,(0,255,0),-1)
                cv2.putText(im,f'{suffix[-5:]} frame {i}: height {world[2]*1000:.0f}mm',(12,22),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,255,255),1)
                tiles.append(im)
        report.append({'captureId':p.name,'cameraHeightM':float((-r.T@t)[2]),'points':results})
    (root/'edge-fit-experiment-v1.0.0.json').write_text(json.dumps(report,indent=2))
    if tiles:
        if len(tiles)%2: tiles.append(np.zeros_like(tiles[-1]))
        cv2.imwrite(str(root/'edge-fit-experiment-v1.0.0.jpg'),np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,len(tiles),2)]))
