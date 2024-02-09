"""The iDealLED device model."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
    retry_bluetooth_connection_error,
)

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .errors import Disconnected, DisconnectReason, NotConnected, Timeout, iDealLedError
from .models import BaseProcedure, DeviceInfo, NullProcedure

DISCONNECT_DELAY = 180
DEFAULT_ATTEMPTS = 3

_LOGGER = logging.getLogger(__name__)


@dataclass
class IdealLedData:
    """Data for the iDealLed integration."""

    lock: iDealLed
    coordinator: DataUpdateCoordinator[None]


class iDealLed:
    """Class representing an iDealLed."""

    coordinator: DataUpdateCoordinator[None]
    brightness: int

    def __init__(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData | None = None
    ) -> None:
        """Initialise."""
        self._procedure_lock: asyncio.Lock = (
            asyncio.Lock()
        )  # Lock to ensure a single procedure runs at once
        self._connect_lock: asyncio.Lock = (
            asyncio.Lock()
        )  # Lock to ensure a single connect happens at once
        self._client: BleakClient | None = None  # test
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data
        self._disconnect_reason: DisconnectReason | None = None
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._expected_disconnect: bool = False
        self.loop = asyncio.get_running_loop()
        self.device_info = DeviceInfo()

    @property
    def name(self) -> str:
        """Get the name of the device."""
        return str(self._ble_device.name or self._ble_device.address)

    @property
    def rssi(self) -> int | None:
        """Get the rssi of the device."""
        if self._advertisement_data:
            return self._advertisement_data.rssi
        return None

    def set_ble_device_and_advertisement_data(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        """Set the ble device."""
        _LOGGER.debug("%s: %s", self.name, inspect.currentframe().f_code.co_name)
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data

    async def update(self) -> bool:
        """Update the lock's status."""
        _LOGGER.debug("%s: Update", self.name)
        null_proc = NullProcedure(self)
        return await self._execute(null_proc)

    async def connect(self) -> None:
        """Connect the lock.

        Note: A connection is automatically established when performing an operation
        on the lock. This can be called to ensure the lock is in range.
        """
        _LOGGER.info("%s: Connect", self.name)
        await self._ensure_connected()

    async def disconnect(self) -> None:
        """Disconnect from the lock."""
        _LOGGER.info("%s: Disconnect", self.name)
        await self._execute_disconnect(DisconnectReason.USER_REQUESTED)

    @retry_bluetooth_connection_error(DEFAULT_ATTEMPTS)  # type: ignore[misc]
    async def _execute(self, procedure: BaseProcedure) -> bool:
        """Execute a procedure."""
        _LOGGER.debug(
            "%s: %s(%s)",
            self.name,
            inspect.currentframe().f_code.co_name,
            procedure.__class__.__name__,
        )
        if self._procedure_lock.locked():
            _LOGGER.debug(
                "%s: Procedure already in progress, waiting for it to complete; "
                "RSSI: %s",
                self.name,
                self.rssi,
            )
        async with self._procedure_lock:
            try:
                await self._ensure_connected()
                _LOGGER.debug("%s: About to run procedure", self.name)
                result = await procedure.execute()
                _LOGGER.debug("%s: Ran procedure", self.name)
                return result
            except asyncio.CancelledError as err:
                if self._disconnect_reason is None:
                    _LOGGER.debug("%s: Cancelled", self.name)
                    raise iDealLedError from err
                if self._disconnect_reason == DisconnectReason.TIMEOUT:
                    _LOGGER.debug("%s: Timeout", self.name)
                    raise Timeout from err
                _LOGGER.debug("%s: Disconnected", self.name)
                raise Disconnected(self._disconnect_reason) from err
            except iDealLedError:
                self._disconnect(DisconnectReason.ERROR)
                raise

    async def _ensure_connected(self) -> None:
        """Ensure connection to device is established."""
        _LOGGER.debug("%s: %s", self.name, inspect.currentframe().f_code.co_name)
        if self._connect_lock.locked():
            _LOGGER.debug(
                "%s: Connection already in progress, waiting for it to complete; "
                "RSSI: %s",
                self.name,
                self.rssi,
            )
        if self._client and self._client.is_connected:
            self._reset_disconnect_timer()
            return
        async with self._connect_lock:
            # Check again while holding the lock
            if self._client and self._client.is_connected:
                self._reset_disconnect_timer()
                return
            _LOGGER.debug("%s: Connecting; RSSI: %s", self.name, self.rssi)
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self.name,
                self._disconnected,
                use_services_cache=True,
                ble_device_callback=lambda: self._ble_device,
            )
            _LOGGER.debug("%s: Established connection; RSSI: %s", self.name, self.rssi)
            # await client.pair()
            _LOGGER.debug("%s: Connected; RSSI: %s", self.name, self.rssi)
            # services = client.services
            # for service in services:
            #    _LOGGER.debug("%s:service: %s", self.name, service.uuid)
            #    characteristics = service.characteristics
            #    for char in characteristics:
            #        _LOGGER.debug("%s:characteristic: %s", self.name, char.uuid)
            # resolved = self._resolve_characteristics(client.services)
            # if not resolved:
            #    # Try to handle services failing to load
            #    resolved = self._resolve_characteristics(await client.get_services())

            self._client = client
            self._disconnect_reason = None
            self._reset_disconnect_timer()

            # _LOGGER.debug(
            #    "%s: Subscribe to notifications; RSSI: %s", self.name, self.rssi
            # )
            # await client.start_notify(
            #    CHARACTERISTIC_UUID_TO_SERVER, self._notification_handler
            # )
            # await client.start_notify(
            #    CHARACTERISTIC_UUID_FROM_SERVER, self._notification_handler
            # )

    def _raise_if_not_connected(self) -> None:
        """Raise if the connection to device is lost. Also reset the disconnect timer."""
        if self._client and self._client.is_connected:
            self._reset_disconnect_timer()
            return
        raise NotConnected

    def _reset_disconnect_timer(self) -> None:
        """Reset disconnect timer."""
        _LOGGER.debug("%s: %s", self.name, inspect.currentframe().f_code.co_name)
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
        self._expected_disconnect = False
        self._disconnect_timer = self.loop.call_later(
            DISCONNECT_DELAY, self._timed_disconnect
        )

    def _disconnected(self, client: BleakClient) -> None:
        """Disconnected callback."""
        if self._expected_disconnect:
            _LOGGER.info("%s: Disconnected from device; RSSI: %s", self.name, self.rssi)
            return
        _LOGGER.warning(
            "%s: Device unexpectedly disconnected; RSSI: %s",
            self.name,
            self.rssi,
        )
        self._client = None
        self._disconnect(DisconnectReason.UNEXPECTED)

    def _timed_disconnect(self) -> None:
        """Disconnect from device."""
        self._disconnect_timer = None
        asyncio.create_task(self._execute_timed_disconnect())  # noqa: RUF006

    async def _execute_timed_disconnect(self) -> None:
        """Execute timed disconnection."""
        _LOGGER.debug(
            "%s: Disconnecting after timeout of %s",
            self.name,
            DISCONNECT_DELAY,
        )
        await self._execute_disconnect(DisconnectReason.TIMEOUT)

    def _disconnect(self, reason: DisconnectReason) -> None:
        """Disconnect from device."""
        _LOGGER.debug("%s: %s", self.name, inspect.currentframe().f_code.co_name)
        asyncio.create_task(self._execute_disconnect(reason))  # noqa: RUF006

    async def _execute_disconnect(self, reason: DisconnectReason) -> None:
        """Execute disconnection."""
        _LOGGER.debug("%s: Execute disconnect", self.name)
        if self._connect_lock.locked():
            _LOGGER.debug(
                "%s: Connection already in progress, waiting for it to complete; "
                "RSSI: %s",
                self.name,
                self.rssi,
            )
        async with self._connect_lock:
            client = self._client
            self._client = None
            if client and client.is_connected:
                self._expected_disconnect = True
                # await client.stop_notify(CHARACTERISTIC_UUID_TO_SERVER)
                # await client.stop_notify(CHARACTERISTIC_UUID_FROM_SERVER)
                await client.disconnect()
            self._reset(reason)
        _LOGGER.debug("%s: Execute disconnect done", self.name)

    def _reset(self, reason: DisconnectReason) -> None:
        """Reset."""
        _LOGGER.debug("%s: reset", self.name)
        self._disconnect_reason = reason
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
        self._disconnect_timer = None

    async def turn_on(self, brightness: int) -> None:
        """Turn on the light."""
        _LOGGER.debug("%s: Turn on (%s)", self.name, brightness)

    async def turn_off(self) -> None:
        """Turn off the light."""
        _LOGGER.debug("%s: Turn off", self.name)

    def is_on(self) -> bool:
        """Is On."""
        _LOGGER.debug("%s: Is On", self.name)
        return True
