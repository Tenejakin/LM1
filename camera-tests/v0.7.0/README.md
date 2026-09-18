# Stationary ball stability v0.7.0

The live Pi logs showed that the ball was detected repeatedly, but the detector alternated between detected and removed while the ball remained visible. The 200 fps image also showed strong horizontal bands from the indoor lighting.

Service 0.7.0 samples CSI detection every fourth frame (about 50 samples per second at 200 fps) instead of every twentieth frame. It also keeps the last confirmed ball bounds during a brief missed-contour debounce period so the app does not drop the box immediately. BLE preview cadence remains three seconds.

App 2.5.0/build 15, Pi service 0.7.0, BLE protocol 2.5.0.
