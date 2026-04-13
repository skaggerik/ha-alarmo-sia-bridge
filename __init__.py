import logging
import asyncio
import os
import uuid
import socket
from datetime import datetime, timedelta, timezone
from collections import deque

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval, async_call_later
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pysiaalarm import SIAAccount

from .const import DOMAIN, SIA_MAPPING, SENSOR_TYPES, RESTORE_MAP

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor"]

async def async_setup_entry(hass: HomeAssistant, entry):
    merged_conf = {**entry.data, **entry.options}
    
    account_id = merged_conf.get("account_id", "")
    alarm_entity = merged_conf.get("alarm_entity", "alarm_control_panel.alarmo")
    
    snapshot_path = hass.config.path("www/sia_snapshots")
    if not os.path.exists(snapshot_path):
        await hass.async_add_executor_job(os.makedirs, snapshot_path)

    account = SIAAccount(account_id, key=merged_conf.get("key"))
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {
        "seq": 1,
        "active_alarms": set(), 
        "ac_trouble": False,
        "timers": {},
        "offline_sensors": set(),
        "history": deque(maxlen=50) 
    })

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    def create_sia_packet(code, zone, message="", url=""):
        now = datetime.now(timezone.utc).strftime("%H:%M:%S,%m-%d-%Y")
        seq = str(hass.data[DOMAIN][entry.entry_id]["seq"]).zfill(4)
        hass.data[DOMAIN][entry.entry_id]["seq"] = (hass.data[DOMAIN][entry.entry_id]["seq"] % 9999) + 1

        clean_msg = message.replace(' ', '_').replace('/', '_')
        photo_method = merged_conf.get("photo_method", "extended_message")
        
        if url and photo_method == "extended_message":
            event_block = f"[#{account_id}|Nri{zone}/{code}^{clean_msg}|Url:{url}]"
            multi_block = ""
        else:
            event_block = f"[#{account_id}|Nri{zone}/{code}^{clean_msg}]"
            multi_block = ""
            if url:
                if photo_method == "ajax_v":
                    multi_block = f"[V{url}]"
                elif photo_method == "modern_url":
                    multi_block = f"[#{account_id}|M{url}]"

        rec_num = merged_conf.get("receiver_number", "1")
        header = f"\"SIA-DCS\"{seq}R{rec_num}L0#{account_id}"
        
        readable_content = f"{header}{event_block}{multi_block}_{now}"
        
        content_len = hex(len(readable_content))[2:].zfill(4).upper()
        crc = 0x0000
        for byte in readable_content.encode('ascii'):
            crc ^= byte
            for _ in range(8):
                crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        
        checksum = hex(crc)[2:].zfill(4).upper()
        full_packet_string = f"{checksum}{content_len}{readable_content}"
        
        packet_to_send = f"\n{full_packet_string}\r".encode('ascii')
        return packet_to_send, full_packet_string

    def _send_udp_sync(packet_bytes, host, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(packet_bytes, (host, port))
        sock.close()

    async def send_event(code, zone=1, message="", url=""):
        packet_bytes, readable_string = create_sia_packet(code, zone, message, url)
        host = merged_conf.get("host")
        port = merged_conf.get("port")
        
        if not host or not port:
            _LOGGER.error("SIA Transmission Error: Host or Port is missing.")
            return

        try:
            if merged_conf.get("protocol") == "UDP":
                await hass.async_add_executor_job(_send_udp_sync, packet_bytes, host, port)
            else:
                reader, writer = await asyncio.open_connection(host, port)
                writer.write(packet_bytes)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
            
            event_data = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "code": code,
                "msg": message,
                "full_packet": readable_string
            }
            hass.data[DOMAIN][entry.entry_id]["history"].appendleft(event_data)
            async_dispatcher_send(hass, f"{DOMAIN}_{entry.entry_id}_event_added")
            
        except Exception as e:
            _LOGGER.error(f"SIA Transmission Error: {e}")

    # --- POLLING ---
    async def handle_polling(now=None): 
        await send_event("RP", 0, "Heartbeat")

    # --- ALARMO LISTENER ---
    async def alarmo_listener(event):
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if not new_state or not old_state or old_state.state == new_state.state: return
        
        mem = hass.data[DOMAIN][entry.entry_id]

        if old_state.state == "triggered" and new_state.state != "triggered":
            for trigger_code, f_name in list(mem["active_alarms"]):
                await send_event(RESTORE_MAP.get(trigger_code, "BH"), 1, f"Restored_{f_name}")
                await asyncio.sleep(0.3)
            if new_state.state == "disarmed":
                await send_event("BC", 1, "Alarm_Cancelled")
                await asyncio.sleep(0.3)
            mem["active_alarms"].clear()

        if merged_conf.get("enable_op_cl"):
            if new_state.state == "disarmed": 
                await send_event("OP", 1, "System_Disarmed")
            elif new_state.state.startswith("armed_"): 
                await send_event("CL", 1, f"System_{new_state.state}")

        if new_state.state == "triggered":
            open_sensors = new_state.attributes.get("open_sensors", [])
            if not open_sensors:
                mem["active_alarms"].add(("BA", "Panel"))
                await send_event("BA", 1, "Panel_Triggered")
                return

            sensors = list(open_sensors.keys()) if isinstance(open_sensors, dict) else open_sensors
            for s_id in sensors:
                s_obj = hass.states.get(s_id)
                f_name = s_obj.attributes.get("friendly_name", s_id) if s_obj else s_id
                
                sia_code = "BA"
                for opt_key, mapped_code in SENSOR_TYPES.items():
                    if s_id in merged_conf.get(opt_key, []):
                        sia_code = mapped_code
                        break
                else:
                    d_class = s_obj.attributes.get("device_class", "safety") if s_obj else "safety"
                    sia_code = SIA_MAPPING.get(d_class, "BA")

                mem["active_alarms"].add((sia_code, f_name))
                
                photo_url = ""
                cameras = merged_conf.get("camera_entity", [])
                if merged_conf.get("enable_photos") and cameras:
                    urls = []
                    for cam_id in (cameras if isinstance(cameras, list) else [cameras]):
                        img_name = f"{uuid.uuid4().hex}.jpg"
                        img_path = f"{snapshot_path}/{img_name}"
                        await hass.services.async_call("camera", "snapshot", {"entity_id": cam_id, "filename": img_path})
                        base = merged_conf.get('base_url', '').rstrip('/')
                        urls.append(f"{base}/local/sia_snapshots/{img_name}")
                    await asyncio.sleep(2) 
                    photo_url = ",".join(urls)

                await send_event(sia_code, 1, f_name, url=photo_url)

    # --- AC LISTENER ---
    async def ac_listener(event):
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if not new_state or not old_state or old_state.state == new_state.state: return
        mem = hass.data[DOMAIN][entry.entry_id]
        timers = mem["timers"]
        is_trouble = False
        if entity_id == merged_conf.get("ac_binary_sensor"):
            sensor_obj = hass.states.get(entity_id)
            d_class = sensor_obj.attributes.get("device_class") if sensor_obj else None
            is_trouble = (new_state.state == "on") if d_class in ["problem", "battery"] else (new_state.state == "off")
        elif entity_id == merged_conf.get("ac_numeric_sensor"):
            try: is_trouble = float(new_state.state) < float(merged_conf.get("ac_threshold", 0))
            except ValueError: return

        delay = merged_conf.get("ac_grace_period", 60)
        async def fire_ac_trouble(now):
            mem["ac_trouble"] = True
            await send_event("AT", 0, "AC_Power_Lost")
        async def fire_ac_restore(now):
            mem["ac_trouble"] = False
            await send_event("AR", 0, "AC_Power_Restored")

        if "ac" in timers:
            timers["ac"]()
            timers.pop("ac")
        if is_trouble and not mem["ac_trouble"]:
            timers["ac"] = async_call_later(hass, delay, fire_ac_trouble)
        elif not is_trouble and mem["ac_trouble"]:
            timers["ac"] = async_call_later(hass, delay, fire_ac_restore)

    # --- OFFLINE LISTENER ---
    async def offline_listener(event):
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if not new_state or not old_state: return
        mem = hass.data[DOMAIN][entry.entry_id]
        timers = mem["timers"]
        is_unavail = new_state.state in ["unavailable", "unknown"]
        was_unavail = old_state.state in ["unavailable", "unknown"]
        if is_unavail == was_unavail: return

        delay = merged_conf.get("offline_grace_period", 300)
        timer_key = f"offline_{entity_id}"
        sensor_obj = hass.states.get(entity_id)
        friendly_name = sensor_obj.attributes.get("friendly_name", entity_id) if sensor_obj else entity_id

        async def fire_offline(now):
            mem["offline_sensors"].add(entity_id)
            await send_event("UT", 1, f"Offline_{friendly_name}")
        async def fire_online(now):
            mem["offline_sensors"].discard(entity_id)
            await send_event("UH", 1, f"Restored_{friendly_name}")

        if timer_key in timers:
            timers[timer_key]()
            timers.pop(timer_key)
        if is_unavail and entity_id not in mem["offline_sensors"]:
            timers[timer_key] = async_call_later(hass, delay, fire_offline)
        elif not is_unavail and entity_id in mem["offline_sensors"]:
            timers[timer_key] = async_call_later(hass, delay, fire_online)

    # =======================================================
    # CORRECTED INITIALIZATION SEQUENCE (No duplicates/leaks)
    # =======================================================
    
    # 1. Start the independent Polling Loop
    unsub_interval = async_track_time_interval(hass, handle_polling, timedelta(minutes=merged_conf.get("polling_interval", 30)))
    hass.async_create_task(handle_polling()) # Fire first heartbeat immediately

    # 2. Attach Alarmo Tracker
    unsub_event = async_track_state_change_event(hass, alarm_entity, alarmo_listener)
    
    # 3. Attach AC Tracker (If configured)
    ac_entities = [e for e in [merged_conf.get("ac_binary_sensor"), merged_conf.get("ac_numeric_sensor")] if e and isinstance(e, str)]
    unsub_ac = async_track_state_change_event(hass, ac_entities, ac_listener) if ac_entities else None

    # 4. Attach Offline Tracker (If configured)
    offline_entities = merged_conf.get("offline_sensors", [])
    unsub_offline = async_track_state_change_event(hass, offline_entities, offline_listener) if offline_entities else None

    # 5. Attach Config Update Tracker
    unsub_update = entry.add_update_listener(update_listener)
    
    # 6. Save ALL un-subscribers so they can be properly killed on reload
    hass.data[DOMAIN][entry.entry_id]["unsub_interval"] = unsub_interval
    hass.data[DOMAIN][entry.entry_id]["unsub_event"] = unsub_event
    hass.data[DOMAIN][entry.entry_id]["unsub_ac"] = unsub_ac
    hass.data[DOMAIN][entry.entry_id]["unsub_offline"] = unsub_offline
    hass.data[DOMAIN][entry.entry_id]["unsub_update"] = unsub_update

    return True

async def update_listener(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass, entry):
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    
    # Cleanly kill all listeners
    for key in ["unsub_interval", "unsub_event", "unsub_ac", "unsub_offline", "unsub_update"]:
        if key in data and callable(data[key]):
            data[key]()
            
    # Cleanly kill all active timers
    for timer_cancel in data.get("timers", {}).values():
        timer_cancel()
        
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True