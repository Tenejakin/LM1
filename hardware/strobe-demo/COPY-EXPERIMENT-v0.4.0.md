# Three-copy experiment 0.4.0

Run `demo.py --copies` using the existing Pi environment. Current deployed folder is `/home/lm1/strobe-demo-v0.4.0`, browser port 3113. Stop the existing camera owner first. The temporary service uses automatic restart; stop it explicitly before returning to normal operation.

The camera runs at 50 fps with requested exposure 19500 us and gain 1. The ring emits 100 us pulses at offsets 0, 5000, 13000 us in each 20000 us cycle. Cyclic gaps are 5000, 8000, 7000 us, at 1.5% electrical duty. No peak-current increase or hardware modification is made.

Distance is speed times elapsed time. At 10 m/s the consecutive spacings are 50, 80, 70 mm, while a pulse contributes 1 mm of movement. At 14 m/s these become 70, 112, 98 mm and 1.4 mm pulse blur. For a 42.67 mm ball, the shortest gap separates complete copies above about 8.53 m/s. Slower shots may overlap. Perspective and ambient contribution remain unresolved.

Each image is analyzed independently for at least three distinct ball copies. All cyclic flash phases are fitted; ambiguous phase or poor fit prevents a result. Camera exposure boundaries can clip or omit pulses, since there is no hardware synchronization. Raw images, commanded pattern, sensor metadata and failed attempts are preserved.

The off/on bench used the initial 5/6.5/8.5 ms gaps and 100/250/500 us pulse widths, with actual 19497 us exposure. Minimum gain did not make the room dark: the lower placement ROI had 4.45% clipping, upper 0.67%. ROI statistics are not isolated ball photometry. Saturation prevents concluding that a weak measured difference means the ring itself is weak. The raw bench is in `output/strobe-demo-v0.4.0/bench/`; moving shots are required to inspect whether separate flash copies survive ambient trails.
