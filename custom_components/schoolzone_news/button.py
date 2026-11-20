"""'Check now' button for an on-demand SchoolZone check."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SchoolZoneConfigEntry
from .coordinator import SchoolZoneCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchoolZoneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([SchoolZoneCheckNowButton(entry.runtime_data, entry.entry_id)])


class SchoolZoneCheckNowButton(CoordinatorEntity[SchoolZoneCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Check now"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: SchoolZoneCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_check_now"
        self._attr_device_info = device_info(entry_id)

    @property
    def available(self) -> bool:
        # Pressing it is how you recover from a failed check, so never grey it out.
        return True

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
