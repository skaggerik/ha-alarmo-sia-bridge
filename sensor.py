from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .const import DOMAIN

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the SIA sensors."""
    async_add_entities([
        SiaHistorySensor(hass, config_entry),
        SiaSequenceSensor(hass, config_entry)
    ])

class SiaHistorySensor(SensorEntity):
    """Diagnostic sensor for SIA traffic and routing history."""
    
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._attr_name = f"{entry.title} SIA History"
        self._attr_unique_id = f"{entry.entry_id}_sia_history"
        self._attr_icon = "mdi:shield-sync"

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
        """Return the unencrypted Tx, Rx, and Routing Status."""
        history = self.hass.data[DOMAIN][self.entry.entry_id].get("history")
        if not history:
            return "Idle (No traffic logged)"
            
        last = history[0]
        # Format: Tx: [Packet] -> Rx: [Reply] | Status
        state_str = f"Tx: {last['full_packet']} -> Rx: {last['reply']} | {last['status']}"
        
        # HA caps states at 255 characters. Truncate cleanly if CMS returns massive DUH responses.
        return state_str[:255]

    @property
    def extra_state_attributes(self):
        """Return the rolling log of 50 events including raw packets."""
        history = self.hass.data[DOMAIN][self.entry.entry_id].get("history", [])
        return {
            "total_sent": len(history),
            "events": list(history)
        }

class SiaSequenceSensor(SensorEntity):
    """Tracks the exact sequence number of the last transmitted packet."""
    
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._attr_name = f"{entry.title} Last Sequence"
        self._attr_unique_id = f"{entry.entry_id}_sia_sequence"
        self._attr_icon = "mdi:counter"

    async def async_added_to_hass(self):
        """Register dispatcher to update sequence immediately on send."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, 
                f"{DOMAIN}_{self.entry.entry_id}_event_added", 
                self.async_write_ha_state
            )
        )

    @property
    def state(self):
        """Return the precise sequence number appended to the last packet."""
        return self.hass.data[DOMAIN][self.entry.entry_id].get("last_seq", "None")