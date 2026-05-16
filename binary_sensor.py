from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .const import DOMAIN

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the SIA connectivity binary sensor."""
    async_add_entities([SiaConnectionSensor(hass, config_entry)])

class SiaConnectionSensor(BinarySensorEntity):
    """Binary sensor tracking the success of the last SIA transmission."""
    
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._attr_name = f"{entry.title} Connection Status"
        self._attr_unique_id = f"{entry.entry_id}_sia_connection_status"
        # Using 'problem' class: 'On' = Problem, 'Off' = OK
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    async def async_added_to_hass(self):
        """Register dispatcher for real-time updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, 
                f"{DOMAIN}_{self.entry.entry_id}_event_added", 
                self.async_write_ha_state
            )
        )

    @property
    def is_on(self):
        """Return True if there is a problem (no ACK received)."""
        history = self.hass.data[DOMAIN][self.entry.entry_id].get("history")
        
        # If no history yet, assume everything is OK
        if not history:
            return False 
            
        last_event = history[0]
        status = last_event.get("status", "")
        
        # If the last transmission contains an ACK, there is NO problem (return False). 
        # Otherwise, there IS a problem (return True).
        if "ACK" in status:
            return False
            
        return True