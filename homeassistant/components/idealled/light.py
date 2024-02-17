"""The light classes."""
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    PLATFORM_SCHEMA,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .idealled import IDEALLEDInstance

LOGGER = logging.getLogger(__name__)
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({vol.Required(CONF_MAC): cv.string})


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the lights."""
    instance = hass.data[DOMAIN][config_entry.entry_id]
    await instance.update()
    async_add_entities(
        [
            IDEALLEDLight(instance, config_entry.data["name"], config_entry.entry_id),
            EffectColourLight(
                instance,
                0,
                config_entry.data["name"] + " Effect Color 1",
                config_entry.entry_id + "_effect_color_1",
            ),
            EffectColourLight(
                instance,
                1,
                config_entry.data["name"] + " Effect Color 2",
                config_entry.entry_id + "_effect_color_2",
            ),
            EffectColourLight(
                instance,
                2,
                config_entry.data["name"] + " Effect Color 3",
                config_entry.entry_id + "_effect_color_3",
            ),
            EffectColourLight(
                instance,
                3,
                config_entry.data["name"] + " Effect Color 4",
                config_entry.entry_id + "_effect_color_4",
            ),
            EffectColourLight(
                instance,
                4,
                config_entry.data["name"] + " Effect Color 5",
                config_entry.entry_id + "_effect_color_5",
            ),
            EffectColourLight(
                instance,
                5,
                config_entry.data["name"] + " Effect Color 6",
                config_entry.entry_id + "_effect_color_6",
            ),
            EffectColourLight(
                instance,
                6,
                config_entry.data["name"] + " Effect Color 7",
                config_entry.entry_id + "_effect_color_7",
            ),
        ]
    )
    # config_entry.async_on_unload(await instance.stop())


class EffectColourLight(LightEntity):
    """A class representing a single colour that the effects use."""

    def __init__(
        self,
        idealledinstance: IDEALLEDInstance,
        effect_colour_index: int,
        name: str,
        entry_id: str,
    ) -> None:
        """Initialise the class."""
        self._instance = idealledinstance
        self._effect_colour_index = effect_colour_index
        self._entry_id = entry_id
        self._attr_supported_color_modes = {ColorMode.RGB}
        self._attr_supported_features = LightEntityFeature.EFFECT
        self._attr_brightness_step_pct = 10
        self._attr_name = name
        self._attr_unique_id = (
            self._instance.mac + "_effect_color_" + str(effect_colour_index)
        )
        self._instance.local_callback = self.light_local_callback
        self._rgb_color = (255, 255, 255)
        self._brightness = None
        self._is_on = True

    @property
    def available(self) -> bool:
        """Determines whether the light is avaialable."""
        return self._instance.is_on is not None

    @property
    def brightness(self) -> int:
        """The brightness."""
        return self._brightness

    @property
    def brightness_step_pct(self):
        """The amout the brightness changes by."""
        return self._attr_brightness_step_pct

    @property
    def is_on(self) -> bool | None:
        """Whether the LEDs are on."""
        return self._is_on

    @property
    def supported_features(self) -> LightEntityFeature:
        """Flag supported features."""
        return self._attr_supported_features

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Flag supported color modes."""
        return self._attr_supported_color_modes

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        """Return the hs color value."""
        return self._rgb_color

    @property
    def color_mode(self) -> ColorMode:
        """Return the color mode of the light."""
        return ColorMode.RGB

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self._instance.mac)
            },
            name=self.name,
            connections={(dr.CONNECTION_NETWORK_MAC, self._instance.mac)},
        )

    @property
    def should_poll(self) -> bool:
        """We shouldn't poll since it can't provide updates."""
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        LOGGER.info("Turn on called.  kwargs: %s", str(kwargs))
        self._is_on = True

        if ATTR_BRIGHTNESS in kwargs:
            self._brightness = kwargs[ATTR_BRIGHTNESS]

        if ATTR_RGB_COLOR in kwargs:
            self._rgb_color = (
                kwargs[ATTR_RGB_COLOR][0],
                kwargs[ATTR_RGB_COLOR][1],
                kwargs[ATTR_RGB_COLOR][2],
            )

        if self._brightness is None:
            self._brightness = 255
        brightness_percent = int(self._brightness * 100 / 255)

        # Now adjust the RBG values to match the brightness
        red = int(self._rgb_color[0] * brightness_percent / 100)
        green = int(self._rgb_color[1] * brightness_percent / 100)
        blue = int(self._rgb_color[2] * brightness_percent / 100)
        await self._instance.set_effect_colour(
            self._effect_colour_index, (red, green, blue)
        )

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        self._is_on = False
        await self._instance.set_effect_colour(self._effect_colour_index, (0, 0, 0))
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the entity."""
        LOGGER.debug("async update called")
        await self._instance.update()
        self.async_write_ha_state()

    def light_local_callback(self):
        """Perform the callback."""
        self.async_write_ha_state()

    async def update_ha_state(self) -> None:
        """Update HA state."""
        await self._instance.update()
        self.async_write_ha_state()


class IDEALLEDLight(
    LightEntity
):  # TODO: Use RestoreEntity to save/load state across reloads
    """The main class representing the LED lights."""

    def __init__(
        self, idealledinstance: IDEALLEDInstance, name: str, entry_id: str
    ) -> None:
        """Initialise the class."""
        self._instance = idealledinstance
        self._entry_id = entry_id
        self._effect = None
        self._attr_supported_color_modes = {ColorMode.RGB}
        self._attr_supported_features = LightEntityFeature.EFFECT
        self._attr_brightness_step_pct = 10
        self._attr_name = name
        self._attr_unique_id = self._instance.mac
        self._instance.local_callback = self.light_local_callback

    @property
    def available(self) -> bool:
        """Determines whether the light is avaialable."""
        return self._instance.is_on is not None

    @property
    def brightness(self) -> int:
        """The brightness."""
        return self._instance.brightness

    @property
    def brightness_step_pct(self):
        """The amout the brightness changes by."""
        return self._attr_brightness_step_pct

    @property
    def is_on(self) -> bool | None:
        """Whther the LEDs are on."""
        return self._instance.is_on

    @property
    def effect_list(self) -> list[str]:
        """The list of possible supported effects."""
        return self._instance.effect_list

    @property
    def effect(self) -> str:
        """The current effect."""
        return self._instance.effect

    @property
    def supported_features(self) -> LightEntityFeature:
        """Flag supported features."""
        return self._attr_supported_features

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Flag supported color modes."""
        return self._attr_supported_color_modes

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        """Return the hs color value."""
        return self._instance.rgb_color

    @property
    def color_mode(self) -> ColorMode:
        """Return the color mode of the light."""
        return self._instance.color_mode

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self._instance.mac)
            },
            name=self.name,
            connections={(dr.CONNECTION_NETWORK_MAC, self._instance.mac)},
        )

    @property
    def should_poll(self) -> bool:
        """We shouldn't poll since it can't provide updates."""
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        LOGGER.info("Turn on called.  kwargs: %s", str(kwargs))
        if not self.is_on:
            await self._instance.turn_on()

        if ATTR_BRIGHTNESS in kwargs and len(kwargs) == 1:
            # Only brightness changed
            await self._instance.set_brightness(kwargs[ATTR_BRIGHTNESS])

        if ATTR_RGB_COLOR in kwargs:
            if kwargs[ATTR_RGB_COLOR] != self.rgb_color:
                self._effect = None
                bri = (
                    kwargs[ATTR_BRIGHTNESS]
                    if ATTR_BRIGHTNESS in kwargs
                    else self._instance.brightness
                )
                await self._instance.set_rgb_color(kwargs[ATTR_RGB_COLOR], bri)

        if ATTR_EFFECT in kwargs:
            if kwargs[ATTR_EFFECT] != self.effect:
                self._effect = kwargs[ATTR_EFFECT]
                bri = (
                    kwargs[ATTR_BRIGHTNESS]
                    if ATTR_BRIGHTNESS in kwargs
                    else self._instance.brightness
                )
                await self._instance.set_effect(kwargs[ATTR_EFFECT], bri)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._instance.turn_off()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the entity."""
        LOGGER.debug("async update called")
        await self._instance.update()
        self.async_write_ha_state()

    def light_local_callback(self):
        """Perform the callback."""
        self.async_write_ha_state()

    async def update_ha_state(self) -> None:
        """Update HA state."""
        await self._instance.update()
        self.async_write_ha_state()
