import math
import unittest

from flight_model import (assumed_spin_rpm, carry_meters, impact_spin_rpm, roll_meters, simulate_flight,
                          spin_loft_deg)

MPH, YD = 0.44704, 0.9144
# Trackman PGA Tour averages: club mph, attack deg, ball mph, launch deg, spin rpm,
# carry yd, max height yd, landing angle deg.
TOUR = {
    "driver": (113, -1.3, 167, 10.9, 2686, 275, 32, 38),
    "5-iron": (94, -3.7, 132, 12.1, 5361, 194, 31, 49),
    "7-iron": (90, -4.3, 120, 16.3, 7097, 172, 32, 50),
    "pitching-wedge": (83, -5.0, 102, 24.2, 9304, 136, 29, 52),
}


class FlightModelTests(unittest.TestCase):
    def test_partial_swing_and_attack_change_assumed_spin(self):
        full = assumed_spin_rpm("sand-wedge", 31.32)
        chip = assumed_spin_rpm("sand-wedge", 7.2)
        steep = assumed_spin_rpm("sand-wedge", 7.2, -10)
        shallow = assumed_spin_rpm("sand-wedge", 7.2, 5)
        self.assertGreater(full, chip)
        self.assertGreater(steep, chip)
        self.assertLess(shallow, chip)

    def test_carry_uses_spin_and_direction(self):
        no_spin = carry_meters(45, 19, 0, 0)
        with_spin = carry_meters(45, 19, 0, 6500)
        offline = carry_meters(45, 19, 20, 6500)
        self.assertGreater(no_spin, 0)
        self.assertGreater(with_spin, no_spin)
        self.assertLess(offline, with_spin)

    def test_gentle_chip_remains_short(self):
        spin = assumed_spin_rpm("sand-wedge", 7.2139, -11.6598)
        carry = carry_meters(7.2139, 23.8095, -2.8204, spin)
        self.assertGreater(carry, 3)
        self.assertLess(carry, 6)

    def test_flight_matches_tour_averages(self):
        for club, (_, _, ball, launch, spin, carry, height, landing) in TOUR.items():
            flight = simulate_flight(ball * MPH, launch, 0, spin)
            self.assertAlmostEqual(flight["carryM"] / YD, carry, delta=carry * 0.08, msg=club)
            self.assertAlmostEqual(flight["apexM"] / YD, height, delta=5, msg=club)
            self.assertAlmostEqual(flight["descentDeg"], landing, delta=8, msg=club)

    def test_impact_spin_and_loft_reproduce_tour_values(self):
        for club, (club_mph, attack, _, launch, spin, *_rest) in TOUR.items():
            self.assertAlmostEqual(impact_spin_rpm(club, club_mph * MPH, launch, attack), spin, delta=spin * 0.1, msg=club)
        # A tour 7-iron is delivered with roughly 21 deg of dynamic loft.
        self.assertAlmostEqual(spin_loft_deg(16.3, -4.3) - 4.3, 21, delta=2)

    def test_impossible_launch_over_attack_has_no_loft(self):
        # Replayed chip 1790291972012751193 (…6716): launch 29.3, attack -14.8 gave 65 deg loft.
        self.assertIsNone(spin_loft_deg(29.3, -14.8))
        self.assertIsNotNone(spin_loft_deg(28.8, -7.7))

    def test_roll_anchors(self):
        drive = simulate_flight(167 * MPH, 10.9, 0, 2686)
        roll, surface = roll_meters(drive)
        self.assertEqual(surface, "fairway")
        self.assertAlmostEqual(roll / YD, 20, delta=3)
        chip = simulate_flight(12.3, 29, 0, impact_spin_rpm("sand-wedge", 10, 29, -8))
        roll, surface = roll_meters(chip)
        self.assertEqual(surface, "green")
        self.assertAlmostEqual(roll, chip["carryM"], delta=chip["carryM"] * 0.2)
        # A skulled chip lands flat and runs; it is not assumed to be on a green.
        skull = simulate_flight(17.7, 5.9, 0, 772)
        self.assertEqual(roll_meters(skull)[1], "fairway")

    def test_offline_follows_direction(self):
        flight = simulate_flight(40, 20, -5, 6000)
        self.assertLess(flight["offlineM"], 0)
        self.assertAlmostEqual(math.degrees(math.atan2(flight["offlineM"], flight["carryM"])), -5, places=3)


if __name__ == "__main__":
    unittest.main()
