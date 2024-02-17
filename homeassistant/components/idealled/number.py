"""The number entities."""
import logging

from homeassistant.components.number import NumberEntity
from homeassistant.components.number.const import NumberDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .idealled import IDEALLEDInstance

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the relevent number entities to HA."""
    instance = hass.data[DOMAIN][config_entry.entry_id]
    await instance.update()
    async_add_entities(
        [
            IDEALLEDSpeedNumber(
                instance,
                config_entry.data["name"] + " Effect Speed",
                config_entry.entry_id + "_effect_speed",
            )
        ]
    )
    # config_entry.async_on_unload(await instance.stop())


class IDEALLEDSpeedNumber(
    NumberEntity
):  # TODO: Implement RestoreNumber https://developers.home-assistant.io/docs/core/entity/number
    """An entity to store the speed of the effect."""

    def __init__(
        self, idealledinstance: IDEALLEDInstance, name: str, entry_id: str
    ) -> None:
        """Initialise this number."""
        self._instance = idealledinstance
        self._entry_id = entry_id
        self._attr_name = name
        self._attr_unique_id = self._instance.mac + "_effect_speed"

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
    def device_class(self) -> NumberDeviceClass:
        """The device class of this number entity."""
        return NumberDeviceClass.SPEED

    @property
    def available(self) -> bool:
        """Whether this entity is available."""
        return self._instance.is_on is not None

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        return self._instance.effect_speed

    # default native max/min of 100/0 is fine

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        intspeed = max(min(int(value), 100), 0)
        await self._instance.set_speed(intspeed)

    async def async_update(self) -> None:
        """Update the number."""
        LOGGER.debug("async update called")
        await self._instance.update()
        self.async_write_ha_state()

    def light_local_callback(self):
        """Write HA state."""
        self.async_write_ha_state()

    async def update_ha_state(self) -> None:
        """Update HA state."""
        await self._instance.update()
        self.async_write_ha_state()
