"""Config flow: paste an integration key from the SI portal."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import SIApiError, SIAuthError, async_connect
from .const import (
    CONF_API_KEY,
    CONF_TRANSPORT,
    DOMAIN,
    KEY_PAGE_URL,
    KEY_PREFIX,
    TRANSPORT_TCP,
    TRANSPORT_WS,
)

KEY_SCHEMA = vol.Schema(
    {vol.Required(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
)


class SIConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, key: str) -> tuple[dict[str, str], Any]:
        key = key.strip()
        if not key.startswith(KEY_PREFIX):
            return {CONF_API_KEY: "not_a_key"}, None
        try:
            info = await async_connect(self.hass, key)
        except SIAuthError:
            return {CONF_API_KEY: "invalid_auth"}, None
        except SIApiError:
            return {"base": "cannot_connect"}, None
        return {}, info

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            errors, info = await self._validate(key)
            if not errors:
                await self.async_set_unique_id(info.key_id)
                self._abort_if_unique_id_configured()
                plants = ", ".join(info.plants.values()) or "no plants"
                return self.async_create_entry(
                    title=f"{info.label} ({plants})",
                    data={CONF_API_KEY: key},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=KEY_SCHEMA,
            errors=errors,
            description_placeholders={"key_url": KEY_PAGE_URL},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            errors, info = await self._validate(key)
            if not errors:
                # A new key is a new broker account and possibly a different
                # set of plants; the entry follows the new key.
                entry = self._get_reauth_entry()
                return self.async_update_reload_and_abort(
                    entry, unique_id=info.key_id, data={CONF_API_KEY: key}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=KEY_SCHEMA,
            errors=errors,
            description_placeholders={"key_url": KEY_PAGE_URL},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SIOptionsFlow()


class SIOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_TRANSPORT, TRANSPORT_TCP)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TRANSPORT, default=current): SelectSelector(
                        SelectSelectorConfig(
                            options=[TRANSPORT_TCP, TRANSPORT_WS],
                            mode=SelectSelectorMode.LIST,
                            translation_key=CONF_TRANSPORT,
                        )
                    )
                }
            ),
        )
