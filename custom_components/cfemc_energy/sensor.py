"""Sensor platform for the CF-EMC Energy integration."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .coordinator import EMCDataCoordinator
from .const import DOMAIN, CONF_NAME

SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="yesterday_total_kwh",
        name="Yesterday's Total Usage",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:flash",
    ),
    SensorEntityDescription(
        key="last_successful_update",
        name="Last Successful Update",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:update",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor entities from a config entry."""
    coordinator: EMCDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = [
        CfemcEnergySensor(coordinator, description, entry)
        for description in SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)


class CfemcEnergySensor(CoordinatorEntity[EMCDataCoordinator], RestoreEntity, SensorEntity):
    """Represents a CF-EMC Energy sensor that can restore its state."""

    def __init__(
        self,
        coordinator: EMCDataCoordinator,
        description: SensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.data[CONF_NAME],
            "manufacturer": "CF-EMC (Unofficial)",
        }
        self._restored_state: State | None = None

    async def async_added_to_hass(self) -> None:
        """Handle entity which provides non-async data."""
        await super().async_added_to_hass()
        # Restore the last known state
        if (last_state := await self.async_get_last_state()) is not None:
            self._restored_state = last_state

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor, falling back to the restored state."""
        # Prioritize fresh data from the coordinator for the usage sensor
        if self.entity_description.key == "yesterday_total_kwh":
            if self.coordinator.data:
                total_usage = sum(item['usage'] for item in self.coordinator.data)
                return round(total_usage, 2)
            # If coordinator has no data (e.g., after restart), use the restored state
            if self._restored_state and self._restored_state.state not in ("unknown", "unavailable"):
                return self._restored_state.state
            return None

        # Prioritize fresh data from the coordinator for the timestamp sensor
        if self.entity_description.key == "last_successful_update":
            if self.coordinator.last_successful_run_timestamp:
                return self.coordinator.last_successful_run_timestamp
            # If coordinator has no data, parse the restored state back into a datetime object
            if self._restored_state and self._restored_state.state not in ("unknown", "unavailable"):
                try:
                    return dt_util.parse_datetime(self._restored_state.state)
                except (TypeError, ValueError):
                    return None
            return None
            
        return None

