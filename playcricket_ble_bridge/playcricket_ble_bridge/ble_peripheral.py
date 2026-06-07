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
from .ble_dbus import count_connected_devices, ensure_adapter_hygiene

log = logging.getLogger(__name__)


_ADVERT_NAME = "scoreboard24"

# How often the watchdog checks the real link/advertising state. Cheap on a Pi 3B
# (one dbus round-trip) and fast enough that a re-advertise follows a disconnect
# within a few seconds.
_WATCHDOG_POLL_SECONDS = 3.0


async def _safe_readvertise(server) -> None:
    """Tear down (guarded) and restart advertising. Never raises.

    BlueZ deactivates a connectable advertisement the moment a central connects
    and never re-registers it, so after a disconnect the Pi stops being
    discoverable. ``start_advertising`` won't re-register an existing advert path
    and ``stop_advertising`` pops ``app.advertisements`` (erroring if empty), so we
    stop first only when there's something to stop, then start fresh.
    """
    app = server.app
    adapter = server.adapter
    if app.advertisements:
        try:
            await app.stop_advertising(adapter)
        except Exception as e:
            log.debug("stop_advertising during re-advertise failed (ignored): %s", e)
    try:
        await app.start_advertising(adapter)
        log.info("re-advertising as %r resumed", _ADVERT_NAME)
    except Exception as e:
        log.warning("start_advertising failed, will retry next poll: %s", e)


async def _advertising_watchdog(server, accumulator: MatchAccumulator,
                                stop_event: "asyncio.Event") -> None:
    """Keep a connectable advert alive whenever no central is connected.

    Reads the authoritative ``org.bluez.Device1.Connected`` state (not bless's
    notify-subscription proxy) every few seconds. When nothing is connected and the
    adapter isn't advertising, it re-advertises — covering both reconnect-after-
    device-switch and recovery from a silently dropped (half-open) link, which BlueZ
    surfaces by flipping ``Connected`` to false after its supervision timeout.

    The accumulator is intentionally left untouched: a brief link blip must not wipe
    a live match (the phone re-sends its init tokens on reconnect).
    """
    prev_connected = 0
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(),
                                   timeout=_WATCHDOG_POLL_SECONDS)
            break  # stop_event set -> shut down promptly
        except asyncio.TimeoutError:
            pass  # normal: time for the next poll

        try:
            connected = await count_connected_devices(server.bus)
        except Exception as e:
            log.debug("watchdog: could not read device state (ignored): %s", e)
            continue

        if connected != prev_connected:
            if connected > prev_connected:
                log.info("BLE central connected (now %d connected)", connected)
            else:
                log.info("BLE central disconnected (now %d connected)", connected)
            prev_connected = connected

        if connected == 0:
            try:
                advertising = await server.is_advertising()
            except Exception as e:
                log.debug("watchdog: is_advertising failed (ignored): %s", e)
                advertising = True  # don't thrash on a transient read error
            if not advertising:
                log.info("no device connected and not advertising -> re-advertising")
                await _safe_readvertise(server)


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

    # Make sure the adapter is powered, pairable and discoverable. Best-effort.
    try:
        await ensure_adapter_hygiene(server.adapter)
    except Exception as e:
        log.warning("adapter hygiene setup failed (continuing): %s", e)

    watchdog = None
    try:
        if stop_event is None:
            stop_event = asyncio.Event()
        watchdog = asyncio.create_task(
            _advertising_watchdog(server, accumulator, stop_event),
            name="ble-advertising-watchdog",
        )
        await stop_event.wait()
    finally:
        if watchdog is not None:
            watchdog.cancel()
            try:
                await watchdog
            except (asyncio.CancelledError, Exception):
                pass
        await server.stop()
        if disc_fp is not None:
            disc_fp.close()
        log.info("BLE peripheral stopped")
