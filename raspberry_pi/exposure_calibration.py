"""Pick a camera exposure and gain that suit the room the monitor is standing in.

Manual control stays exactly as it was; this only works out a sensible starting
point and applies it, so a player does not have to understand microseconds to get
a usable picture.

The search deliberately prefers the *shortest* exposure that still gives a bright
enough frame. A launch monitor needs the ball frozen far more than it needs a
pretty image, so extra light is bought with exposure only up to the point where
the frame is usable, and analogue gain is raised afterwards - grain costs less
accuracy than motion blur does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Sequence

try:  # pragma: no cover - numpy is present on the Pi and in CI
    import numpy as np
except ImportError:  # pragma: no cover - keeps the module importable for tests
    np = None  # type: ignore[assignment]

# What is judged is the brightest compact region of the frame (its 99.5th percentile), not the average: the ball is
# under 1 % of the pixels, so on a dark mat the frame mean is tiny (0.7 to 39 at the shutters a driver needs) even when
# the ball is bright, and a mean-based search drove the gain to 16, where the background noise is 32 grey levels and a
# ball at 100 us is 66 % saturated. Measured on the Pi at 58 us: gain 4 already gives ball 97 on a noise-free black
# background; gain 16 gives 211 on a background at 26 with noise 32. For a plain, evenly lit frame the level and the mean
# agree, so nothing changes there. (The names below keep "mean" for compatibility; read them as "level".)
BRIGHT_PERCENTILE = 99.5
# Mid-grey on an 8-bit sensor. Bright enough for a white ball to separate from a
# mat, dark enough that highlights keep their shape.
TARGET_MEAN = 105.0
# Below this the frame is too dark to track reliably.
MIN_ACCEPTABLE_MEAN = 70.0
# Above this the picture is washed out and the ball edge is lost.
MAX_ACCEPTABLE_MEAN = 165.0
# A few specular highlights are fine; a blown-out frame is not.
MAX_CLIPPED_FRACTION = 0.02
CLIPPING_LEVEL = 250
MAX_GAIN_STEPS = 5         # step the gain at most this many times, re-measuring after each
GAIN_OVERCORRECTION = 1.8  # later steps over-correct: brightness grows more slowly than gain
TARGET_TOLERANCE = 25.0    # stop raising gain once the level is this close to the target


@dataclass(frozen=True)
class FrameStats:
    """What one test frame looked like."""

    mean: float
    clipped_fraction: float
    level: float | None = None   # the brightest compact region; absent means judge by the mean

    @property
    def bright(self) -> float:
        return self.mean if self.level is None else self.level

    @property
    def usable(self) -> bool:
        return (
            MIN_ACCEPTABLE_MEAN <= self.bright <= MAX_ACCEPTABLE_MEAN
            and self.clipped_fraction <= MAX_CLIPPED_FRACTION
        )


@dataclass(frozen=True)
class Sample:
    """One exposure/gain pair and the frame it produced."""

    exposure_us: int
    gain: float
    stats: FrameStats


def measure_frame(frame: Any) -> FrameStats:
    """Reduce a frame to the two numbers the search cares about."""
    if np is None:  # pragma: no cover - numpy missing only in reduced environments
        raise RuntimeError("NumPy is required to measure exposure test frames.")
    pixels = np.asarray(frame)
    if pixels.size == 0:
        raise ValueError("Cannot measure an empty frame.")
    if pixels.ndim == 3:
        # Plain channel mean is enough here and avoids depending on OpenCV.
        pixels = pixels.mean(axis=2)
    pixels = pixels.astype("float32", copy=False)
    return FrameStats(
        mean=float(pixels.mean()),
        clipped_fraction=float((pixels >= CLIPPING_LEVEL).mean()),
        level=float(np.percentile(pixels[::2, ::2], BRIGHT_PERCENTILE)),
    )


def plan_exposures(min_us: int, max_us: int, step_us: int, steps: int = 7) -> list[int]:
    """Spread a handful of probe exposures across the range the sensor allows."""
    if min_us > max_us:
        raise ValueError("Minimum exposure cannot exceed the maximum.")
    steps = max(2, steps)
    step_us = max(1, step_us)
    span = max_us - min_us
    raw = [min_us + round(span * index / (steps - 1)) for index in range(steps)]
    snapped = sorted({min(max_us, max(min_us, round(value / step_us) * step_us)) for value in raw})
    # Snapping can push a value outside the range; keep the ends honest.
    if snapped[0] < min_us:
        snapped[0] = min_us
    if snapped[-1] > max_us:
        snapped[-1] = max_us
    return snapped


def _score(stats: FrameStats) -> float:
    """Lower is better: distance from the target, with clipping punished hard."""
    return abs(stats.bright - TARGET_MEAN) + stats.clipped_fraction * 1000.0


def choose_sample(samples: Sequence[Sample]) -> Sample:
    """Pick the best of the probes: shortest usable exposure, else closest to target."""
    if not samples:
        raise ValueError("At least one sample is required.")
    usable = [sample for sample in samples if sample.stats.usable]
    if usable:
        # Shortest exposure wins; ties go to the frame nearest the target brightness.
        return min(usable, key=lambda sample: (sample.exposure_us, _score(sample.stats)))
    return min(samples, key=lambda sample: _score(sample.stats))


def suggest_gain(stats: FrameStats, current_gain: float, min_gain: float, max_gain: float,
                 step: float, exponent: float = 1.0) -> float:
    """Scale gain so a too-dark frame reaches the target, without inventing light.

    `exponent` above 1 over-corrects a straight-line guess: the picture's brightness grows more slowly than the gain
    (the image processor's curve), so one linear step on a real sensor falls short."""
    if stats.bright <= 0:
        return max_gain
    wanted = current_gain * (TARGET_MEAN / stats.bright) ** exponent
    if step > 0:
        wanted = round(wanted / step) * step
    return round(min(max_gain, max(min_gain, wanted)), 2)


@dataclass(frozen=True)
class CalibrationResult:
    exposure_us: int
    gain: float
    mean: float
    clipped_fraction: float
    usable: bool
    samples: int
    note: str
    level: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "exposureUs": self.exposure_us,
            "gain": self.gain,
            "meanBrightness": round(self.mean, 1),
            "ballLevel": round(self.mean if self.level is None else self.level, 1),
            "clippedFraction": round(self.clipped_fraction, 4),
            "usable": self.usable,
            "samplesTaken": self.samples,
            "note": self.note,
        }


def calibrate_exposure(
    apply_settings: Callable[[int, float], None],
    grab_frame: Callable[[], Any],
    *,
    min_us: int,
    max_us: int,
    step_us: int,
    min_gain: float,
    max_gain: float,
    gain_step: float,
    settle_frames: int = 2,
    steps: int = 7,
) -> CalibrationResult:
    """Sweep exposures, then trim gain, and leave the camera on the winning pair.

    ``apply_settings`` sets the camera; ``grab_frame`` returns the next frame from
    whoever owns the stream. Both are injected so the search can be tested without
    a camera and so it never has to fight the detection loop for frames.
    """
    base_gain = round(max(min_gain, min(max_gain, 1.0)), 2)
    samples: list[Sample] = []

    for exposure_us in plan_exposures(min_us, max_us, step_us, steps):
        apply_settings(exposure_us, base_gain)
        frame = _settled_frame(grab_frame, settle_frames)
        samples.append(Sample(exposure_us, base_gain, measure_frame(frame)))

    best = choose_sample(samples)
    exposure_us, gain, stats = best.exposure_us, best.gain, best.stats
    note = "Matched the light in the room."

    if not stats.usable and stats.bright < MIN_ACCEPTABLE_MEAN:
        # Still dark at every exposure we are allowed to use: buy the rest with gain. The first step assumes brightness
        # follows gain in a straight line; a real sensor's curve makes that fall short, so later steps over-correct.
        # Use the longest shutter we are allowed: every unlit frame reads about the same at gain 1, so "the best sample" is
        # arbitrary, and a shorter shutter would only need more gain, which is where the noise comes from.
        longest = max(samples, key=lambda sample: sample.exposure_us)
        exposure_us, gain, stats = longest.exposure_us, longest.gain, longest.stats
        # Step the gain towards the target level. The first step assumes brightness follows gain in a straight line; a
        # real sensor's curve makes that fall short (or, from a black frame, overshoot), so later steps over-correct and
        # can come back down. "Usable" is not enough: a ball just over the minimum is fragile.
        exponent = 1.0
        raised = False
        for _ in range(MAX_GAIN_STEPS):
            if stats.usable and abs(stats.bright - TARGET_MEAN) <= TARGET_TOLERANCE:
                break
            stepped = suggest_gain(stats, gain, min_gain, max_gain, gain_step, exponent)
            if stepped == gain:
                break
            raised = raised or stepped > gain
            gain = stepped
            apply_settings(exposure_us, gain)
            frame = _settled_frame(grab_frame, settle_frames)
            stats = measure_frame(frame)
            if stats.bright <= 0 and gain > base_gain:
                # A black frame right after raising the gain is a stale frame, not a measurement (seen once on the Pi,
                # where it was taken as final and left the gain at the maximum): look once more.
                frame = _settled_frame(grab_frame, settle_frames)
                stats = measure_frame(frame)
            samples.append(Sample(exposure_us, gain, stats))
            exponent = GAIN_OVERCORRECTION
        if raised:
            note = "The room is dim, so brightness boost was raised as well."
        if not stats.usable:
            note = "Still dark at the brightest safe setting - add light to the hitting area."
    elif not stats.usable and stats.bright > MAX_ACCEPTABLE_MEAN:
        note = "Very bright light - the shortest shutter still over-exposes the frame."
    else:
        apply_settings(exposure_us, gain)

    return CalibrationResult(
        exposure_us=exposure_us,
        gain=gain,
        mean=stats.mean,
        clipped_fraction=stats.clipped_fraction,
        usable=stats.usable,
        samples=len(samples),
        note=note,
        level=stats.level,
    )


def _settled_frame(grab_frame: Callable[[], Any], settle_frames: int) -> Any:
    """Throw away the frames still exposed with the previous settings."""
    frame = None
    for _ in range(max(1, settle_frames + 1)):
        frame = grab_frame()
        if frame is None:
            raise RuntimeError("The camera stopped delivering frames during calibration.")
    return frame


def is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
