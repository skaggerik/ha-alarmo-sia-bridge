DOMAIN = "alarmo_sia_bridge"
PROTOCOLS = ["TCP", "UDP"]
DEFAULT_POLLING_MINUTES = 30

# UI Configuration Keys to SIA Trigger Codes
SENSOR_TYPES = {
    "fire_sensors": "FA",
    "gas_sensors": "GA",
    "holdup_sensors": "HA",
    "heat_sensors": "KA",
    "medical_sensors": "MA",
    "panic_sensors": "PA",
    "water_sensors": "WA"
}

# Mapping Triggers to their proper Restore Codes
RESTORE_MAP = {
    "FA": "FH", # Fire Restore
    "GA": "GH", # Gas Restore
    "HA": "HH", # Holdup Restore
    "KA": "KH", # Heat Restore
    "MA": "MH", # Medical Restore
    "PA": "PH", # Panic Restore
    "WA": "WH", # Water Restore
    "BA": "BH"  # Burglary Restore
}

# Fallbacks for HA device classes if not manually mapped
SIA_MAPPING = {
    "moisture": "WA",
    "smoke": "FA",
    "gas": "GA",
    "safety": "BA",
    "door": "BA",
    "window": "BA",
    "motion": "BA",
}