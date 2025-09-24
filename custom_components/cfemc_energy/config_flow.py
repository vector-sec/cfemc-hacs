"""Config flow for CF-EMC Energy integration."""
from __future__ import annotations

import voluptuous as vol
from typing import Any
import logging

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_BACKFILL_DAYS,
    CONF_MEMBER_NUMBER,
    CONF_ACCOUNT_NUMBER,
)
from .api import CFEMCApi

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CF-EMC Energy."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api = CFEMCApi(
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                user_input[CONF_MEMBER_NUMBER],
                user_input[CONF_ACCOUNT_NUMBER],
            )

            try:
                authenticated = await self.hass.async_add_executor_job(
                    api.test_credentials
                )
                if authenticated:
                    await self.async_set_unique_id(user_input[CONF_USERNAME])
                    self._abort_if_unique_id_configured()
                    
                    return self.async_create_entry(
                        title=user_input[CONF_NAME], data=user_input
                    )
                else:
                    errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception during authentication")
                errors["base"] = "cannot_connect"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="CF-EMC Energy"): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_MEMBER_NUMBER): str,
                vol.Required(CONF_ACCOUNT_NUMBER): str,
                vol.Optional(CONF_BACKFILL_DAYS, default=7): cv.positive_int,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

