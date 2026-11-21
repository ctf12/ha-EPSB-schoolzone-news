"""Coordinator for SchoolZone News.

Checks SchoolZone at two fixed times a day (default 07:00 and 17:00, Home
Assistant's local time) instead of polling on an interval. The last result is
cached on disk so a Home Assistant restart doesn't trigger an extra check,
unless a scheduled check was missed while Home Assistant was down.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Announcement, SchoolZoneAuthError, SchoolZoneClient, SchoolZoneError
from .const import (
    CONF_EVENING_TIME,
    CONF_MORNING_TIME,
    CONF_NEWS_TYPES,
    DEFAULT_EVENING_TIME,
    DEFAULT_MORNING_TIME,
    DEFAULT_NEWS_TYPES,
    DOMAIN,
    EVENT_NEW_ANNOUNCEMENT,
    MAX_RETRIES,
    MAX_SEEN_IDS,
    NEWS_TYPES,
    RETRY_DELAY_MIN,
    STORAGE_VERSION,
    store_key,
)

_LOGGER = logging.getLogger(__name__)


def _parse_time(value: str, fallback: str) -> time:
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        return time.fromisoformat(fallback)


class SchoolZoneCoordinator(DataUpdateCoordinator[dict[str, list[Announcement]]]):
    """Fetches every configured news stream and fires events for new posts."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: SchoolZoneClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,  # fixed-time schedule, see async_start_schedule
        )
        self.client = client
        self.news_types: list[str] = list(entry.options.get(CONF_NEWS_TYPES, DEFAULT_NEWS_TYPES))
        self.check_times: list[time] = sorted(
            {
                _parse_time(entry.options.get(CONF_MORNING_TIME), DEFAULT_MORNING_TIME),
                _parse_time(entry.options.get(CONF_EVENING_TIME), DEFAULT_EVENING_TIME),
            }
        )
        self.last_checked: datetime | None = None
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, store_key(entry.entry_id))
        self._seen: dict[str, set[str]] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._retry_unsub: CALLBACK_TYPE | None = None
        self._retries_left = MAX_RETRIES

    # ---------- startup / cache ----------

    async def async_load_cache(self) -> bool:
        """Load seen ids and cached posts. Return True if the cache is current.

        Current means it was fetched after the most recent scheduled check time
        and covers every configured stream.
        """
        stored = await self._store.async_load() or {}
        self._seen = {k: set(v) for k, v in stored.get("seen", {}).items()}

        items = stored.get("items") or {}
        fetched_at = dt_util.parse_datetime(stored.get("fetched_at") or "")
        if not fetched_at or any(t not in items for t in self.news_types):
            return False
        try:
            data = {
                t: [Announcement.from_storage(a) for a in items[t]] for t in self.news_types
            }
        except (TypeError, KeyError):
            _LOGGER.debug("Ignoring unreadable SchoolZone cache")
            return False

        self.data = data
        self.last_checked = fetched_at
        return fetched_at >= self._last_scheduled_slot()

    def _last_scheduled_slot(self) -> datetime:
        now = dt_util.now()
        slots = []
        for t in self.check_times:
            slot = now.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
            if slot > now:
                slot -= timedelta(days=1)
            slots.append(slot)
        return max(slots)

    # ---------- schedule ----------

    @callback
    def async_start_schedule(self) -> None:
        for t in self.check_times:
            self._unsubs.append(
                async_track_time_change(
                    self.hass, self._scheduled_check, hour=t.hour, minute=t.minute, second=t.second
                )
            )

    @callback
    def async_stop_schedule(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_retry()

    @callback
    def _cancel_retry(self) -> None:
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None

    @callback
    def _scheduled_check(self, _now: datetime) -> None:
        self._cancel_retry()
        self._retries_left = MAX_RETRIES
        self.hass.async_create_task(self.async_refresh(), eager_start=True)

    @callback
    def _retry_check(self, _now: datetime) -> None:
        self._retry_unsub = None
        self.hass.async_create_task(self.async_refresh(), eager_start=True)

    # ---------- fetching ----------

    async def _async_update_data(self) -> dict[str, list[Announcement]]:
        result: dict[str, list[Announcement]] = {}
        try:
            # Checks are hours apart, so any session held from the last one has
            # almost certainly expired. Sign in fresh once per check rather than
            # guessing; fetch_news still recovers if the session drops mid-check.
            await self.client.login()
            for news_type in self.news_types:
                result[news_type] = await self.client.fetch_news(news_type)
        except SchoolZoneAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SchoolZoneError as err:
            self._schedule_retry()
            raise UpdateFailed(str(err)) from err

        self._cancel_retry()
        self._retries_left = MAX_RETRIES
        self.last_checked = dt_util.now()
        self._fire_new_item_events(result)
        await self._store.async_save(
            {
                "seen": {k: sorted(v, key=_id_key) for k, v in self._seen.items()},
                "items": {k: [a.to_storage() for a in v] for k, v in result.items()},
                "fetched_at": self.last_checked.isoformat(),
            }
        )
        return result

    @callback
    def _schedule_retry(self) -> None:
        if self._retry_unsub or self._retries_left <= 0 or not self._unsubs:
            return
        self._retries_left -= 1
        _LOGGER.info("SchoolZone check failed; retrying in %s minutes", RETRY_DELAY_MIN)
        self._retry_unsub = async_call_later(
            self.hass, timedelta(minutes=RETRY_DELAY_MIN), self._retry_check
        )

    @callback
    def _fire_new_item_events(self, result: dict[str, list[Announcement]]) -> None:
        for news_type, items in result.items():
            first_time = news_type not in self._seen
            seen = self._seen.setdefault(news_type, set())
            new_items = [a for a in items if a.id not in seen]
            # The first load of a stream only records what's there; announcing
            # every existing post would flood notifications.
            if not first_time:
                for item in sorted(new_items, key=lambda a: a.sort_key):
                    data = item.as_dict()
                    # Body HTML can be large and events are written to the
                    # recorder database; plain text and links are enough.
                    data.pop("html", None)
                    self.hass.bus.async_fire(
                        EVENT_NEW_ANNOUNCEMENT,
                        {
                            "news_type": news_type,
                            "news_type_name": NEWS_TYPES.get(news_type, news_type),
                            **data,
                        },
                    )
            seen.update(a.id for a in items)
            if len(seen) > MAX_SEEN_IDS:
                self._seen[news_type] = set(sorted(seen, key=_id_key)[-MAX_SEEN_IDS:])


def _id_key(value: str) -> tuple[int, str]:
    return (int(value), value) if value.isdigit() else (-1, value)
