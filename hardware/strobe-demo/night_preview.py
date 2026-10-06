"""Night illumination preview 0.1.0 from the saved linear bench images."""
import cv2
import numpy as np
from pathlib import Path
base=Path('/home/lm1/strobe-demo-v0.4.0/bench')
for j in (0,1):
    raw=cv2.imread(str(base/f'cam{j}-p100-raw.png'),-1)
    preview=np.clip((raw.astype(float)/64-16)*2,0,255).astype('uint8')
    cv2.imwrite(f'/home/lm1/night-ball-{j}.jpg',preview)
