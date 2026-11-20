"""Shared entity helpers."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN, NEWS_PAGE


def device_info(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name="SchoolZone",
        manufacturer="Edmonton Public Schools",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=f"{NEWS_PAGE}?type=school",
    )
