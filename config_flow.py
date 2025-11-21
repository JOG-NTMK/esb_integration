"""Config flow for ESB Integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN


class ESBConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ESB Integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Here you would validate the credentials
            # For now, we'll just accept any input

            # Create a unique ID based on the MPRN
            await self.async_set_unique_id(user_input["mprn"])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"ESB {user_input['mprn']}",
                data=user_input
            )

        data_schema = vol.Schema(
            {
                vol.Required("mprn"): str,
                vol.Required("email"): str,
                vol.Required("password"): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )