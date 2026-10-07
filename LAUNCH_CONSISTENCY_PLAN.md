# LM1 — Launch Data Consistency Plan

Why shot-to-shot numbers wobble, what the OV9281 datasheet says we're doing
right and wrong, and a no-new-hardware plan to make results repeatable.

Status: analysis + plan. No hardware purchases required.

---

## 1. TL;DR

The monitor is fighting two physics problems at once, and compounding both by
running the sensor **above its datasheet frame-rate envelope**.

1. **A golf ball at 30–70 m/s needs a shutter ≤ ~57 µs** (driver) to keep blur
   under 4 mm. A 3 µm pixel at 30–100 µs collects very few photons, so the image
   is shot-noise-limited. Noise makes the ball edge wander, and the edge is what
   every sub-pixel centroid / circle fit / velocity fit is built on.
2. **Velocity is a derivative.** You get 3–5 samples for a driver, each noisy.
   Few noisy samples → large variance in speed and launch, exactly the
   "inconsistent" behaviour you're seeing.
3. We make both worse by running **640×400 @ 242 fps**. The datasheet specifies
   **VGA @ 180 fps** and **1280×800 @ 120 fps**. 242 fps is ~35 % above the VGA
   ceiling — there is zero readout headroom, so any host hiccup drops frames or
   shifts timing, and the software stagger/sync has no margin to correct with.

The good news: the sensor choice is right (global shutter, mono, high NIR QE),
the timestamping is right, and a lot of the hardening already exists. Most of the
fixes are tuning, not construction.

---

## 2. What the OV9281 datasheet says

Sources: [OmniVision OV9281 product page](https://www.ovt.com/products/ov9281/) and
[OV9281 product brief](http://www.ovt.com/wp-content/uploads/2024/05/OV9281-PB-v1.4-WEB.pdf).

| Datasheet fact | What it means for us |
| --- | --- |
| 1/4", 1280×800, **3.0 µm** pixel, OmniPixel®3-GS **global shutter** | Global shutter = no rolling-shutter skew on a fast ball (correct choice). Small pixel = small full-well = low SNR at short exposure (our #1 limit). |
| **Monochrome**, "best-in-class NIR QE" | No Bayer filter → full spatial resolution + good response to the IR ring. Right sensor for IR-lit, high-speed machine vision. |
| **1280×800 @ 120 fps; VGA (640×480) @ 180 fps** | **We run 640×400 @ 242 fps — above the VGA ceiling.** This is the single most important finding. |
| 2-lane MIPI, 8/10-bit RAW | 10-bit is there; the 8-bit ISP path crushes the low end (see §3.2). |
| **Built-in strobe control + LED PWM** | The sensor can drive/phase a light to exposure. We instead let the ESP32 ring free-run and drift. Untapped. |
| 2×2 binning, 2:1 / 4:1 subsampling, ROI / context switching | We use subsampling to reach 640×400; binning is a cheap SNR lever we don't use. |

### 2.1 The frame-rate envelope (why 242 fps is the problem)

- In-spec: **640×480 @ 180 fps** and **1280×800 @ 120 fps**.
- We run **640×400 @ 242 fps** — *faster than the sensor is specified for*.
- `DUAL_CAMERA_SETUP.md` already records the cliff: 243/244/245 fps "stalled
  during startup"; 280/300 fps (8-bit) failed the 250 µs timing gate; **242 fps
  was the fastest that "passed"**.

"Passed startup" is not "operates cleanly." At the edge, the readout has no spare
time. Raspberry Pi's own software-sync docs (linked in `DUAL_CAMERA_SETUP.md`)
say software sync needs **spare frame-rate capacity** to absorb timing
corrections — at 242 fps there is none. The result: occasional dropped frames,
irregular inter-frame gaps, and stagger phase drift, all of which silently make a
shot's velocity fit worse.

---

## 3. Root causes of inconsistency (ranked)

### 3.1 SNR at short exposure (fundamental, dominant)

`MAX_MOTION_BLUR_M = 0.004 m` and the blur gate force exposure ≤ ~57 µs at driver
speed. A 3 µm mono pixel at 30–100 µs under the IR ring collects few photons, so:

- Photon shot noise dominates → the ball's edge (used by `ball_edge_fit`,
  `_circle_candidates`, template matching) moves frame to frame.
- `EDGE_MIN_CONTRAST = 12` and `EDGE_MAX_RMS_PX = 0.8` are fought by noise; the
  sub-pixel peak interpolation quantises and jitters.
- Gain up to 16× is available and the auto-sweep will use it; the code itself
  measured **gain 16 → background noise σ≈32 grey levels** vs gain 4 → clean.
  High gain directly injects variance into the tracker.

**Effect:** even with perfect timing, per-sample position error is large, so the
velocity (slope) estimate varies shot to shot.

### 3.2 The 8-bit ISP crushes the signal we need

`camera_source.py` documents it precisely: the sensor is 10-bit, but the image
processor subtracts 64 counts of real signal and applies a ~0.45 gamma, so the
darkest ~3 % of the range becomes exactly 0. At 20–100 µs exposure, "99.8–100 %
of the 8-bit picture was 0 while the raw data held a clear signal." The primary
measurement path still runs on that crushed 8-bit picture; raw 10-bit is captured
but only used for the strobe-copy path.

**Effect:** the faint-but-real ball signal at short exposure is quantised away,
turning a weak gradient into a hard, noisy edge.

### 3.3 Few samples for the fit

`TRAJECTORY_MIN_FRAMES = 3`, "measured" needs 6. At 242 fps a driver moves ~29 cm
per frame. From `DUAL_CAMERA_SETUP.md`'s own table, at the 40–56 px ball sweet
spot a driver yields only **1–3 frames**; to get 4–5 you must pull back to ~1 m
where the ball shrinks to 19–25 px (below the reliable 40 px floor). There is a
hard geometric conflict between *trackable ball size* and *visible flight path*.

**Effect:** for the fastest clubs you are fitting a line through 3 noisy points —
variance is inherent, not a bug.

### 3.4 Illumination phase drift (indoor / strobe)

The detector normalises brightness per frame (`gain = bg.mean / frame.mean`),
which masks whole-frame flicker but does **not** restore a consistent *ball* SNR.
In strobe mode the ESP32 ring free-runs; the changelog notes bursts "straddle the
gap between exposures" and that "optical exposure is not claimed to be 20 µs."
Different frames see different flash phase → different brightness → different
centroid. The datasheet's **built-in strobe/LED PWM** would fix this but is
unused.

**Effect:** frame-to-frame brightness changes are indistinguishable from motion,
adding fit noise.

### 3.5 Calibration / setup variance

Stereo depth rests on the ground AprilTag + lens focus + stand rigidity. 3 µm
pixels with a short-focal lens mean a fraction-of-a-pixel calibration error is
millimetres at 1 m. `readiness.py` catches drift but is advisory only. Any stand
bump, focus shift, or tag move silently degrades every shot.

---

## 4. What is already good (keep these)

1. **Global shutter** is exactly the right sensor for a 70 m/s ball — no skew.
2. **Monochrome + high NIR QE** — no Bayer losses, IR ring is the right light.
3. **Real `SensorTimestamp`** for velocity (not host arrival time) — correct and
   essential; `DUAL_CAMERA_SETUP.md` verified offsets ≤ 54 µs.
4. **Software stagger** to double effective sample rate — clever; just needs the
   in-spec headroom to be reliable.
5. **Auto-exposure that judges the ball (99.5th pct) and respects per-club blur
   limits** — thoughtful and correct in principle.
6. **Raw 10-bit capture** to recover the signal the 8-bit path destroys — the
   right idea; it just isn't wired into the primary measurement yet.
7. **Readiness checks + plain-language rejection reasons** — good proactive
   diagnostics; the failure messages already tell you *why* a shot died.
8. **Debounced departure + template re-anchoring + false-removal rejection** —
   robust against hand-lift / club-occlusion false triggers.

---

## 5. The plan (no new hardware)

Ordered by expected impact on *consistency*.

### Phase 0 — Measure the variance (do first, ~1 session)

You cannot fix what you don't quantify. Take **20 identical shots** (same club,
same mat, same light, same ball placement) and, for each, record from the saved
`capture.json` / `analysis.json`:

- measured/estimated status and which gate failed
- ball diameter px, frame count used, fit residual (px/mm)
- `measuredFps`, max inter-frame gap, stagger phase/state, sync offset
- exposure µs and gain actually applied

Goal: a per-shot table that separates *detection failures* from *measurement
variance*. The existing `scripts/audit-capture.py` and
`scripts/review-capture-reliability.py` already read these captures — extend or
script the aggregation rather than writing new plumbing.

### Phase 1 — Bring the sensor back inside its envelope (biggest single lever)

Drop the frame rate into spec and lean on the stagger for temporal density.

1. Run **640×400 @ ~180–200 fps** (at/below the VGA ceiling), both cameras
   staggered. Staggered, that is still ~360–400 effective samples/sec.
2. Alternatively evaluate **1280×800 @ 120 fps** full-res, staggered → the ball
   is ~2× bigger in pixels (50 px vs 25 px at 1 m), spatial resolution and travel
   room double, and 120 fps is rock-solid in-spec. Trade-off: fewer temporal
   samples per shot, so verify the driver still clears `TRAJECTORY_MIN_FRAMES`.
3. Measure, for each candidate rate: dropped-frame rate, max inter-frame gap,
   stagger phase drift over 60 s, and the 20-shot speed variance. **Pick the rate
   by variance, not by max fps.** (The current 242 fps was chosen because it was
   the fastest that *passed*, not the most *repeatable*.)

This is reversible via `PINPOINT_CAMERA_FPS` in `/etc/default/pinpoint` — no code
change to try.

### Phase 2 — Stabilise the light (remove flash-phase noise)

1. **Measure in "Flat" (ring steady), not "Strobe".** Strobe captures are already
   saved-for-review-only and carry no measurements; steady light is the only mode
   that gives consistent frame-to-frame ball brightness. Auto-set already prefers
   Flat unless daylight is enough.
2. Prefer the **lowest gain that still exposes the ball** (target ≤ 4×, never
   16×). Buy brightness with the ring position/intensity and camera distance, not
   gain.
3. (Optional, existing hardware only) The OV9281 has **built-in strobe control /
   LED PWM**. Investigate driving the existing ESP32 ring from a signal derived
   from the sensor's exposure (via libcamera's flash/strobe controls or a GPIO on
   the existing camera module) so every flash lands deterministically inside every
   exposure. This is a firmware/software change; treat it as a stretch goal after
   Phases 1–2, and only if strobe is ever needed for measurement.

### Phase 3 — Use the raw 10-bit signal for measurement (SNR)

1. Run the **ball edge / circle fit and centroid on the linear raw 10-bit data**
   (`raw_frames.py` already preserves it; `RAW_SCALE` / `raw_black_level` are
   already in place), instead of the gamma-crushed 8-bit picture. At short
   exposures this is the difference between "real signal" and "exactly 0".
2. Keep the 8-bit path only for display/preview and the presence detector.

### Phase 4 — More usable samples per shot (geometry, not hardware)

1. Enforce the documented sweet spot operationally: ball **40–56 px**, near the
   **upstream edge**, camera ~1 m back for fast clubs. `readiness.py` already
   computes this — make it a *hard* gate for "measured" grade, not advisory.
2. Reject (downgrade) any shot with **< 5–6 frames** or a **frame gap** rather
   than letting a 3-point fit carry "measured" status. The code already has the
   `FREE_START_MIN_FRAMES = 6` / measured-needs-6 logic; extend the same bar to
   the mono path.
3. Verify the frame-gap warning (`intervals.max() > 2.5 / fps`) actually
   downgrades the shot; it currently only appends a warning string.

### Phase 5 — Calibration & validation discipline

1. Re-run lens + stereo + AprilTag calibration at the **exact** resolution and
   fps you settle on in Phase 1 (calibration is mode-specific).
2. Build a **no-hardware reference** for repeatable validation: roll balls down a
   fixed ramp/incline (known height → repeatable speed), or putts of known
   distance, and use those to measure shot-to-shot variance. Compare against the
   same reference for every tuning change.
3. Use `readiness` "Camera alignment" (ray-gap / rest-height) before each session;
   treat a `fail` there as blocking, not advisory.

### Phase 6 — Surface consistency to the user

1. Add a per-shot / session summary showing **why** shots varied: blur, ball size,
   frame count, frame gaps, SNR, gate failures. The data already exists in
   `diagnostics`; it just isn't surfaced as a trend.
2. Keep the rejection hints — they are already good — but tie them to the new
   variance table so a user can see "driver shots fail 60 % on blur/coverage"
   at a glance.

---

## 6. What NOT to do

- **Do not raise fps further.** 242 fps is already above spec; more fps buys
  nothing but dropped frames and drift.
- **Do not chase gain to 16×.** Noise is the enemy of consistency, and gain is
  noise.
- **Do not trust strobe mode for measurement.** It is review-only by design.
- **Do not keep the ball centred.** Half the frame is wasted behind the ball;
  upstream-edge placement is the single cheapest "more frames" win.
- **Do not tune constants to make numbers look right.** Reject unsupported
  metrics (the code already does this; keep it).

---

## 7. Expected outcome

| Change | Expected effect on consistency |
| --- | --- |
| In-spec frame rate (Phase 1) | Fewer drops, stable timing/stagger → cleaner fits |
| Steady light + low gain (Phase 2) | Stable ball SNR → stable centroid |
| Raw 10-bit measurement (Phase 3) | Real signal instead of quantised 0 → better edges |
| More frames + hard gates (Phase 4) | Velocity fit from 5–6 points instead of 3 |
| Variance table + reference (Phase 0/5) | Visible, measurable progress instead of guesswork |

**Reality check:** this is still a 1 MP, 3 µm-pixel camera measuring a 70 m/s
ball at 1 m. Absolute accuracy will remain limited and should be validated
against a real reference monitor before trusting any number. This plan targets
**repeatability** (same input → same output), which is the concrete symptom you
asked about and is fully addressable with the hardware you already have.
