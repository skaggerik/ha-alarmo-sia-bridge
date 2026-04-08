import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN, PROTOCOLS, DEFAULT_POLLING_MINUTES, SENSOR_TYPES

class AlarmoSiaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title=f"SIA Bridge ({user_input['host']})", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("host"): str,
                vol.Required("port", default=1234): int,
                vol.Required("protocol", default="TCP"): vol.In(PROTOCOLS),
                vol.Required("account_id"): str,
                vol.Optional("key"): str,
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
            return self.async_create_entry(title="", data=user_input)

        opt = self._config_entry.options
        schema_dict = {}
        
        # 1. Target Alarm Panel
        alarm_ent = opt.get("alarm_entity") or "alarm_control_panel.alarmo"
        schema_dict[vol.Required("alarm_entity", default=alarm_ent)] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="alarm_control_panel")
        )
        
        # 2. General Settings
        schema_dict[vol.Required("enable_op_cl", default=opt.get("enable_op_cl", False))] = bool
        schema_dict[vol.Required("enable_photos", default=opt.get("enable_photos", False))] = bool
        schema_dict[vol.Optional("base_url", default=opt.get("base_url", ""))] = str
        
        # FEATURE: Allow multiple cameras
        # Backward compatibility check for users upgrading from single-camera setup
        cam_ent = opt.get("camera_entity", [])
        if not isinstance(cam_ent, list):
            cam_ent = [cam_ent] if cam_ent else []

        schema_dict[vol.Optional("camera_entity", default=cam_ent)] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="camera", multiple=True)
        )

        # 3. Dynamic Sensor Mapping
        for key in SENSOR_TYPES.keys():
            val = opt.get(key, [])
            if not isinstance(val, list):
                val = []
            schema_dict[vol.Optional(key, default=val)] = selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            )

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))