"""The CF-EMC Energy integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .api import CFEMCApi
from .const import DOMAIN, CONF_BACKFILL_DAYS, CONF_MEMBER_NUMBER, CONF_ACCOUNT_NUMBER
from .coordinator import EMCDataCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CF-EMC Energy from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api = CFEMCApi(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        member_number=entry.data[CONF_MEMBER_NUMBER],
        account_number=entry.data[CONF_ACCOUNT_NUMBER],
    )

    backfill_days = entry.options.get(
        CONF_BACKFILL_DAYS,
        entry.data.get(CONF_BACKFILL_DAYS, 7),
    )

    coordinator = EMCDataCoordinator(
        hass,
        api=api,
        backfill_days=backfill_days,
    )

    # Fetch initial data so we have it when platforms are set up
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload entry when options change
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
