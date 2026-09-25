"""Still-air flight, roll and impact estimates. Model output is never a measured landing.

Version 2.0.0. Aerodynamics are fitted to the Trackman PGA Tour averages (driver to
pitching wedge: ball speed, launch and spin in; carry, height and landing angle
out). Carry lands within 1-7% of those averages, height within a few yards and the
landing angle within 1-7 degrees for irons; version 1 carried a driver 190 yd
instead of 275. Anything outside that envelope (chips, skulls) is extrapolation.

The club spin profiles are provisional averages, not calibrated measurements.
"""
import math

GRAVITY = 9.80665
BALL_MASS_KG = 0.04593
BALL_RADIUS_M = 0.021335
AIR_DENSITY = 1.225
STEP_S = 0.002
MAX_FLIGHT_S = 15.0
# Drag falls with speed (the dimpled ball's drag crisis) and rises with spin; lift
# grows sub-linearly with the spin parameter S = spin * radius / speed.
DRAG_BASE = 0.237
DRAG_PER_SPIN_PARAMETER = 0.271
DRAG_PER_SPEED = 0.036  # per 50 m/s above 50 m/s
LIFT_SCALE = 0.495
LIFT_EXPONENT = 0.417
SPIN_DECAY_PER_S = 0.06
# Spin from impact: spin = K * club speed * sin(launch - attack), K fitted per club
# to the same tour averages (driver 252 ... irons 453-536). Wedges use the pitching
# wedge value; short-game use is an extrapolation.
SPIN_LOFT_K = {
    "driver": 252, "3-wood": 365, "5-wood": 430, "3-hybrid": 419, "4-hybrid": 436,
    "4-iron": 453, "5-iron": 469, "6-iron": 485, "7-iron": 501, "8-iron": 535,
    "9-iron": 536, "pitching-wedge": 514, "gap-wedge": 514, "sand-wedge": 514, "lob-wedge": 514,
}
# Launch sits between the face normal and the club path: launch - attack =
# SL - atan(c tan SL), with c = (2/7)(1 + m/M)/(1 + e) for a ball rolling off the
# face (m/M ~ 0.18, e ~ 0.78). It reproduces a tour 7-iron's ~21 deg dynamic loft.
FACE_TANGENT_RATIO = 0.19
# Beyond this the impact model has no stable solution: the attack angle is off.
MAX_LAUNCH_ABOVE_ATTACK_DEG = 40.0
# Landing: the ball slides to rolling (5v - 2 r w)/7, the turf absorbs a share of
# the normal speed, then it rolls out against surface friction. Calibrated so a
# 12 m/s sand-wedge chip rolls about its carry on a green and a tour drive rolls
# 20 yd on fairway. Short, steep landings are assumed to be on a green.
TURF_ABSORPTION = 0.162
GREEN_ROLL_FRICTION = 0.065
FAIRWAY_ROLL_FRICTION = 0.304
GREEN_MAX_CARRY_M = 40.0
GREEN_MIN_DESCENT_DEG = 20.0

CLUB_SPIN_RPM = {
    "driver": 2600, "3-wood": 3500, "5-wood": 4200,
    "3-hybrid": 4300, "4-hybrid": 4700, "4-iron": 4800,
    "5-iron": 5300, "6-iron": 5900, "7-iron": 6500,
    "8-iron": 7200, "9-iron": 7900, "pitching-wedge": 8600,
    "gap-wedge": 9200, "sand-wedge": 9800, "lob-wedge": 10200,
}
CLUB_BALL_SPEED_MPS = {
    "driver": 61.32, "3-wood": 58.32, "5-wood": 56.09,
    "3-hybrid": 54.6, "4-hybrid": 52.44, "4-iron": 51.375,
    "5-iron": 49.68, "6-iron": 47.88, "7-iron": 45.85,
    "8-iron": 43.86, "9-iron": 41.91, "pitching-wedge": 39.06,
    "gap-wedge": 34.8, "sand-wedge": 31.32, "lob-wedge": 27.5,
}


def assumed_spin_rpm(club_id, ball_speed_mps, attack_angle_deg=None):
    """Scale club-average spin for a partial swing; steep descent raises it modestly."""
    club = club_id if club_id in CLUB_SPIN_RPM else "driver"
    speed_ratio = max(0.15, min(1.25, ball_speed_mps / CLUB_BALL_SPEED_MPS[club]))
    attack_factor = (max(0.7, min(1.3, 1 - 0.018 * attack_angle_deg))
                     if attack_angle_deg is not None and math.isfinite(attack_angle_deg) else 1)
    return round(CLUB_SPIN_RPM[club] * speed_ratio ** 0.7 * attack_factor)


def simulate_flight(ball_speed_mps, launch_angle_deg, direction_deg, spin_rpm):
    """Carry along the target line, offline, apex, landing angle and landing state."""
    values = (ball_speed_mps, launch_angle_deg, direction_deg, spin_rpm)
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in values) or ball_speed_mps <= 0:
        return None
    angle = math.radians(max(-10.0, min(80.0, launch_angle_deg)))
    direction = math.radians(max(-90.0, min(90.0, direction_deg)))
    vx, vz = ball_speed_mps * math.cos(angle), ball_speed_mps * math.sin(angle)
    x = z = t = apex = 0.0
    constant = 0.5 * AIR_DENSITY * math.pi * BALL_RADIUS_M ** 2 / BALL_MASS_KG
    omega0 = max(0.0, spin_rpm) * 2 * math.pi / 60
    while t < MAX_FLIGHT_S:
        speed = math.hypot(vx, vz)
        if speed < 0.01:
            break
        spin_parameter = omega0 * math.exp(-SPIN_DECAY_PER_S * t) * BALL_RADIUS_M / speed
        drag_coefficient = max(0.1, DRAG_BASE + DRAG_PER_SPIN_PARAMETER * spin_parameter
                               - DRAG_PER_SPEED * (speed / 50 - 1))
        lift_coefficient = LIFT_SCALE * spin_parameter ** LIFT_EXPONENT
        ax = -constant * speed * (drag_coefficient * vx + lift_coefficient * vz)
        az = -GRAVITY - constant * speed * (drag_coefficient * vz - lift_coefficient * vx)
        next_x = x + vx * STEP_S + 0.5 * ax * STEP_S ** 2
        next_z = z + vz * STEP_S + 0.5 * az * STEP_S ** 2
        if next_z <= 0 < t:
            fraction = z / (z - next_z) if z > next_z else 1.0
            x += (next_x - x) * fraction
            vx += ax * STEP_S * fraction
            vz += az * STEP_S * fraction
            t += STEP_S * fraction
            break
        x, z = next_x, next_z
        vx += ax * STEP_S
        vz += az * STEP_S
        t += STEP_S
        apex = max(apex, z)
    return {"carryM": max(0.0, x * math.cos(direction)), "offlineM": x * math.sin(direction),
            "apexM": apex, "descentDeg": math.degrees(math.atan2(-vz, vx)), "flightTimeS": t,
            "landingHorizontalMps": vx, "landingVerticalMps": -vz,
            "landingSpinRpm": max(0.0, spin_rpm) * math.exp(-SPIN_DECAY_PER_S * t), "flightM": x}


def roll_meters(flight):
    """Roll after landing and the surface assumed for it."""
    omega = flight["landingSpinRpm"] * 2 * math.pi / 60
    rolling = max(0.0, (5 * flight["landingHorizontalMps"] - 2 * BALL_RADIUS_M * omega) / 7
                  - TURF_ABSORPTION * flight["landingVerticalMps"])
    green = flight["flightM"] < GREEN_MAX_CARRY_M and flight["descentDeg"] >= GREEN_MIN_DESCENT_DEG
    friction = GREEN_ROLL_FRICTION if green else FAIRWAY_ROLL_FRICTION
    return rolling ** 2 / (2 * GRAVITY * friction), "green" if green else "fairway"


def spin_loft_deg(launch_angle_deg, attack_angle_deg):
    """Spin loft (dynamic loft minus attack angle) implied by launch and attack, or None."""
    gap = launch_angle_deg - attack_angle_deg
    if not 0 < gap <= MAX_LAUNCH_ABOVE_ATTACK_DEG:
        return None
    target, low, high = math.radians(gap), 0.0, math.radians(80.0)
    for _ in range(60):
        middle = (low + high) / 2
        if middle - math.atan(FACE_TANGENT_RATIO * math.tan(middle)) < target:
            low = middle
        else:
            high = middle
    return math.degrees(low)


def impact_spin_rpm(club_id, club_speed_mps, launch_angle_deg, attack_angle_deg):
    """Backspin from club speed and how far launch sits above the attack angle, or None."""
    values = (club_speed_mps, launch_angle_deg, attack_angle_deg)
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in values) or club_speed_mps <= 0:
        return None
    gap = launch_angle_deg - attack_angle_deg
    # sin() stays well conditioned past the loft solve's limit; beyond +10 deg the
    # inputs themselves are implausible.
    if not 0 < gap <= MAX_LAUNCH_ABOVE_ATTACK_DEG + 10:
        return None
    return round(SPIN_LOFT_K.get(club_id, SPIN_LOFT_K["7-iron"]) * club_speed_mps * math.sin(math.radians(gap)))


def select_spin(club_id, ball_speed_mps, launch_angle_deg, measured_rpm=None, club_speed_mps=None,
                attack_angle_deg=None):
    """Spin for the flight model, in order of evidence: camera, impact estimate, club average.

    Returns (rpm, source) with source "camera", "impact-estimate" or "club-attack-assumption".
    """
    finite = lambda value: isinstance(value, (int, float)) and math.isfinite(value)
    if finite(measured_rpm):
        return measured_rpm, "camera"
    impact = impact_spin_rpm(club_id, club_speed_mps, launch_angle_deg, attack_angle_deg) if finite(
        club_speed_mps) and finite(attack_angle_deg) else None
    if impact is not None:
        return impact, "impact-estimate"
    return assumed_spin_rpm(club_id, ball_speed_mps, attack_angle_deg if finite(attack_angle_deg) else None),         "club-attack-assumption"


def carry_meters(ball_speed_mps, launch_angle_deg, direction_deg, spin_rpm):
    """Integrate drag and backspin lift to launch height; return target-line carry."""
    flight = simulate_flight(ball_speed_mps, launch_angle_deg, direction_deg, spin_rpm)
    return 0.0 if flight is None else round(flight["carryM"], 1)
