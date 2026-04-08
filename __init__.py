import logging
import asyncio
import os
import uuid
import socket
from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from pysiaalarm import SIAAccount

from .const import DOMAIN, SIA_MAPPING, SENSOR_TYPES, RESTORE_MAP

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry):
    conf = entry.data
    options = entry.options
    
    snapshot_path = hass.config.path("www/sia_snapshots")
    if not os.path.exists(snapshot_path):
        await hass.async_add_executor_job(os.makedirs, snapshot_path)

    account = SIAAccount(conf["account_id"], key=conf.get("key"))
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {
        "seq": 1,
        "active_alarms": set() 
    })

    def create_sia_packet(code, zone, message="", url=""):
        now = datetime.now(timezone.utc).strftime("%H:%M:%S,%m-%d-%Y")
        seq = str(hass.data[DOMAIN][entry.entry_id]["seq"]).zfill(4)
        hass.data[DOMAIN][entry.entry_id]["seq"] = (hass.data[DOMAIN][entry.entry_id]["seq"] % 9999) + 1

        clean_msg = message.replace(' ', '_').replace('/', '_').replace('[', '').replace(']', '')
        
        # Safely assemble the extended data string with multiple URLs if present
        extended_data = ""
        if clean_msg and url:
            extended_data = f"^{clean_msg}|{url}"
        elif clean_msg:
            extended_data = f"^{clean_msg}"
        elif url:
            extended_data = f"^{url}"
            
        data_block = f"[#{account.account_id}|Nri{zone}/{code}{extended_data}]"
        
        content = f"\"SIA-DCS\"{seq}L0#{account.account_id}{data_block}_{now}"
        content_len = hex(len(content))[2:].zfill(4).upper()
        
        crc = 0x0000
        for byte in content.encode('ascii'):
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        crc_str = hex(crc)[2:].zfill(4).upper()
        
        return f"\n{crc_str}{content_len}{content}\r".encode('ascii')

    def _send_udp_sync(packet, host, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(packet, (host, port))
        sock.close()

    async def send_event(code, zone=1, message="", url=""):
        packet = create_sia_packet(code, zone, message, url)
        host = conf["host"]
        port = conf["port"]
        
        try:
            if conf.get("protocol", "TCP") == "UDP":
                await hass.async_add_executor_job(_send_udp_sync, packet, host, port)
            else:
                reader, writer = await asyncio.open_connection(host, port)
                writer.write(packet)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
            _LOGGER.info(f"SIA Sent {code} to {host}:{port}")
        except Exception as e:
            _LOGGER.error(f"Failed to send SIA event: {e}")

    async def handle_polling(now):
        await send_event("RP", 0, "Heartbeat")

    async def alarmo_listener(event):
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        
        if not new_state or not old_state:
            return

        if old_state.state == new_state.state:
            return

        current_options = entry.options
        mem = hass.data[DOMAIN][entry.entry_id]

        if current_options.get("enable_op_cl"):
            if new_state.state == "disarmed" and old_state.state != "disarmed":
                await send_event("OP", zone=1, message="System_Disarmed")
                await asyncio.sleep(0.5)
            elif new_state.state.startswith("armed_") and not old_state.state.startswith("armed_"):
                await send_event("CL", zone=1, message=f"System_{new_state.state}")
                await asyncio.sleep(0.5)

        if old_state.state == "triggered" and new_state.state != "triggered":
            for trigger_code in mem["active_alarms"]:
                restore_code = RESTORE_MAP.get(trigger_code, "BC") 
                await send_event(restore_code, zone=1, message="Alarm_Restored")
                await asyncio.sleep(0.5) 
            
            if new_state.state == "disarmed":
                await send_event("BC", zone=1, message="Alarm_Cancelled")
            
            mem["active_alarms"].clear()
            return

        if new_state.state == "triggered":
            open_sensors_attr = new_state.attributes.get("open_sensors")
            sensors = []
            if isinstance(open_sensors_attr, dict):
                sensors = list(open_sensors_attr.keys())
            elif isinstance(open_sensors_attr, list):
                sensors = open_sensors_attr
                
            if not sensors:
                mem["active_alarms"].add("BA")
                await send_event("BA", zone=1, message="Panel_Triggered")
                return

            for sensor_id in sensors:
                sia_code = "BA" 
                
                sensor_obj = hass.states.get(sensor_id)
                friendly_name = sensor_obj.attributes.get("friendly_name", sensor_id) if sensor_obj else sensor_id
                
                for option_key, mapped_code in SENSOR_TYPES.items():
                    if sensor_id in current_options.get(option_key, []):
                        sia_code = mapped_code
                        break
                else:
                    d_class = sensor_obj.attributes.get("device_class", "safety") if sensor_obj else "safety"
                    sia_code = SIA_MAPPING.get(d_class, "BA")
                
                mem["active_alarms"].add(sia_code)
                
                msg = f"{friendly_name}"
                photo_url_string = ""

                # --- FEATURE: MULTI-CAMERA LOGIC ---
                cameras = current_options.get("camera_entity", [])
                if isinstance(cameras, str): # Backward compatibility
                    cameras = [cameras]

                if current_options.get("enable_photos") and cameras:
                    urls = []
                    for cam_id in cameras:
                        img_name = f"{uuid.uuid4().hex}.jpg"
                        img_path = f"{snapshot_path}/{img_name}"
                        
                        # Command HA to take a snapshot for each camera
                        await hass.services.async_call("camera", "snapshot", {"entity_id": cam_id, "filename": img_path})
                        
                        base = current_options.get('base_url', '').rstrip('/')
                        urls.append(f"Url:{base}/local/sia_snapshots/{img_name}")
                    
                    # Wait once for all camera files to finish writing
                    await asyncio.sleep(2)
                    photo_url_string = "|".join(urls)

                await send_event(sia_code, zone=1, message=msg, url=photo_url_string)

    unsub_interval = async_track_time_interval(
        hass, handle_polling, timedelta(minutes=conf.get("polling_interval", 30))
    )
    
    target_alarm = options.get("alarm_entity") or "alarm_control_panel.alarmo"
    unsub_event = async_track_state_change_event(hass, target_alarm, alarmo_listener)
    unsub_update = entry.add_update_listener(update_listener)
    
    hass.data[DOMAIN][entry.entry_id]["unsub_interval"] = unsub_interval
    hass.data[DOMAIN][entry.entry_id]["unsub_event"] = unsub_event
    hass.data[DOMAIN][entry.entry_id]["unsub_update"] = unsub_update

    return True

async def update_listener(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass, entry):
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    for key in ["unsub_interval", "unsub_event", "unsub_update"]:
        if key in data and callable(data[key]):
            data[key]()
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True