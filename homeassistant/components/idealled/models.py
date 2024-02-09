"""The iDealLED integration models."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import inspect
import logging

from .iDealLed import iDealLed

_LOGGER = logging.getLogger(__name__)


class BaseProcedure(ABC):
    """Base class for procedures."""

    enable_notifications: bool = False
    need_auth: bool = False

    def __init__(self, lock: iDealLed) -> None:
        """Initialize."""
        self._lock = lock

    @abstractmethod
    async def execute(self) -> bool:
        """Execute the procedure."""


class NullProcedure(BaseProcedure):
    """Do nothing."""

    enable_notifications = True
    need_auth = False

    async def execute(self) -> bool:
        """Execute the procedure."""
        _LOGGER.debug(
            "%s.%s",
            self.__class__.__name__,
            inspect.currentframe().f_code.co_name,
        )
        return True


@dataclass
class DeviceInfo:
    """Device info."""

    device_id: str | None = None
    device_name: str | None = None
    sw_version: str | None = None
