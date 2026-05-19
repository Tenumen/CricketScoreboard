"""BLE GATT peripheral that mimics a Play-Cricket Scorer 'generic external
scoreboard'. Uses `bless` to wrap BlueZ (Linux) / CoreBluetooth (macOS) /
WinRT (Windows) so the same code runs on the Pi and on a dev laptop for
smoke tests.

The phone is BLE central; it scans, connects, then writes ASCII frames to
the scoreboard-item characteristic. Each write is decoded via tokens.parse_frame,
applied to the MatchAccumulator, and appended to a discovery log so unknown
codes can be triaged later.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Optional

from . import tokens as T
from .state import MatchAccumulator

log = logging.getLogger(__name__)


_ADVERT_NAME = "scoreboard24"


async def run_peripheral(accumulator: MatchAccumulator,
                         discovery_log_path: Optional[str] = None,
                         stop_event: Optional[asyncio.Event] = None) -> None:
    """Start the BLE GATT peripheral and block until cancelled.

    Imports of `bless` are deferred so unit tests that exercise only the
    accumulator / serializers don't need the BlueZ stack installed.
    """
    from bless import (   # type: ignore
        BlessServer,
        BlessGATTCharacteristic,
        GATTCharacteristicProperties,
        GATTAttributePermissions,
    )

    disc_fp = None
    if discovery_log_path:
        try:
            disc_fp = open(discovery_log_path, "a", buffering=1)
        except OSError as e:
            log.warning("could not open discovery log %s: %s", discovery_log_path, e)

    def _log_token(raw: bytes, code: Optional[str], value: Optional[str], known: bool) -> None:
        if disc_fp is None:
            return
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        hex_preview = raw.hex(" ")
        if code is None:
            disc_fp.write(f"{ts} RAW         {hex_preview}\n")
        elif known:
            disc_fp.write(f"{ts} {code} {value!r}\n")
        else:
            disc_fp.write(f"{ts} {code} UNKNOWN {value!r} ({hex_preview})\n")

    def _on_read(characteristic: BlessGATTCharacteristic, **_) -> bytearray:
        # No state is read back today — return the current generation as a
        # liveness probe so an inquisitive central sees something.
        return bytearray(str(accumulator.generation), "utf-8")

    def _on_write(characteristic: BlessGATTCharacteristic, value: bytes, **_) -> None:
        payload = bytes(value)
        parsed  = T.parse_frame(payload)
        if parsed is None:
            log.debug("dropping malformed frame: %r", payload)
            _log_token(payload, None, None, False)
            return
        code, val = parsed
        known = T.is_known(code)
        log.debug("token %s %r (known=%s)", code, val, known)
        _log_token(payload, code, val, known)
        try:
            accumulator.apply(code, val)
        except Exception:
            log.exception("accumulator.apply failed for code=%s value=%r", code, val)

    server = BlessServer(name=_ADVERT_NAME, loop=asyncio.get_running_loop())
    server.read_request_func  = _on_read
    server.write_request_func = _on_write

    await server.add_new_service(T.SERVICE_UUID)
    await server.add_new_characteristic(
        service_uuid=T.SERVICE_UUID,
        char_uuid=T.CHARACTERISTIC_UUID,
        properties=(GATTCharacteristicProperties.read
                    | GATTCharacteristicProperties.write
                    | GATTCharacteristicProperties.notify),
        value=None,
        permissions=(GATTAttributePermissions.readable
                     | GATTAttributePermissions.writeable),
    )

    await server.start()
    log.info("BLE peripheral advertising as %r (service %s)",
             _ADVERT_NAME, T.SERVICE_UUID)
    try:
        if stop_event is None:
            stop_event = asyncio.Event()
        await stop_event.wait()
    finally:
        await server.stop()
        if disc_fp is not None:
            disc_fp.close()
        log.info("BLE peripheral stopped")
