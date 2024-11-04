"""The iDealLED device."""
import asyncio
from collections.abc import Callable
import logging
import traceback
from typing import Any, TypeVar, cast

from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTCharacteristic, BleakGATTServiceCollection
from bleak.exc import BleakDBusError
from bleak_retry_connector import (
    BLEAK_RETRY_EXCEPTIONS as BLEAK_EXCEPTIONS,
    BleakClientWithServiceCache,
    BleakNotFoundError,
    establish_connection,
)
from Crypto.Cipher import AES

# from datetime import datetime
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

# Add effects information in a separate file because there is a LOT of boilerplate.

LOGGER = logging.getLogger(__name__)

EFFECT_01 = "Effect 01"
EFFECT_02 = "Effect 02"
EFFECT_03 = "Effect 03"
EFFECT_04 = "Effect 04"
EFFECT_05 = "Effect 05"
EFFECT_06 = "Effect 06"
EFFECT_07 = "Effect 07"
EFFECT_08 = "Effect 08"
EFFECT_09 = "Effect 09"  # What's up with this one?
EFFECT_10 = "Effect 10"
EFFECT_11 = "Effect 11"
EFFECT_MICROPHONE = "Microphone"

EFFECT_MAP = {
    EFFECT_01: 1,
    EFFECT_02: 2,
    EFFECT_03: 3,
    EFFECT_04: 4,
    EFFECT_05: 5,
    EFFECT_06: 6,
    EFFECT_07: 7,
    EFFECT_08: 8,
    EFFECT_09: 9,
    EFFECT_10: 10,
    EFFECT_11: 11,
    EFFECT_MICROPHONE: 12,
}

EFFECT_LIST = sorted(EFFECT_MAP)
EFFECT_ID_NAME = {v: k for k, v in EFFECT_MAP.items()}

NAME_ARRAY = ["IDL-"]
WRITE_CMD_CHARACTERISTIC_UUIDS = ["d44bc439-abfd-45a2-b575-925416129600"]
WRITE_COL_CHARACTERISTIC_UUIDS = ["d44bc439-abfd-45a2-b575-92541612960a"]
NOTIFY_CHARACTERISTIC_UUIDS = ["d44bc439-abfd-45a2-b575-925416129601"]
SECRET_ENCRYPTION_KEY = bytes(
    [
        0x34,
        0x52,
        0x2A,
        0x5B,
        0x7A,
        0x6E,
        0x49,
        0x2C,
        0x08,
        0x09,
        0x0A,
        0x9D,
        0x8D,
        0x2A,
        0x23,
        0xF8,
    ]
)


DEFAULT_ATTEMPTS = 3
BLEAK_BACKOFF_TIME = 0.25
RETRY_BACKOFF_EXCEPTIONS = BleakDBusError

WrapFuncType = TypeVar("WrapFuncType", bound=Callable[..., Any])


def bytearray_to_hex_format(byte_array):
    """Convert a byte array to a hex string."""
    hex_strings = [f"{byte:02x}" for byte in byte_array]
    return hex_strings


def retry_bluetooth_connection_error(func: WrapFuncType) -> WrapFuncType:
    """Retry the given function upon a bluetooth error."""

    async def _async_wrap_retry_bluetooth_connection_error(
        self: "IDEALLEDInstance", *args: Any, **kwargs: Any
    ) -> Any:
        """Perform the retry."""
        attempts = DEFAULT_ATTEMPTS
        max_attempts = attempts - 1

        for attempt in range(attempts):
            try:
                return await func(self, *args, **kwargs)
            except BleakNotFoundError:
                # The lock cannot be found so there is no
                # point in retrying.
                raise
            except RETRY_BACKOFF_EXCEPTIONS as err:
                if attempt >= max_attempts:
                    LOGGER.debug(
                        "%s: %s error calling %s, reach max attempts (%s/%s)",
                        self.name,
                        type(err),
                        func,
                        attempt,
                        max_attempts,
                        exc_info=True,
                    )
                    raise
                LOGGER.debug(
                    "%s: %s error calling %s, backing off %ss, retrying (%s/%s)",
                    self.name,
                    type(err),
                    func,
                    BLEAK_BACKOFF_TIME,
                    attempt,
                    max_attempts,
                    exc_info=True,
                )
                await asyncio.sleep(BLEAK_BACKOFF_TIME)
            except BLEAK_EXCEPTIONS as err:
                if attempt >= max_attempts:
                    LOGGER.debug(
                        "%s: %s error calling %s, reach max attempts (%s/%s): %s",
                        self.name,
                        type(err),
                        func,
                        attempt,
                        max_attempts,
                        err,
                        exc_info=True,
                    )
                    raise
                LOGGER.debug(
                    "%s: %s error calling %s, retrying  (%s/%s)...: %s",
                    self.name,
                    type(err),
                    func,
                    attempt,
                    max_attempts,
                    err,
                    exc_info=True,
                )

    return cast(WrapFuncType, _async_wrap_retry_bluetooth_connection_error)


class IDEALLEDInstance:
    """A class representing the iDeal LED device."""

    def __init__(self, address, reset: bool, delay: int, hass: HomeAssistant) -> None:
        """Initialise the class."""
        self._startmiccommand = bytearray(
            [6, 77, 73, 67, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        )
        self._stopmiccommand = bytearray(
            [6, 77, 73, 67, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        )
        self._usingmic = False

        self.loop = asyncio.get_running_loop()
        self._mac = address
        self._reset = reset
        self._delay = delay
        self._hass = hass
        self._device: BLEDevice | None = None
        self._device = bluetooth.async_ble_device_from_address(self._hass, address)
        if not self._device:
            raise ConfigEntryNotReady(
                f"You need to add bluetooth integration (https://www.home-assistant.io/integrations/bluetooth) or couldn't find a nearby device with address: {address}"
            )
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._client: BleakClientWithServiceCache | None = None
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._cached_services: BleakGATTServiceCollection | None = None
        self._expected_disconnect = False
        self._is_on = None
        self._rgb_color = (255, 255, 255)
        self._brightness = 255
        self._effect = None
        self._effect_speed = 0x64
        self._write_uuid = None
        self._write_colour_uuid = None
        self._read_uuid = None
        self._turn_on_cmd = None
        self._turn_off_cmd = None
        self._model = self._detect_model()
        self._on_update_callbacks = []
        self._notification_callback = None
        self._disconnecttask = None
        self._effect_colors = [
            (0, 255, 0),
            (128, 255, 0),
            (255, 255, 0),
            (255, 0, 0),
            (255, 0, 255),
            (0, 0, 255),
            (128, 0, 255),
        ]

        LOGGER.debug(
            "Model information for device %s : ModelNo %s. MAC: %s",
            self._device.name,
            self._model,
            self._mac,
        )

    def _detect_model(self):
        x = 0
        for name in NAME_ARRAY:
            if self._device.name.lower().startswith(name.lower()):
                return x
            x = x + 1

    async def _write(self, data: bytearray):
        """Send command to device and read response."""
        await self._ensure_connected()
        cipher = AES.new(SECRET_ENCRYPTION_KEY, AES.MODE_ECB)
        ciphered_data = cipher.encrypt(data)
        LOGGER.debug("Writing data to %s: %s", self.name, bytearray_to_hex_format(data))
        LOGGER.debug(
            "Writing encrypted data to %s: %s",
            self.name,
            bytearray_to_hex_format(ciphered_data),
        )
        await self._write_while_connected(ciphered_data)

    async def _write_colour_data(self, data: bytearray):
        """Send command to device and read response."""
        await self._ensure_connected()
        await self._write_colour_while_connected(data)

    async def _write_while_connected(self, data: bytearray):
        await self._client.write_gatt_char(self._write_uuid, data, False)

    async def _write_colour_while_connected(self, data: bytearray):
        LOGGER.debug(
            "Writing colour data to %s: %s", self.name, bytearray_to_hex_format(data)
        )
        await self._client.write_gatt_char(self._write_colour_uuid, data, False)

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        # This doesn't work.  I can't get the controller to send notifications.
        """Handle BLE notifications from the device.  Update internal state to reflect the device state."""
        cipher = AES.new(SECRET_ENCRYPTION_KEY, AES.MODE_ECB)
        clear_data = cipher.decrypt(data)
        LOGGER.debug(
            "BLE Notification: %s: %s", self.name, bytearray_to_hex_format(clear_data)
        )
        # self.local_callback()

    @property
    def mac(self):
        """The device's mac address."""
        return self._device.address

    @property
    def reset(self):
        """Whether this device is reset."""
        return self._reset

    @property
    def name(self):
        """The name of this device."""
        return self._device.name

    @property
    def rssi(self):
        """The rssi of this device."""
        return self._device.rssi

    @property
    def is_on(self):
        """Whether this device is on."""
        return self._is_on

    @property
    def brightness(self):
        """The brightness of this device."""
        return self._brightness

    @property
    def effect_speed(self):
        """The brightness of this device."""
        return self._effect_speed

    @property
    def rgb_color(self):
        """The colour of this device, when set to a single colour."""
        return self._rgb_color

    @property
    def effect_list(self) -> list[str]:
        """The list of effects supported by this device."""
        return EFFECT_LIST

    @property
    def effect(self):
        """The current effect."""
        return self._effect

    def effect_colour(self, index: int):
        """Get the effect colour at the given index."""
        return self._effect_colors[index]

    async def set_effect_colour(self, index: int, colour):
        """Set the effect colour at the given index."""
        self._effect_colors[index] = colour
        # if an effect (that's not the microphone) is happening then set that effect again to update the colours
        if (
            self._effect is not None
            and self._effect != EFFECT_MICROPHONE
            and self.is_on
        ):
            await self.set_effect(self._effect, self._brightness)

    async def set_speed(self, speed: int):
        """Set the effect speed of this device."""
        speed = min(speed, 100)
        if speed == self._effect_speed:
            return
        self._effect_speed = speed
        packet = bytearray([6, 83, 80, 69, 69, 68, speed, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        await self._write(packet)

    async def set_brightness(self, brightness: int):
        """Set the brightness of this device."""
        brightness = min(brightness, 255)
        if brightness == self._brightness:
            return
        self._brightness = brightness
        brightness_percent = int(brightness * 100 / 255)
        packet = bytearray(
            [
                6,
                76,
                73,
                71,
                72,
                84,
                max(3, brightness_percent),
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ]
        )
        await self._write(packet)

    @retry_bluetooth_connection_error
    async def set_rgb_color(
        self, rgb: tuple[int, int, int], brightness: int | None = None
    ):
        """Set the colour of this device."""
        if self._usingmic:
            self._usingmic = False
            await self._write(self._stopmiccommand)

        if None in rgb:
            rgb = self._rgb_color
        self._rgb_color = rgb
        self._effect = None
        if brightness is None:
            if self._brightness is None:
                self._brightness = 255
            else:
                brightness = self._brightness
        brightness_percent = int(brightness * 100 / 255)
        # Now adjust the RBG values to match the brightness
        red = int(rgb[0] * brightness_percent / 100)
        green = int(rgb[1] * brightness_percent / 100)
        blue = int(rgb[2] * brightness_percent / 100)

        # You CAN send 8 bit colours to this thing, but you probably shouldn't for power reasons.  Thanks to the good folks at Hacker News for that insight. (used to shift 3, now just 1)
        red = int(red >> 1)
        green = int(green >> 1)
        blue = int(blue >> 1)
        rgb_packet = bytearray(
            [7, 67, 79, 76, 79, green, red, blue, 0, 0, 0, 0, 0, 0, 0, 0]
        )
        await self._write(rgb_packet)

    @retry_bluetooth_connection_error
    # effect, reverse=0, speed=50, saturation=50, colour_data=COLOUR_DATA
    async def set_effect(self, effect: str, brightness: int | None = NotImplemented):
        """Set the effect of this device."""
        if effect not in EFFECT_LIST:
            LOGGER.error("Effect %s not supported", effect)
            return
        self._effect = effect

        if effect == EFFECT_MICROPHONE:
            self._usingmic = True
            await self._write(self._startmiccommand)
            return

        effect_id = EFFECT_MAP.get(effect)
        effect_id = min(
            effect_id, 11
        )  # IMPORTANT, ENSURE NO EFFECT ID MORE THAN 11 IS CHOSEN SINCE THAT MAY BRICK THE DEVICE
        brightness_pct = int(brightness * 100 / 255)
        # (14, 69, 70, 70) = effect header | effect id | 7 colours | colour array index? | the colours (g,r,b)
        packet = bytearray(
            [
                14,
                69,
                70,
                70,
                effect_id,
                7,
                3,
                int(int(self._effect_colors[0][1] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[0][0] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[0][2] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[1][1] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[1][0] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[1][2] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[2][1] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[2][0] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[2][2] * brightness_pct / 100) >> 1),
            ]
        )
        await self._write(packet)
        packet = bytearray(
            [
                14,
                69,
                70,
                70,
                effect_id,
                7,
                19,
                int(int(self._effect_colors[3][1] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[3][0] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[3][2] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[4][1] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[4][0] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[4][2] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[5][1] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[5][0] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[5][2] * brightness_pct / 100) >> 1),
            ]
        )
        await self._write(packet)
        packet = bytearray(
            [
                14,
                69,
                70,
                70,
                effect_id,
                7,
                33,
                int(int(self._effect_colors[6][1] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[6][0] * brightness_pct / 100) >> 1),
                int(int(self._effect_colors[6][2] * brightness_pct / 100) >> 1),
                0,
                0,
                0,
                0,
                0,
                0,
            ]
        )
        await self._write(packet)

    @retry_bluetooth_connection_error
    async def turn_on(self):
        """Turn on this device."""
        packet = bytearray([6, 76, 69, 68, 79, 78, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        await self._write(packet)
        self._is_on = True
        if self._usingmic:
            await self._write(self._startmiccommand)

    @retry_bluetooth_connection_error
    async def turn_off(self):
        """Turn off this device."""
        if self._usingmic:
            # Stop the mic, but say we're still ising it so it starts it again when we turn back on
            await self._write(self._stopmiccommand)
        packet = bytearray([6, 76, 69, 68, 79, 70, 70, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        await self._write(packet)
        self._is_on = False

    @retry_bluetooth_connection_error
    async def update(self):
        """Update this device."""
        LOGGER.debug("%s: Update in lwdnetwf called", self.name)
        try:
            await self._ensure_connected()
            self._is_on = True  # Assume on
        except Exception as error:
            self._is_on = None  # failed to connect, this should mark it as unavailable
            LOGGER.error("Error getting status: %s", error)
            track = traceback.format_exc()
            LOGGER.debug(track)

    async def _ensure_connected(self) -> None:
        """Ensure connection to device is established."""
        if self._connect_lock.locked():
            LOGGER.debug(
                "%s: Connection already in progress, waiting for it to complete",
                self.name,
            )
        if self._client and self._client.is_connected:
            self._reset_disconnect_timer()
            return
        async with self._connect_lock:
            # Check again while holding the lock
            if self._client and self._client.is_connected:
                self._reset_disconnect_timer()
                return
            LOGGER.debug("%s: Connecting", self.name)
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._device,
                self.name,
                self._disconnected,
                cached_services=self._cached_services,
                ble_device_callback=lambda: self._device,
            )
            LOGGER.debug("%s: Connected", self.name)
            resolved = self._resolve_characteristics(client.services)
            if not resolved:
                # Try to handle services failing to load
                resolved = self._resolve_characteristics(await client.get_services())
            self._cached_services = client.services if resolved else None

            self._client = client
            self._reset_disconnect_timer()

            # Subscribe to notification is needed for LEDnetWF devices to accept commands
            self._notification_callback = self._notification_handler
            await client.start_notify(self._read_uuid, self._notification_callback)
            LOGGER.debug("%s: Subscribed to notifications", self.name)

    def _resolve_characteristics(self, services: BleakGATTServiceCollection) -> bool:
        """Resolve characteristics."""
        for characteristic in NOTIFY_CHARACTERISTIC_UUIDS:
            if char := services.get_characteristic(characteristic):
                self._read_uuid = char
                LOGGER.debug("%s: Read UUID: %s", self.name, self._read_uuid)
                break
        for characteristic in WRITE_CMD_CHARACTERISTIC_UUIDS:
            if char := services.get_characteristic(characteristic):
                self._write_uuid = char
                LOGGER.debug("%s: Write UUID: %s", self.name, self._write_uuid)
                break
        for characteristic in WRITE_COL_CHARACTERISTIC_UUIDS:
            if char := services.get_characteristic(characteristic):
                self._write_colour_uuid = char
                LOGGER.debug(
                    "%s: Write colour UUID: %s", self.name, self._write_colour_uuid
                )
                break
        return bool(self._read_uuid and self._write_uuid and self._write_colour_uuid)

    def _reset_disconnect_timer(self) -> None:
        """Reset disconnect timer."""
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
        self._expected_disconnect = False
        if self._delay is not None and self._delay != 0:
            LOGGER.debug(
                "%s: Configured disconnect from device in %s seconds",
                self.name,
                self._delay,
            )
            self._disconnect_timer = self.loop.call_later(self._delay, self._disconnect)

    def _disconnected(self, client: BleakClientWithServiceCache) -> None:
        """Disconnected callback."""
        if self._expected_disconnect:
            LOGGER.debug("%s: Disconnected from device", self.name)
            return
        LOGGER.warning("%s: Device unexpectedly disconnected", self.name)

    def _disconnect(self) -> None:
        """Disconnect from device."""
        self._disconnect_timer = None
        self._disconnecttask = asyncio.create_task(self._execute_timed_disconnect())

    async def stop(self) -> None:
        """Stop the LEDBLE."""
        LOGGER.debug("%s: Stop", self.name)
        await self._execute_disconnect()

    async def _execute_timed_disconnect(self) -> None:
        """Execute timed disconnection."""
        LOGGER.debug("%s: Disconnecting after timeout of %s", self.name, self._delay)
        await self._execute_disconnect()

    async def _execute_disconnect(self) -> None:
        """Execute disconnection."""
        async with self._connect_lock:
            read_char = self._read_uuid
            client = self._client
            self._expected_disconnect = True
            self._client = None
            self._write_uuid = None
            self._read_uuid = None
            if client and client.is_connected:
                await client.stop_notify(read_char)
                await client.disconnect()
            LOGGER.debug("%s: Disconnected", self.name)

    def local_callback(self):
        """Just return for now."""
        # Placeholder to be replaced by a call from light.py
        # I can't work out how to plumb a callback from here to light.py
        return
