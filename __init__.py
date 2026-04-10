import logging
import asyncio
import os
import uuid
import socket
import json
from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval, async_call_later
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import area_registry as ar
from pysiaalarm import SIAAccount

from .const import DOMAIN, SIA_MAPPING, SENSOR_TYPES, RESTORE_MAP

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry):
    merged_conf = {**entry.data, **entry.options}
    
    cms_name = merged_conf.get("cms_name", "Primary CMS")
    if entry.title != cms_name:
        hass.config_entries.async_update_entry(entry, title=cms_name)
    
    snapshot_path = hass.config.path("www/sia_snapshots")
    if not os.path.exists(snapshot_path):
        await hass.async_add_executor_job(os.makedirs, snapshot_path)

    account = SIAAccount(merged_conf["account_id"], key=merged_conf.get("key"))
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {
        "seq": 1,
        "active_alarms": set(), # Stores tuples: (sia_code, friendly_name)
        "ac_trouble": False,
        "timers": {},
        "offline_sensors": set()
    })

    # --- CORE SIA SENDER ---
    def create_sia_packet(code, zone, message="", url=""):
        now = datetime.now(timezone.utc).strftime("%H:%M:%S,%m-%d-%Y")
        seq = str(hass.data[DOMAIN][entry.entry_id]["seq"]).zfill(4)
        hass.data[DOMAIN][entry.entry_id]["seq"] = (hass.data[DOMAIN][entry.entry_id]["seq"] % 9999) + 1

        clean_msg = message.replace(' ', '_').replace('/', '_').replace('[', '').replace(']', '')
        
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
        host = merged_conf["host"]
        port = merged_conf["port"]
        
        try:
            if merged_conf.get("protocol", "TCP") == "UDP":
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

    # --- LISTENERS ---
    # FIX: allow 'now' to be None so we can trigger it manually on boot
    async def handle_polling(now=None):
        await send_event("RP", 0, "Heartbeat")

    async def ac_listener(event):
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        
        if not new_state or not old_state or old_state.state == new_state.state:
            return

        mem = hass.data[DOMAIN][entry.entry_id]
        timers = mem["timers"]
        
        is_trouble = False
        if entity_id == merged_conf.get("ac_binary_sensor"):
            sensor_obj = hass.states.get(entity_id)
            d_class = sensor_obj.attributes.get("device_class") if sensor_obj else None
            is_trouble = (new_state.state == "on") if d_class in ["problem", "battery"] else (new_state.state == "off")
        elif entity_id == merged_conf.get("ac_numeric_sensor"):
            try:
                is_trouble = float(new_state.state) < float(merged_conf.get("ac_threshold", 0))
            except ValueError:
                return

        delay = merged_conf.get("ac_grace_period", 60)

        async def fire_ac_trouble(now):
            mem["ac_trouble"] = True
            await send_event("AT", zone=0, message="AC_Power_Lost")

        async def fire_ac_restore(now):
            mem["ac_trouble"] = False
            await send_event("AR", zone=0, message="AC_Power_Restored")

        if "ac" in timers:
            timers["ac"]()
            timers.pop("ac")

        if is_trouble and not mem["ac_trouble"]:
            timers["ac"] = async_call_later(hass, delay, fire_ac_trouble)
        elif not is_trouble and mem["ac_trouble"]:
            timers["ac"] = async_call_later(hass, delay, fire_ac_restore)

    async def offline_listener(event):
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        
        if not new_state or not old_state:
            return

        mem = hass.data[DOMAIN][entry.entry_id]
        timers = mem["timers"]
        
        is_unavail = new_state.state in ["unavailable", "unknown"]
        was_unavail = old_state.state in ["unavailable", "unknown"]

        if is_unavail == was_unavail:
            return

        delay = merged_conf.get("offline_grace_period", 300)
        timer_key = f"offline_{entity_id}"
        
        sensor_obj = hass.states.get(entity_id)
        friendly_name = sensor_obj.attributes.get("friendly_name", entity_id) if sensor_obj else entity_id

        async def fire_offline(now):
            mem["offline_sensors"].add(entity_id)
            await send_event("UT", zone=1, message=f"Offline_{friendly_name}")

        async def fire_online(now):
            mem["offline_sensors"].discard(entity_id)
            await send_event("UH", zone=1, message=f"Restored_{friendly_name}")

        if timer_key in timers:
            timers[timer_key]()
            timers.pop(timer_key)

        if is_unavail and entity_id not in mem["offline_sensors"]:
            timers[timer_key] = async_call_later(hass, delay, fire_offline)
        elif not is_unavail and entity_id in mem["offline_sensors"]:
            timers[timer_key] = async_call_later(hass, delay, fire_online)

    async def alarmo_listener(event):
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        
        if not new_state or not old_state or old_state.state == new_state.state:
            return

        mem = hass.data[DOMAIN][entry.entry_id]

        if merged_conf.get("enable_op_cl"):
            if new_state.state == "disarmed" and old_state.state != "disarmed":
                await send_event("OP", zone=1, message="System_Disarmed")
                await asyncio.sleep(0.5)
            elif new_state.state.startswith("armed_") and not old_state.state.startswith("armed_"):
                await send_event("CL", zone=1, message=f"System_{new_state.state}")
                await asyncio.sleep(0.5)

        if old_state.state == "triggered" and new_state.state != "triggered":
            for trigger_code, f_name in list(mem["active_alarms"]):
                restore_code = RESTORE_MAP.get(trigger_code, "BC") 
                await send_event(restore_code, zone=1, message=f"Restored_{f_name}")
                await asyncio.sleep(0.5) 
            
            if new_state.state == "disarmed":
                await send_event("BC", zone=1, message="System_Cancelled")
            
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
                mem["active_alarms"].add(("BA", "Panel_Triggered"))
                await send_event("BA", zone=1, message="Panel_Triggered")
                return

            for sensor_id in sensors:
                sia_code = "BA" 
                sensor_obj = hass.states.get(sensor_id)
                friendly_name = sensor_obj.attributes.get("friendly_name", sensor_id) if sensor_obj else sensor_id
                
                for option_key, mapped_code in SENSOR_TYPES.items():
                    if sensor_id in merged_conf.get(option_key, []):
                        sia_code = mapped_code
                        break
                else:
                    d_class = sensor_obj.attributes.get("device_class", "safety") if sensor_obj else "safety"
                    sia_code = SIA_MAPPING.get(d_class, "BA")
                
                mem["active_alarms"].add((sia_code, friendly_name))
                msg = f"{friendly_name}"
                photo_url_string = ""

                cameras = merged_conf.get("camera_entity", [])
                if isinstance(cameras, str): 
                    cameras = [cameras]

                if merged_conf.get("enable_photos") and cameras:
                    urls = []
                    for cam_id in cameras:
                        img_name = f"{uuid.uuid4().hex}.jpg"
                        img_path = f"{snapshot_path}/{img_name}"
                        await hass.services.async_call("camera", "snapshot", {"entity_id": cam_id, "filename": img_path})
                        base = merged_conf.get('base_url', '').rstrip('/')
                        urls.append(f"Url:{base}/local/sia_snapshots/{img_name}")
                    
                    await asyncio.sleep(2)
                    photo_url_string = "|".join(urls)

                await send_event(sia_code, zone=1, message=msg, url=photo_url_string)

    # --- INITIALIZATION SEQUENCE ---
    # 1. Setup the background timer for future polls
    unsub_interval = async_track_time_interval(hass, handle_polling, timedelta(minutes=merged_conf.get("polling_interval", 30)))
    
    # 2. FIX: Immediately fire a heartbeat now that the config is loaded/reloaded
    hass.async_create_task(handle_polling())

    unsub_event = async_track_state_change_event(hass, merged_conf.get("alarm_entity", "alarm_control_panel.alarmo"), alarmo_listener)
    
    ac_entities = [e for e in [merged_conf.get("ac_binary_sensor"), merged_conf.get("ac_numeric_sensor")] if e and isinstance(e, str)]
    unsub_ac = async_track_state_change_event(hass, ac_entities, ac_listener) if ac_entities else None

    offline_entities = merged_conf.get("offline_sensors", [])
    unsub_offline = None
    if offline_entities:
        unsub_offline = async_track_state_change_event(hass, offline_entities, offline_listener)

    unsub_update = entry.add_update_listener(update_listener)
    
    hass.data[DOMAIN][entry.entry_id]["unsub_interval"] = unsub_interval
    hass.data[DOMAIN][entry.entry_id]["unsub_event"] = unsub_event
    hass.data[DOMAIN][entry.entry_id]["unsub_update"] = unsub_update
    if unsub_ac: hass.data[DOMAIN][entry.entry_id]["unsub_ac"] = unsub_ac
    if unsub_offline: hass.data[DOMAIN][entry.entry_id]["unsub_offline"] = unsub_offline

    return True

async def update_listener(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass, entry):
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    
    for key in ["unsub_interval", "unsub_event", "unsub_ac", "unsub_offline", "unsub_update"]:
        if key in data and callable(data[key]):
            data[key]()
            
    for timer_cancel in data.get("timers", {}).values():
        timer_cancel()
        
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True