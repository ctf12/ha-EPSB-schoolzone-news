"""Sensors: one per SchoolZone news stream."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SchoolZoneConfigEntry
from .api import Announcement
from .const import MAX_ITEMS_IN_ATTRIBUTES, NEWS_PAGE, NEWS_TYPES
from .coordinator import SchoolZoneCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchoolZoneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        SchoolZoneNewsSensor(coordinator, entry.entry_id, news_type)
        for news_type in coordinator.news_types
    )


class SchoolZoneNewsSensor(CoordinatorEntity[SchoolZoneCoordinator], SensorEntity):
    """State = title of the newest post; attributes = recent posts."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:school"
    # Full post bodies are large; keep them out of the recorder database.
    _unrecorded_attributes = frozenset({"announcements", "latest_text"})

    def __init__(self, coordinator: SchoolZoneCoordinator, entry_id: str, news_type: str) -> None:
        super().__init__(coordinator)
        self._news_type = news_type
        self._attr_unique_id = f"{entry_id}_{news_type}_news"
        self._attr_name = f"{NEWS_TYPES.get(news_type, news_type)} news"
        self._attr_device_info = device_info(entry_id)

    @property
    def _items(self) -> list[Announcement]:
        return (self.coordinator.data or {}).get(self._news_type, [])

    @property
    def available(self) -> bool:
        # Checks only run twice a day; keep showing the last good posts if a
        # check fails. `last_check_ok` tells you when that happened.
        return self._news_type in (self.coordinator.data or {})

    @property
    def native_value(self) -> str | None:
        items = self._items
        if not items:
            return "No announcements"
        return items[0].title[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        items = self._items
        latest = items[0] if items else None
        last = self.coordinator.last_checked
        return {
            "news_type": self._news_type,
            "count": len(items),
            "new_count": sum(1 for a in items if a.is_new),
            "latest_id": latest.id if latest else None,
            "latest_posted": latest.posted if latest else None,
            "latest_text": latest.text if latest else None,
            "last_checked": last.isoformat() if last else None,
            "last_check_ok": self.coordinator.last_update_success,
            "check_times": [t.strftime("%H:%M") for t in self.coordinator.check_times],
            "page_url": f"{NEWS_PAGE}?type={self._news_type}",
            "announcements": [
                {
                    "id": a.id,
                    "title": a.title,
                    "posted": a.posted,
                    "pinned": a.pinned,
                    "new": a.is_new,
                    "text": a.text,
                    "links": a.links,
                    "attachments": [{"name": x.name, "url": x.url} for x in a.attachments],
                }
                for a in items[:MAX_ITEMS_IN_ATTRIBUTES]
            ],
        }
