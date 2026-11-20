"""Config flow for SchoolZone News."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import SchoolZoneAuthError, SchoolZoneClient, SchoolZoneError
from .const import (
    CONF_EVENING_TIME,
    CONF_MORNING_TIME,
    CONF_NEWS_TYPES,
    DEFAULT_EVENING_TIME,
    DEFAULT_MORNING_TIME,
    DEFAULT_NEWS_TYPES,
    DOMAIN,
    NEWS_TYPES,
)

CREDS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


def _options_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_NEWS_TYPES, default=defaults.get(CONF_NEWS_TYPES, DEFAULT_NEWS_TYPES)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=k, label=v) for k, v in NEWS_TYPES.items()
                    ],
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(
                CONF_MORNING_TIME,
                default=defaults.get(CONF_MORNING_TIME, DEFAULT_MORNING_TIME),
            ): selector.TimeSelector(),
            vol.Required(
                CONF_EVENING_TIME,
                default=defaults.get(CONF_EVENING_TIME, DEFAULT_EVENING_TIME),
            ): selector.TimeSelector(),
        }
    )


async def _validate(hass, username: str, password: str) -> str | None:
    """Return an error key, or None if the credentials work."""
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    try:
        client = SchoolZoneClient(session, username, password)
        await client.login()
        await client.fetch_news("school")
    except SchoolZoneAuthError:
        return "invalid_auth"
    except SchoolZoneError:
        return "cannot_connect"
    finally:
        await session.close()
    return None


class SchoolZoneConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._creds: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            error = await _validate(self.hass, username, user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                self._creds = {CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                return await self.async_step_streams()
        return self.async_show_form(step_id="user", data_schema=CREDS_SCHEMA, errors=errors)

    async def async_step_streams(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            if not user_input[CONF_NEWS_TYPES]:
                return self.async_show_form(
                    step_id="streams",
                    data_schema=_options_schema({}),
                    errors={"base": "no_streams"},
                )
            return self.async_create_entry(
                title=f"SchoolZone ({self._creds[CONF_USERNAME]})",
                data=self._creds,
                options=user_input,
            )
        return self.async_show_form(step_id="streams", data_schema=_options_schema({}))

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            error = await _validate(self.hass, entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SchoolZoneOptionsFlow()


class SchoolZoneOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_NEWS_TYPES]:
                errors["base"] = "no_streams"
            else:
                return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self.config_entry.options),
            errors=errors,
        )
