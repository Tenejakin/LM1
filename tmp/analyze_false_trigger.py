import sys

import cv2

sys.path.insert(0, "/tmp/lm1-0.13.2-s2PFks")
from ball_detector import ball_template_similarity


capture = "/var/lib/pinpoint/rolling-captures/capture-1789046721770830448"
first = cv2.imread(f"{capture}/frame-0000.jpg")
last = cv2.imread(f"{capture}/frame-0219.jpg")
print(ball_template_similarity(first, last, (270, 233, 66, 70)))
