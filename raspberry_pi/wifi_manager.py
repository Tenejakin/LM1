"""NetworkManager-backed Wi-Fi provisioning for the LM1 BLE service."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any


MAX_WIFI_NETWORKS = 12
WIFI_COMMAND_TIMEOUT_SECONDS = 45


class WifiProvisioningError(RuntimeError):
    """An error safe to return to the connected LM1 app."""


def wifi_interface() -> str:
    return os.getenv("PINPOINT_WIFI_INTERFACE", "wlan0").strip() or "wlan0"


def wifi_provisioning_available() -> bool:
    enabled = os.getenv("PINPOINT_WIFI_PROVISIONING", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    return enabled and shutil.which("nmcli") is not None


def _require_wifi_provisioning() -> None:
    if not wifi_provisioning_available():
        raise WifiProvisioningError(
            "Wi-Fi setup is unavailable. Update the Pi service or enable "
            "PINPOINT_WIFI_PROVISIONING."
        )


def _split_terse_row(row: str) -> list[str]:
    """Split an nmcli terse row while preserving escaped colons and backslashes."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in row:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


def _run_nmcli(
    arguments: list[str],
    *,
    timeout: int = WIFI_COMMAND_TIMEOUT_SECONDS,
    input_text: str | None = None,
    redacted_value: str | None = None,
) -> str:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    try:
        completed = subprocess.run(
            ["nmcli", *arguments],
            capture_output=True,
            text=True,
            input=input_text,
            timeout=timeout,
            check=False,
            env=environment,
        )
    except FileNotFoundError as error:
        raise WifiProvisioningError("NetworkManager is not installed on the Pi.") from error
    except subprocess.TimeoutExpired as error:
        raise WifiProvisioningError("Wi-Fi setup timed out. Move the Pi closer and try again.") from error

    if completed.returncode == 0:
        return completed.stdout

    detail = (completed.stderr.strip() or completed.stdout.strip()).replace("\n", " ")
    if redacted_value:
        detail = detail.replace(redacted_value, "[hidden]")
    if not detail:
        detail = f"NetworkManager exited with code {completed.returncode}."
    raise WifiProvisioningError(detail[:300])


def scan_wifi_networks(*, rescan: bool = True) -> list[dict[str, Any]]:
    _require_wifi_provisioning()
    output = _run_nmcli(
        [
            "--terse",
            "--escape",
            "yes",
            "--fields",
            "IN-USE,SSID,SIGNAL,SECURITY",
            "device",
            "wifi",
            "list",
            "--rescan",
            "yes" if rescan else "no",
            "ifname",
            wifi_interface(),
        ],
        timeout=20,
    )

    by_ssid: dict[str, dict[str, Any]] = {}
    for row in output.splitlines():
        fields = _split_terse_row(row)
        if len(fields) < 4:
            continue
        active, ssid, raw_signal, security = fields[:4]
        if not ssid:
            continue
        try:
            signal = max(0, min(100, int(raw_signal)))
        except ValueError:
            signal = 0
        connected = active.lower() in {"*", "yes", "true"}
        candidate = {
            "ssid": ssid,
            "signal": signal,
            "security": "Open" if security in {"", "--"} else security,
            "secure": security not in {"", "--"},
            "supported": "802.1X" not in security.upper() and "EAP" not in security.upper(),
            "connected": connected,
        }
        existing = by_ssid.get(ssid)
        if existing is None or connected or signal > existing["signal"]:
            by_ssid[ssid] = candidate

    return sorted(
        by_ssid.values(),
        key=lambda network: (not network["connected"], -network["signal"], network["ssid"].lower()),
    )[:MAX_WIFI_NETWORKS]


def get_wifi_status() -> dict[str, Any]:
    _require_wifi_provisioning()
    networks = scan_wifi_networks(rescan=False)
    active = next((network for network in networks if network["connected"]), None)
    result: dict[str, Any] = {
        "available": True,
        "connected": active is not None,
        "interface": wifi_interface(),
    }
    if active is None:
        return result

    result["ssid"] = active["ssid"]
    result["signal"] = active["signal"]
    address_output = _run_nmcli(
        [
            "--terse",
            "--escape",
            "yes",
            "--fields",
            "IP4.ADDRESS",
            "device",
            "show",
            wifi_interface(),
        ],
        timeout=10,
    )
    for row in address_output.splitlines():
        match = re.match(r"^IP4\.ADDRESS(?:\[\d+\])?:(.+)$", row)
        if match:
            result["ipAddress"] = _split_terse_row(f"x:{match.group(1)}")[1].split("/", 1)[0]
            break
    return result


def connect_wifi(ssid: str, password: str, *, hidden: bool = False) -> dict[str, Any]:
    _require_wifi_provisioning()
    if not isinstance(ssid, str) or not ssid.strip():
        raise WifiProvisioningError("Wi-Fi name is required.")
    if "\x00" in ssid or "\n" in ssid or len(ssid.encode("utf-8")) > 32:
        raise WifiProvisioningError("Wi-Fi name must be at most 32 bytes.")
    if not isinstance(password, str):
        raise WifiProvisioningError("Wi-Fi password must be text.")
    if "\x00" in password or "\n" in password or len(password.encode("utf-8")) > 128:
        raise WifiProvisioningError("Wi-Fi password is not valid.")

    _run_nmcli(["radio", "wifi", "on"], timeout=10)
    arguments = ["--wait", "35"]
    input_text = None
    if password:
        # --ask reads the secret from stdin, keeping it out of argv and service logs.
        arguments.append("--ask")
        input_text = f"{password}\n"
    arguments.extend(
        ["device", "wifi", "connect", ssid, "ifname", wifi_interface()]
    )
    if hidden:
        arguments.extend(["hidden", "yes"])
    _run_nmcli(
        arguments,
        input_text=input_text,
        redacted_value=password or None,
    )

    status = get_wifi_status()
    if not status.get("connected") or status.get("ssid") != ssid:
        raise WifiProvisioningError(
            "NetworkManager finished, but the Pi did not join the selected Wi-Fi."
        )
    return status
