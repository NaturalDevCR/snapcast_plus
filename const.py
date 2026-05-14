"""Constants for Snapcast."""

from homeassistant.const import Platform

DOMAIN = "snapcast_plus"
DEFAULT_TITLE = "Snapcast"

CLIENT_PREFIX = f"{DOMAIN}_client_"
CLIENT_SUFFIX = "Snapcast Client"
LATENCY_SUFFIX = "Latency"

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER, Platform.SENSOR]
