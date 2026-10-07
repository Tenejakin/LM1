#!/usr/bin/env python3
"""Pinpoint BLE-only GATT peripheral for Raspberry Pi OS."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
from concurrent.futures import CancelledError as FutureCancelledError
from typing import Any

from camera_source import camera_diagnostics, uses_csi

from bless import (
    BlessGATTCharacteristic,
    BlessServer,
    GATTAttributePermissions,
    GATTCharacteristicProperties,
)

from pinpoint_protocol import (
    PinpointProtocol,
    PROTOCOL_VERSION,
    SERVICE_VERSION,
    build_preview_event,
    configured_camera_device,
    encode_message_chunks,
)

try:
    from ball_detector import BallEvent, BallMonitor
except ModuleNotFoundError:
    BallEvent = Any  # type: ignore[misc,assignment]
    BallMonitor = None  # type: ignore[assignment]


SERVICE_UUID = "7f510000-1b15-4d8d-8d9c-5f7b6a210001"
COMMAND_UUID = "7f510001-1b15-4d8d-8d9c-5f7b6a210001"
EVENT_UUID = "7f510002-1b15-4d8d-8d9c-5f7b6a210001"
NOTIFICATION_GAP_SECONDS = 0.015
COMMAND_PERMISSIONS = GATTAttributePermissions.writeable
EVENT_PERMISSIONS = GATTAttributePermissions.readable

logging.basicConfig(
    level=os.getenv("PINPOINT_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger("pinpoint.ble")


class PinpointBlePeripheral:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.server = BlessServer(
            name=os.getenv("PINPOINT_BLE_NAME", "LM1 PRO"),
            loop=loop,
        )
        self.server.read_request_func = self._on_read
        self.server.write_request_func = self._on_write
        self.protocol = PinpointProtocol(
            self.send_message,
            reset_ball_calibration=self._reset_ball_calibration,
            request_calibration_capture=self._request_calibration_capture,
            request_exposure_calibration=self._request_exposure_calibration,
        )
        self._notification_lock = asyncio.Lock()
        self._ball_stop = threading.Event()
        self._ball_calibration_reset = threading.Event()
        self._calibration_capture_request = threading.Event()
        self._calibration_capture_camera = "primary"
        self._exposure_calibration_request = threading.Event()
        self._ball_task: asyncio.Task[None] | None = None
        self._preview_future: Any | None = None
        self._preview_logged = False

    def _reset_ball_calibration(self) -> bool:
        if self._ball_task is None or self._ball_task.done():
            return False
        self._ball_calibration_reset.set()
        return True

    def _request_calibration_capture(self, camera: str = "primary") -> bool:
        if self._ball_task is None or self._ball_task.done():
            return False
        self._calibration_capture_camera = camera
        self._calibration_capture_request.set()
        return True

    def _request_exposure_calibration(self) -> bool:
        if self._ball_task is None or self._ball_task.done():
            return False
        self._exposure_calibration_request.set()
        return True

    def _on_read(
        self,
        characteristic: BlessGATTCharacteristic,
        *_: Any,
        **__: Any,
    ) -> bytearray:
        return characteristic.value or bytearray(f"pinpoint/{PROTOCOL_VERSION}\n", "ascii")

    def _on_write(
        self,
        characteristic: BlessGATTCharacteristic,
        value: Any,
        *_: Any,
        **__: Any,
    ) -> None:
        characteristic.value = bytearray(value)
        if str(characteristic.uuid).lower() != COMMAND_UUID:
            return
        future = asyncio.run_coroutine_threadsafe(
            self.protocol.receive_chunk(bytes(value)),
            self.loop,
        )
        future.add_done_callback(self._log_command_error)

    @staticmethod
    def _log_command_error(future: Any) -> None:
        try:
            future.result()
        except Exception:
            LOGGER.exception("BLE command processing failed")

    async def send_message(self, message: dict[str, Any]) -> None:
        characteristic = self.server.get_characteristic(EVENT_UUID)
        if characteristic is None:
            LOGGER.error("Event characteristic is unavailable")
            return

        async with self._notification_lock:
            for chunk in encode_message_chunks(message, self.protocol.notification_chunk_bytes):
                characteristic.value = bytearray(chunk)
                self.server.update_value(SERVICE_UUID, EVENT_UUID)
                await asyncio.sleep(NOTIFICATION_GAP_SECONDS)

    async def start(self) -> None:
        await self.server.add_new_service(SERVICE_UUID)
        await self.server.add_new_characteristic(
            SERVICE_UUID,
            COMMAND_UUID,
            GATTCharacteristicProperties.write,
            bytearray(),
            COMMAND_PERMISSIONS,
        )
        await self.server.add_new_characteristic(
            SERVICE_UUID,
            EVENT_UUID,
            GATTCharacteristicProperties.read | GATTCharacteristicProperties.notify,
            bytearray(f"pinpoint/{PROTOCOL_VERSION}\n", "ascii"),
            EVENT_PERMISSIONS,
        )
        await self.server.start()
        LOGGER.info(
            "Pinpoint BLE service %s is advertising (protocol %s)",
            SERVICE_VERSION,
            PROTOCOL_VERSION,
        )
        self._start_ball_monitor()

    def _start_ball_monitor(self) -> None:
        enabled = os.getenv("PINPOINT_AUTO_BALL_DETECTION", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        camera_device = configured_camera_device()
        preview_enabled = os.getenv("PINPOINT_BLE_PREVIEW", "false").lower() in {"1", "true", "yes"}
        if not enabled and not preview_enabled:
            LOGGER.info("Camera monitoring is disabled")
            return
        if BallMonitor is None:
            LOGGER.error("Automatic ball detection needs the python3-opencv package")
            return
        if not uses_csi() and (camera_device is None or not camera_device.exists()):
            LOGGER.warning("Automatic ball detection is waiting for a configured camera")
            return

        monitor = BallMonitor(camera_device)
        self._ball_stop.clear()
        self._calibration_capture_request.clear()
        self._exposure_calibration_request.clear()
        self._ball_task = asyncio.create_task(
            asyncio.to_thread(
                monitor.run,
                self._ball_stop,
                self._on_ball_event,
                self._on_preview_frame,
                self._ball_calibration_reset,
                self._calibration_capture_request,
                self._on_calibration_result,
                self._exposure_calibration_request,
                self._on_exposure_calibration,
                calibration_capture_camera=lambda: self._calibration_capture_camera,
                capture_mode=lambda: self.protocol.capture_mode,
                current_club=lambda: self.protocol.club_id,
                emit_readiness=self._on_readiness,
            )
        )
        self._ball_task.add_done_callback(self._log_ball_monitor_error)

    def _on_ball_event(self, event: BallEvent) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self.protocol.ball_presence_changed(
                event.present,
                event.rolling_capture_frames or event.frame_count,
                event.duration_ms,
                event.capture_id,
                event.impact_frame_index,
                event.analysis,
            ),
            self.loop,
        )
        future.add_done_callback(self._log_command_error)

    def _on_readiness(self, items: list[dict[str, Any]]) -> None:
        future = asyncio.run_coroutine_threadsafe(self.protocol.readiness_checked(items), self.loop)
        future.add_done_callback(self._log_command_error)

    def _on_calibration_result(self, result: dict[str, Any]) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self.protocol.calibration_image_captured(result),
            self.loop,
        )
        future.add_done_callback(self._log_command_error)

    def _on_exposure_calibration(self, result: dict[str, Any]) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self.protocol.exposure_calibrated(result),
            self.loop,
        )
        future.add_done_callback(self._log_command_error)

    def _on_preview_frame(self, jpeg_bytes: bytes, secondary_jpeg: bytes | None = None) -> None:
        if os.getenv("PINPOINT_BLE_PREVIEW", "false").lower() not in {
            "1",
            "true",
            "yes",
        }:
            return
        if self._preview_future is not None and not self._preview_future.done():
            return
        if self.protocol.state == "processing":
            return  # The capture result owns the notification channel until it is delivered.
        if not self._preview_logged:
            LOGGER.info("Camera preview ready: %d JPEG bytes; diagnostics=%s", len(jpeg_bytes), camera_diagnostics())
            self._preview_logged = True
        self._preview_future = asyncio.run_coroutine_threadsafe(
            self.send_message(build_preview_event(jpeg_bytes, secondary_jpeg)),
            self.loop,
        )
        self._preview_future.add_done_callback(self._log_preview_error)

    @staticmethod
    def _log_preview_error(future: Any) -> None:
        try:
            future.result()
        except FutureCancelledError:
            return
        except Exception:
            LOGGER.exception("BLE preview transfer failed")

    @staticmethod
    def _log_ball_monitor_error(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            LOGGER.exception("Automatic ball detector stopped unexpectedly")

    async def stop(self) -> None:
        self._ball_stop.set()
        if self._ball_task:
            try:
                await asyncio.wait_for(self._ball_task, timeout=3)
            except TimeoutError:
                self._ball_task.cancel()
                await asyncio.gather(self._ball_task, return_exceptions=True)
            self._ball_task = None
        await self.protocol.close()
        await self.server.stop()


async def main() -> None:
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()
    peripheral = PinpointBlePeripheral(loop)

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stopped.set)

    await peripheral.start()
    try:
        await stopped.wait()
    finally:
        await peripheral.stop()


if __name__ == "__main__":
    asyncio.run(main())
