import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN, PROTOCOLS, DEFAULT_POLLING_MINUTES, SENSOR_TYPES

class AlarmoSiaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            cms_name = user_input.get("cms_name", "SIA Bridge")
            return self.async_create_entry(title=cms_name, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("cms_name", default="Primary CMS"): str,
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
        conf = self._config_entry.data
        schema_dict = {}

        # 1. NETWORK & CMS SETTINGS
        schema_dict[vol.Required("cms_name", default=opt.get("cms_name", conf.get("cms_name", "Primary CMS")))] = str
        schema_dict[vol.Required("host", default=opt.get("host", conf.get("host", "")))] = str
        schema_dict[vol.Required("port", default=opt.get("port", conf.get("port", 1234)))] = int
        schema_dict[vol.Required("protocol", default=opt.get("protocol", conf.get("protocol", "TCP")))] = vol.In(PROTOCOLS)
        
        # --- NEW: Account ID and Key exposed to the Options Menu ---
        schema_dict[vol.Required("account_id", default=opt.get("account_id", conf.get("account_id", "")))] = str
        
        current_key = opt.get("key", conf.get("key"))
        if current_key:
            schema_dict[vol.Optional("key", default=current_key)] = str
        else:
            schema_dict[vol.Optional("key")] = str

        schema_dict[vol.Required("polling_interval", default=opt.get("polling_interval", conf.get("polling_interval", 30)))] = int
        
        # 2. ALARM PANEL SETTINGS
        alarm_ent = opt.get("alarm_entity") or "alarm_control_panel.alarmo"
        schema_dict[vol.Required("alarm_entity", default=alarm_ent)] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="alarm_control_panel")
        )
        schema_dict[vol.Required("enable_op_cl", default=opt.get("enable_op_cl", False))] = bool
        
        # 3. AC POWER MONITORING
        ac_bin = opt.get("ac_binary_sensor")
        if ac_bin:
            schema_dict[vol.Optional("ac_binary_sensor", default=ac_bin)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            )
        else:
            schema_dict[vol.Optional("ac_binary_sensor")] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            )

        ac_num = opt.get("ac_numeric_sensor")
        if ac_num:
            schema_dict[vol.Optional("ac_numeric_sensor", default=ac_num)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            )
        else:
            schema_dict[vol.Optional("ac_numeric_sensor")] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            )
            
        schema_dict[vol.Optional("ac_threshold", default=opt.get("ac_threshold", 0.0))] = vol.Coerce(float)
        schema_dict[vol.Required("ac_grace_period", default=opt.get("ac_grace_period", 60))] = int

        # 4. OFFLINE SENSOR MONITORING
        monitored = opt.get("offline_sensors", [])
        if not isinstance(monitored, list):
            monitored = []
        schema_dict[vol.Optional("offline_sensors", default=monitored)] = selector.EntitySelector(
            selector.EntitySelectorConfig(multiple=True)
        )
        schema_dict[vol.Required("offline_grace_period", default=opt.get("offline_grace_period", 300))] = int

        # 5. PHOTO VERIFICATION
        schema_dict[vol.Required("enable_photos", default=opt.get("enable_photos", False))] = bool
        schema_dict[vol.Optional("base_url", default=opt.get("base_url", ""))] = str
        
        cam_ent = opt.get("camera_entity", [])
        if not isinstance(cam_ent, list):
            cam_ent = [cam_ent] if cam_ent else []

        schema_dict[vol.Optional("camera_entity", default=cam_ent)] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="camera", multiple=True)
        )

        # 6. MANUAL SENSOR MAPPING
        for key in SENSOR_TYPES.keys():
            val = opt.get(key, [])
            if not isinstance(val, list):
                val = []
            schema_dict[vol.Optional(key, default=val)] = selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            )

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))