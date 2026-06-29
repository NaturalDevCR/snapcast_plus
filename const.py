"""Constants for Snapcast."""

from homeassistant.const import Platform

DOMAIN = "snapcast"
DEFAULT_TITLE = "Snapcast"

CLIENT_PREFIX = "snapcast_client_"
CLIENT_SUFFIX = "Snapcast Client"
LATENCY_SUFFIX = "Latency"

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER, Platform.SENSOR]
