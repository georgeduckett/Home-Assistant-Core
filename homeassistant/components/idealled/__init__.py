"""The iDeal LED integration."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import ADDRESS, BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_SECONDS
from .errors import IDEALLED_EXCEPTIONS
from .iDealLed import IdealLedData, iDealLed

# TODO List the platforms that you want to support.
# For your initial PR, limit it to 1 platform.
PLATFORMS: list[Platform] = [Platform.LIGHT]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iDeal LED from a config entry."""
    address: str = entry.data[CONF_ADDRESS]

    ble_device = bluetooth.async_ble_device_from_address(hass, address.upper(), True)
    if not ble_device:
        raise ConfigEntryNotReady(f"Could not find dKey device with address {address}")

    lights = iDealLed(ble_device)

    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Update from a ble callback."""
        lights.set_ble_device_and_advertisement_data(
            service_info.device, service_info.advertisement
        )

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher({ADDRESS: address}),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    async def _async_update() -> None:
        """Update the device state."""
        try:
            await lights.update()
            await lights.disconnect()
        except IDEALLED_EXCEPTIONS as ex:
            raise UpdateFailed(str(ex)) from ex

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=lights.name,
        update_method=_async_update,
        update_interval=timedelta(seconds=UPDATE_SECONDS),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = IdealLedData(lights, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _async_stop(event: Event) -> None:
        """Close the connection."""
        await lights.disconnect()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data: IdealLedData = hass.data[DOMAIN].pop(entry.entry_id)
        await data.lock.disconnect()

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    if unload_ok := await hass.config_entries.async_remove(config_entry.entry_id):
        data: IdealLedData = hass.data[DOMAIN].pop(config_entry.entry_id)
        await data.lock.disconnect()
    return unload_ok
