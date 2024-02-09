"""Exceptions."""

from enum import Enum, IntEnum, auto

from bleak.exc import BleakError
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS as BLEAK_EXCEPTIONS


class DisconnectReason(Enum):
    """Disconnect reason."""

    ERROR = auto()
    INVALID_COMMAND = auto()
    LOCK_REQUESTED = auto()
    TIMEOUT = auto()
    UNEXPECTED = auto()
    USER_REQUESTED = auto()


class ErrorCode(IntEnum):
    """Error code."""

    SUCCESS = 0
    UNKNOWN_CMD = 1
    NOT_AUTHENTICATED = 2
    AUTHENTICATION_FAILED = 3
    WRONG_PIN = 4
    NO_AVAILABLE_KEYS = 5
    FLASH_WRITE_FAILED = 6
    MAX_ADMINS = 7
    MAX_PENDING_KEYS = 8
    MAX_KEY_FOBS_PENDING = 9
    WRONG_STATE = 10
    INC_PREPARE = 12
    REPEAT = 13
    PARAM_NOT_SUPPORTED = 14


class iDealLedError(Exception):
    """Base class for exceptions."""


class CommandFailed(iDealLedError):
    """Raised when the lock rejects a command."""

    def __init__(self, error: ErrorCode):
        """Init."""
        self.error = error
        super().__init__(error.name)


class Disconnected(iDealLedError):
    """Raised when the connection is lost."""

    def __init__(self, reason: DisconnectReason):
        """Init."""
        self.reason = reason
        super().__init__(reason.name)


class InvalidCommand(iDealLedError):
    """Raised when a received command can't be parsed."""


class InvalidActivationCode(iDealLedError):
    """Raised when trying to associate with an invalid activation code."""


class NotAssociated(iDealLedError):
    """Raised when not associated."""


class NotAuthenticated(iDealLedError):
    """Raised when trying to execute a command which requires authentication."""


class NotConnected(iDealLedError):
    """Raised when connection is lost while sending a command."""


class Timeout(BleakError, iDealLedError):
    """Raised when trying to associate with wrong activation code."""


class UnsupportedProtocolVersion(iDealLedError):
    """Unsupported protocol version."""


class WrongActivationCode(iDealLedError):
    """Raised when trying to associate with wrong activation code."""


IDEALLED_EXCEPTIONS = (
    *BLEAK_EXCEPTIONS,
    CommandFailed,
    Disconnected,
    InvalidCommand,
)
