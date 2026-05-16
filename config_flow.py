import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN, PROTOCOLS, DEFAULT_POLLING_MINUTES, SENSOR_TYPES

PHOTO_METHODS = {
    "extended_message": "1. Plaintext Extended Message (SIA-DC-03)",
    "ajax_v": "2. Ajax 'V' Method (Dedicated Block)",
    "modern_url": "3. Modern Multi-Media URL (SIA-DC-09-2021)"
}

class AlarmoSiaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title=user_input.get("cms_name", "Primary CMS"), data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("cms_name", default="Primary CMS"): str,
                vol.Required("host"): str,
                vol.Required("port", default=1234): int,
                vol.Required("protocol", default="TCP"): vol.In(PROTOCOLS),
                vol.Optional("receiver_number", default="1"): str,
                vol.Required("account_id"): str,
                vol.Optional("key"): str,
                vol.Optional("starting_sequence", default=1): int,
                vol.Required("polling_interval", default=DEFAULT_POLLING_MINUTES): int,
            })
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return AlarmoSiaOptionsFlow(config_entry)

class AlarmoSiaOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            # Clean up empty strings or None values so they don't linger in the dictionary
            cleaned_input = {k: v for k, v in user_input.items() if v not in [None, ""]}
            return self.async_create_entry(title="", data=cleaned_input)

        opt = self._config_entry.options
        conf = self._config_entry.data

        # Helper function to grab current value from options, falling back to initial config data
        def get_current(key, fallback=None):
            return opt.get(key, conf.get(key, fallback))

        schema_dict = {
            # 1. PRIMARY CMS SETTINGS
            vol.Required("cms_name", description={"suggested_value": get_current("cms_name", "Primary CMS")}): str,
            vol.Required("host", description={"suggested_value": get_current("host", "")}): str,
            vol.Required("port", description={"suggested_value": get_current("port", 1234)}): int,
            vol.Required("protocol", description={"suggested_value": get_current("protocol", "TCP")}): vol.In(PROTOCOLS),
            
            # 2. SECONDARY FAILOVER SETTINGS
            vol.Optional("secondary_host", description={"suggested_value": get_current("secondary_host")}): str,
            vol.Optional("secondary_port", description={"suggested_value": get_current("secondary_port")}): int,
            vol.Optional("secondary_protocol", description={"suggested_value": get_current("secondary_protocol")}): vol.In(PROTOCOLS),
            
            # 3. ACCOUNT & TIMEOUTS
            vol.Optional("receiver_number", description={"suggested_value": get_current("receiver_number")}): str,
            vol.Required("account_id", description={"suggested_value": get_current("account_id", "")}): str,
            vol.Optional("key", description={"suggested_value": get_current("key")}): str,
            vol.Required("polling_interval", description={"suggested_value": get_current("polling_interval", 30)}): int,
            vol.Required("max_retries", description={"suggested_value": get_current("max_retries", 3)}): int,
            vol.Required("retry_timeout", description={"suggested_value": get_current("retry_timeout", 20)}): int,
            
            # 4. ALARM PANEL SETTINGS
            vol.Required("alarm_entity", description={"suggested_value": get_current("alarm_entity", "alarm_control_panel.alarmo")}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="alarm_control_panel")
            ),
            vol.Required("enable_op_cl", description={"suggested_value": get_current("enable_op_cl", False)}): bool,
            
            # 5. PHOTO VERIFICATION SETTINGS
            vol.Required("enable_photos", description={"suggested_value": get_current("enable_photos", False)}): bool,
            vol.Required("photo_method", description={"suggested_value": get_current("photo_method", "extended_message")}): vol.In(PHOTO_METHODS),
            vol.Optional("base_url", description={"suggested_value": get_current("base_url")}): str,
            vol.Optional("camera_entity", description={"suggested_value": get_current("camera_entity", [])}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="camera", multiple=True)
            ),

            # 6. AC POWER MONITORING (Defaults removed from get_current)
            vol.Optional("ac_binary_sensor", description={"suggested_value": get_current("ac_binary_sensor")}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional("ac_numeric_sensor", description={"suggested_value": get_current("ac_numeric_sensor")}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            ),
            vol.Optional("ac_string_sensor", description={"suggested_value": get_current("ac_string_sensor")}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional("ac_threshold", description={"suggested_value": get_current("ac_threshold")}): vol.Coerce(float),
            vol.Optional("ac_grace_period", description={"suggested_value": get_current("ac_grace_period")}): int,

            # 7. TAMPER MONITORING
            vol.Optional("tamper_sensors", description={"suggested_value": get_current("tamper_sensors", [])}): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),

            # 8. OFFLINE SENSOR MONITORING
            vol.Optional("offline_sensors", description={"suggested_value": get_current("offline_sensors", [])}): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
            vol.Optional("offline_grace_period", description={"suggested_value": get_current("offline_grace_period")}): int,
        }

        # 9. MANUAL SENSOR TYPE MAPPING
        for key in SENSOR_TYPES.keys():
            schema_dict[vol.Optional(key, description={"suggested_value": get_current(key, [])})] = selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            )

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))