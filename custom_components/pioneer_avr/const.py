"""Constants for the Pioneer AVR integration."""

from __future__ import annotations

DOMAIN = "pioneer_avr"

CONF_PORT = "port"
CONF_ASSUME_OFF_WHEN_UNAVAILABLE = "assume_off_when_unavailable"
CONF_CALIBRATE_VOLUME = "calibrate_volume"
CONF_VOLUME_MAX_RAW = "volume_max_raw"
CONF_VOLUME_MIN_RAW = "volume_min_raw"

DEFAULT_NAME = "Pioneer VSX-827"
DEFAULT_PORT = 8102
DEFAULT_TIMEOUT = 5.0
DEFAULT_SCAN_INTERVAL = 30

MANUFACTURER = "Pioneer"
MODEL = "VSX-827"

VOLUME_MIN = 0
VOLUME_MAX = 161

DEFAULT_ASSUME_OFF_WHEN_UNAVAILABLE = True

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
