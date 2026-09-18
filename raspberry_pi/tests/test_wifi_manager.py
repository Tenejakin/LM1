import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wifi_manager import (  # noqa: E402
    WifiProvisioningError,
    connect_wifi,
    get_wifi_status,
    scan_wifi_networks,
)


def completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["nmcli"], returncode, stdout=stdout, stderr=stderr)


class WifiManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PINPOINT_WIFI_PROVISIONING"] = "true"
        os.environ["PINPOINT_WIFI_INTERFACE"] = "wlan0"
        self.nmcli_available = patch("wifi_manager.shutil.which", return_value="/usr/bin/nmcli")
        self.nmcli_available.start()

    def tearDown(self) -> None:
        self.nmcli_available.stop()
        os.environ.pop("PINPOINT_WIFI_PROVISIONING", None)
        os.environ.pop("PINPOINT_WIFI_INTERFACE", None)

    @patch("wifi_manager.subprocess.run")
    def test_scan_deduplicates_and_unescapes_networks(self, run: unittest.mock.Mock) -> None:
        run.return_value = completed(
            "*:Home\\:Lab:88:WPA2\n"
            ":Guest:51:--\n"
            ":Home\\:Lab:60:WPA2\n"
            ":Company:92:WPA2 802.1X\n"
        )

        networks = scan_wifi_networks()

        self.assertEqual(networks[0]["ssid"], "Home:Lab")
        self.assertTrue(networks[0]["connected"])
        self.assertEqual(networks[1]["ssid"], "Company")
        self.assertFalse(networks[1]["supported"])
        self.assertEqual(networks[2]["security"], "Open")

    @patch("wifi_manager.subprocess.run")
    def test_status_reports_active_ssid_and_wifi_ip(self, run: unittest.mock.Mock) -> None:
        run.side_effect = [
            completed("*:Jakin SUPER_5G:97:WPA2\n"),
            completed("IP4.ADDRESS[1]:192.168.8.42/24\n"),
        ]

        status = get_wifi_status()

        self.assertTrue(status["connected"])
        self.assertEqual(status["ssid"], "Jakin SUPER_5G")
        self.assertEqual(status["ipAddress"], "192.168.8.42")

    @patch("wifi_manager.subprocess.run")
    def test_connect_reads_password_from_stdin_not_process_arguments(
        self,
        run: unittest.mock.Mock,
    ) -> None:
        secret = "correct horse battery staple"
        run.side_effect = [
            completed(),
            completed("Device 'wlan0' successfully activated\n"),
            completed("*:Jakin SUPER_5G:97:WPA2\n"),
            completed("IP4.ADDRESS[1]:192.168.8.42/24\n"),
        ]

        status = connect_wifi("Jakin SUPER_5G", secret)

        self.assertTrue(status["connected"])
        connect_call = run.call_args_list[1]
        self.assertNotIn(secret, connect_call.args[0])
        self.assertEqual(connect_call.kwargs["input"], f"{secret}\n")

    @patch("wifi_manager.subprocess.run")
    def test_networkmanager_error_redacts_password(self, run: unittest.mock.Mock) -> None:
        secret = "not-the-right-password"
        run.side_effect = [
            completed(),
            completed(stderr=f"activation failed for {secret}", returncode=4),
        ]

        with self.assertRaises(WifiProvisioningError) as caught:
            connect_wifi("Home", secret)

        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("[hidden]", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
