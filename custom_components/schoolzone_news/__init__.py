"""SchoolZone News: Edmonton Public Schools SchoolZone announcements in Home Assistant."""

from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store

from .api import SchoolZoneClient
from .const import STORAGE_VERSION, store_key
from .coordinator import SchoolZoneCoordinator

PLATFORMS = [Platform.BUTTON, Platform.SENSOR]

type SchoolZoneConfigEntry = ConfigEntry[SchoolZoneCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SchoolZoneConfigEntry) -> bool:
    # Own cookie jar so the SchoolZone sign-in never mixes with HA's shared session.
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    entry.async_on_unload(session.close)

    client = SchoolZoneClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = SchoolZoneCoordinator(hass, entry, client)

    cache_is_current = await coordinator.async_load_cache()
    if coordinator.data is None:
        # Nothing cached yet (first install or new stream): fetch now. A failure
        # here raises ConfigEntryNotReady and HA retries setup with backoff.
        await coordinator.async_config_entry_first_refresh()
        coordinator.async_start_schedule()
    else:
        coordinator.async_start_schedule()
        if not cache_is_current:
            # A scheduled check was missed while HA was down; catch up once.
            # On failure the cached posts stay in place and a retry is queued.
            await coordinator.async_refresh()

    entry.async_on_unload(coordinator.async_stop_schedule)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: SchoolZoneConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SchoolZoneConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: SchoolZoneConfigEntry) -> None:
    await Store(hass, STORAGE_VERSION, store_key(entry.entry_id)).async_remove()
