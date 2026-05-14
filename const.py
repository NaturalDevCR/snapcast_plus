"""Constants for Snapcast."""

from homeassistant.const import Platform

DOMAIN = "snapcast_plus"
DEFAULT_TITLE = "Snapcast"

CLIENT_PREFIX = "snapcast_client_"
CLIENT_SUFFIX = "Snapcast Client"

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]
