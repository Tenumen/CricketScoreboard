"""Low-level BlueZ dbus helpers for the BLE peripheral watchdog.

`bless` gives us a connected dbus_next bus (``server.bus``) and an adapter
ProxyObject (``server.adapter``), but its ``is_connected()`` only reflects GATT
notify subscriptions, not the real ACL link. These helpers read the authoritative
connection state straight from BlueZ and keep the adapter configured so a central
can always (re)discover and (re)connect.

All functions are async and run on the same asyncio loop as the BlessServer, so the
dbus bus is only ever touched from its owning loop.
"""
from __future__ import annotations

import logging
from typing import Any

from dbus_next.signature import Variant  # type: ignore

log = logging.getLogger(__name__)

_OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
_PROPERTIES_IFACE     = "org.freedesktop.DBus.Properties"
_BLUEZ_SERVICE        = "org.bluez"
_DEVICE_IFACE         = "org.bluez.Device1"
_ADAPTER_IFACE        = "org.bluez.Adapter1"


async def count_connected_devices(bus) -> int:
    """Return how many BlueZ devices are currently ``Connected``.

    This is the ground-truth link check — independent of GATT notify
    subscriptions — so it is correct even when a central only ever writes.
    Uses the same GetManagedObjects idiom bless itself uses.
    """
    node    = await bus.introspect(_BLUEZ_SERVICE, "/")
    obj     = bus.get_proxy_object(_BLUEZ_SERVICE, "/", node)
    manager = obj.get_interface(_OBJECT_MANAGER_IFACE)
    managed = await manager.call_get_managed_objects()

    count = 0
    for _path, ifaces in managed.items():
        device = ifaces.get(_DEVICE_IFACE)
        if device is None:
            continue
        connected = device.get("Connected")
        if connected is not None and connected.value:
            count += 1
    return count


async def set_adapter_property(adapter, name: str, variant: Variant) -> None:
    """Set a single org.bluez.Adapter1 property via the Properties interface."""
    props = adapter.get_interface(_PROPERTIES_IFACE)
    await props.call_set(_ADAPTER_IFACE, name, variant)


async def get_adapter_property(adapter, name: str) -> Any:
    """Get a single org.bluez.Adapter1 property value."""
    props = adapter.get_interface(_PROPERTIES_IFACE)
    variant = await props.call_get(_ADAPTER_IFACE, name)
    return variant.value


async def ensure_adapter_hygiene(adapter) -> None:
    """Best-effort: make the adapter powered, pairable and discoverable.

    Each property is set independently and a failure on one is logged but never
    raised, so a quirky BlueZ stack can't stop the peripheral from starting.
    """
    settings = (
        ("Powered",             Variant("b", True)),
        ("Pairable",            Variant("b", True)),
        ("Discoverable",        Variant("b", True)),
        # 0 = never auto-expire; otherwise BlueZ turns Discoverable off after 180s.
        ("DiscoverableTimeout", Variant("u", 0)),
    )
    for name, variant in settings:
        try:
            await set_adapter_property(adapter, name, variant)
        except Exception as e:
            log.warning("could not set adapter %s=%r (ignored): %s",
                        name, variant.value, e)
