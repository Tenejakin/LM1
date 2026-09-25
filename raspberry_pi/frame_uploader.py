"""Send retained original camera JPEGs to the ticketed LM1 cloud uploader."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from typing import Any

from ball_detector import DEFAULT_ROLLING_CAPTURE_PATH, _wait_for_capture_save


class FrameUploadSource:
    def __init__(self, capture_id: str, expected_count: int) -> None:
        if not re.fullmatch(r"capture-\d+", capture_id):
            raise ValueError("Invalid capture id")
        _wait_for_capture_save(capture_id)
        root = Path(os.getenv("PINPOINT_ROLLING_CAPTURE_PATH", str(DEFAULT_ROLLING_CAPTURE_PATH)))
        self.capture_id = capture_id
        self.directory = root / capture_id
        manifest_path = self.directory / "capture.json"
        if not manifest_path.is_file():
            raise ValueError("Original capture frames are no longer on the Pi")
        self.manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.frame_count = int(self.manifest.get("frameCount", 0))
        if self.frame_count != expected_count or not 1 <= self.frame_count <= 2000:
            raise ValueError("The Pi frame count does not match the saved shot")
        self.dual_camera = bool(self.manifest.get("dualCamera"))
        project_ref = os.getenv("PINPOINT_SUPABASE_PROJECT_REF", "")
        if not re.fullmatch(r"[a-z0-9]{20,40}", project_ref):
            raise ValueError("PINPOINT_SUPABASE_PROJECT_REF is not configured")
        self.upload_url = f"https://{project_ref}.supabase.co/functions/v1/shot-frame-ingest"

    def upload_frame(self, index: int, ticket: str) -> None:
        if not 0 <= index < self.frame_count:
            raise ValueError("Frame index is outside this capture")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", ticket):
            raise ValueError("Invalid frame upload ticket")
        name = f"frame-{index:04d}.jpg"
        primary = (self.directory / name).read_bytes()
        payload: dict[str, Any] = {
            "captureId": self.capture_id,
            "frameIndex": index,
            "frameCount": self.frame_count,
            "primaryBase64": base64.b64encode(primary).decode("ascii"),
            "timeMs": (self.manifest.get("frameTimesMs") or [None] * self.frame_count)[index],
        }
        if self.dual_camera:
            secondary = (self.directory / "camera-secondary" / name).read_bytes()
            payload["secondaryBase64"] = base64.b64encode(secondary).decode("ascii")
            payload["pairOffsetUs"] = self.manifest["dualCamera"]["pairOffsetsUs"][index]
        request = urllib.request.Request(
            self.upload_url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Upload-Token": ticket},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status != 200:
                    raise RuntimeError(f"Cloud rejected frame {index} (HTTP {response.status})")
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read(1000).decode("utf-8")).get("error", "Upload failed")
            except (UnicodeError, ValueError):
                detail = "Upload failed"
            raise RuntimeError(f"Cloud rejected frame {index} (HTTP {error.code}): {detail}") from error
