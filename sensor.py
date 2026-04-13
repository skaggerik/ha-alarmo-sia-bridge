from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .const import DOMAIN

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the SIA History Sensor."""
    async_add_entities([SiaHistorySensor(hass, config_entry)])

class SiaHistorySensor(SensorEntity):
    """Diagnostic sensor for SIA traffic history."""
    
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._attr_name = f"{entry.title} SIA History"
        self._attr_unique_id = f"{entry.entry_id}_sia_history"
        self._attr_icon = "mdi:history"

    async def async_added_to_hass(self):
        """Register dispatcher for real-time history updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, 
                f"{DOMAIN}_{self.entry.entry_id}_event_added", 
                self.async_write_ha_state
            )
        )

    @property
    def state(self):
        """Return the unencrypted raw string of the most recent transmission."""
        history = self.hass.data[DOMAIN][self.entry.entry_id].get("history")
        if not history:
            return "Idle (No traffic)"
        return history[0]["full_packet"]

    @property
    def extra_state_attributes(self):
        """Return the rolling log of 50 events."""
        history = self.hass.data[DOMAIN][self.entry.entry_id].get("history", [])
        return {
            "total_sent": len(history),
            "events": list(history)
        }