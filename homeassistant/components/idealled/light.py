"""Platform for light integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

# Import the device class from the component that you want to support
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .models import IdealLedData, iDealLed

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the lock platform for Dormakaba dKey."""
    data: IdealLedData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([iDealLedLight(data.coordinator, data.lock)])


class iDealLedLight(LightEntity):
    """Representation of an iDealLed as a single light."""

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(
        self, coordinator: DataUpdateCoordinator[None], iDealLedDevice: iDealLed
    ) -> None:
        """Initialize."""
        self._light = iDealLedDevice
        self._name = iDealLedDevice.name
        self._state = None
        self._brightness = None

    @property
    def name(self) -> str:
        """Return the display name of this light."""
        return self._name

    @property
    def brightness(self) -> int | None:
        """Brightness."""
        return self._brightness

    @property
    def color_mode(self) -> ColorMode | None:
        """Color Mode."""
        return ColorMode.RGB

    @property
    def supported_color_modes(self) -> set[ColorMode] | set[str] | None:
        """Supported Color Modes."""
        return ColorMode.RGB

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self._state

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on.

        You can skip the brightness part if your light does not support
        brightness control.
        """
        self._brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
        await self._light.turn_on(self._brightness)
        self._state = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        await self._light.turn_off()
        self._state = False

    async def async_update(self) -> None:
        """Fetch new state data for this light.

        This is the only method that should fetch new data for Home Assistant.
        """
        # await self._light.update()
        if self._state is None:
            self._state = self._light.is_on()
        # TODO Figure out if there's a way to get the state of the lights
        # self._brightness = self._light.brightness
