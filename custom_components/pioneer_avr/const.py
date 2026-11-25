"""Constants for the Pioneer AVR integration."""

from __future__ import annotations

DOMAIN = "pioneer_avr"

CONF_PORT = "port"
CONF_ASSUME_OFF_WHEN_UNAVAILABLE = "assume_off_when_unavailable"
CONF_VOLUME_MAX_RAW = "volume_max_raw"
CONF_VOLUME_MIN_RAW = "volume_min_raw"
CONF_MAX_VOLUME_RAW = "max_volume_raw"
CONF_PAUSE_MINUTES = "pause_minutes"
CONF_VOLUME_STEP_DB = "volume_step_db"

DEFAULT_NAME = "Pioneer VSX-827"
DEFAULT_PORT = 8102
DEFAULT_TIMEOUT = 5.0
DEFAULT_SCAN_INTERVAL = 30

MANUFACTURER = "Pioneer"
MODEL = "VSX-827"

VOLUME_MIN = 0
VOLUME_MAX = 161

DEFAULT_ASSUME_OFF_WHEN_UNAVAILABLE = True

# Option value for "no maximum volume".
MAX_VOLUME_NONE = "none"
# Selectable maximum volume in dB (Pioneer mapping: dB = (raw - 161) / 2).
MAX_VOLUME_DB_CHOICES = range(-60, 1)

DEFAULT_VOLUME_STEP_DB = 1
VOLUME_STEP_DB_CHOICES = (1, 2, 3, 5)

DEFAULT_PAUSE_MINUTES = 10
PAUSE_MINUTES_CHOICES = (5, 10, 15, 30, 60)


def raw_to_db(raw: int) -> float:
    """Convert a raw Pioneer volume value to dB."""
    return (raw - VOLUME_MAX) / 2


def db_to_raw(db: float) -> int:
    """Convert dB to a raw Pioneer volume value."""
    return round(VOLUME_MAX + db * 2)


def max_volume_option(raw: int) -> str:
    """Selector key for a maximum volume (translation keys cannot start with -)."""
    return f"raw_{raw}"


def max_volume_options() -> list[str]:
    """Selector keys from 0 dB down to -60 dB in 1 dB steps."""
    return [max_volume_option(db_to_raw(db)) for db in reversed(MAX_VOLUME_DB_CHOICES)]


def parse_max_volume_option(value: str) -> int | None:
    """Return the raw maximum volume for a selector key, or None for no limit."""
    if value == MAX_VOLUME_NONE:
        return None
    return int(value.removeprefix("raw_"))


# Source codes documented for the VSX-1022/VSX-822 2012 protocol family and
# observed by existing VSX-827 users. A receiver may report only a subset.
SOURCES: dict[str, str] = {
    "01": "CD",
    "02": "Tuner",
    "04": "DVD",
    "05": "TV",
    "06": "SAT/CBL",
    "10": "Video",
    "15": "DVR/BDR",
    "17": "iPod/USB",
    "25": "BD",
    "33": "Adapter Port",
    "38": "Internet Radio",
    "41": "Pandora",
    "44": "Media Server",
    "45": "Favorites",
    "46": "AirPlay",
    "47": "DMR",
    "49": "Game",
}

SOURCE_CODES = {name: code for code, name in SOURCES.items()}

# VSX-827 ControlApp/2012 protocol listening-mode button groups. These select
# or cycle a group; the receiver does not report the current mode via TCP.
SOUND_MODE_COMMANDS: dict[str, str] = {
    "Auto / Direct": "0005SR",
    "Standard / ALC": "0010SR",
    "Advanced Surround": "0100SR",
}
