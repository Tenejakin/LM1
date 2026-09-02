#!/usr/bin/env python3
"""Pinpoint BLE-only GATT peripheral for Raspberry Pi OS."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any

from bless import (
    BlessGATTCharacteristic,
    BlessServer,
    GATTAttributePermissions,
    GATTCharacteristicProperties,
)

from pinpoint_protocol import (
    BLE_CHUNK_BYTES,
    PinpointProtocol,
    PROTOCOL_VERSION,
    SERVICE_VERSION,
    encode_message_chunks,
)


SERVICE_UUID = "7f510000-1b15-4d8d-8d9c-5f7b6a210001"
COMMAND_UUID = "7f510001-1b15-4d8d-8d9c-5f7b6a210001"
EVENT_UUID = "7f510002-1b15-4d8d-8d9c-5f7b6a210001"
NOTIFICATION_GAP_SECONDS = 0.015

logging.basicConfig(
    level=os.getenv("PINPOINT_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger("pinpoint.ble")


class PinpointBlePeripheral:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.server = BlessServer(
            name=os.getenv("PINPOINT_BLE_NAME", "Pinpoint LM"),
            loop=loop,
        )
        self.server.read_request_func = self._on_read
        self.server.write_request_func = self._on_write
        self.protocol = PinpointProtocol(self.send_message)
        self._notification_lock = asyncio.Lock()

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
            for chunk in encode_message_chunks(message, BLE_CHUNK_BYTES):
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
            GATTAttributePermissions.writable,
        )
        await self.server.add_new_characteristic(
            SERVICE_UUID,
            EVENT_UUID,
            GATTCharacteristicProperties.read | GATTCharacteristicProperties.notify,
            bytearray(f"pinpoint/{PROTOCOL_VERSION}\n", "ascii"),
            GATTAttributePermissions.readable,
        )
        await self.server.start()
        LOGGER.info(
            "Pinpoint BLE service %s is advertising (protocol %s)",
            SERVICE_VERSION,
            PROTOCOL_VERSION,
        )

    async def stop(self) -> None:
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
