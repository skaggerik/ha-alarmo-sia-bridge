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
from homeassistant.helpers.storage import Store
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

    store = Store(hass, 1, f"{DOMAIN}_seq_{entry.entry_id}")
    saved_data = await store.async_load()
    
    # Use saved sequence, or fallback to the manual override provided in initial setup
    current_seq = saved_data.get("seq") if saved_data else merged_conf.get("starting_sequence", 1)

    account = SIAAccount(account_id, key=merged_conf.get("key"))
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {
        "seq": current_seq,
        "last_seq": "None", 
        "current_route": "primary", 
        "active_alarms": set(), 
        "ac_trouble": False,
        "timers": {},
        "offline_sensors": set(),
        "history": deque(maxlen=50) 
    })

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    def create_sia_packet(code, zone, message="", url=""):
        now = datetime.now(timezone.utc).strftime("%H:%M:%S,%m-%d-%Y")
        mem = hass.data[DOMAIN][entry.entry_id]
        
        seq_str = str(mem["seq"]).zfill(4)
        mem["last_seq"] = seq_str # Store exactly what we are about to transmit
        mem["seq"] = (mem["seq"] % 9999) + 1
        hass.async_create_task(store.async_save({"seq": mem["seq"]}))

        clean_msg = message.replace(' ', '_').replace('/', '_')
        photo_method = merged_conf.get("photo_method", "extended_message")
        
        if url and photo_method == "extended_message":
            event_block = f"[#{account_id}|Nri{zone}/{code}^{clean_msg}|Url:{url}]"
            multi_block = ""
        else:
            event_block = f"[#{account_id}|Nri{zone}/{code}^{clean_msg}]"
            multi_block = ""
            if url:
                if photo_method == "ajax_v": multi_block = f"[V{url}]"
                elif photo_method == "modern_url": multi_block = f"[#{account_id}|M{url}]"

        rec_num = merged_conf.get("receiver_number", "1")
        header = f"\"SIA-DCS\"{seq_str}R{rec_num}L0#{account_id}"
        readable_content = f"{header}{event_block}{multi_block}_{now}"
        
        content_len = hex(len(readable_content))[2:].zfill(4).upper()
        crc = 0x0000
        for byte in readable_content.encode('ascii'):
            crc ^= byte
            for _ in range(8): crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        
        checksum = hex(crc)[2:].zfill(4).upper()
        full_packet_string = f"{checksum}{content_len}{readable_content}"
        
        packet_to_send = f"\n{full_packet_string}\r".encode('ascii')
        return packet_to_send, full_packet_string

    def _send_udp_sync(packet_bytes, t_host, t_port, timeout):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(packet_bytes, (t_host, t_port))
            data, _ = sock.recvfrom(1024)
            return data.decode('ascii', errors='ignore') if data else ""
        except socket.timeout:
            return None
        except Exception as e:
            return f"ERR:{e}"
        finally:
            sock.close()

    async def _send_tcp(packet_bytes, t_host, t_port, timeout):
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(t_host, t_port), timeout=timeout)
            writer.write(packet_bytes)
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=timeout)
            writer.close()
            await writer.wait_closed()
            return data.decode('ascii', errors='ignore') if data else ""
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            return f"ERR:{e}"

    async def try_route(t_host, t_port, t_protocol, packet_bytes, timeout, retries):
        status = "Unknown Error"
        raw_resp = "None"
        for attempt in range(1, retries + 1):
            if t_protocol == "UDP":
                resp = await hass.async_add_executor_job(_send_udp_sync, packet_bytes, t_host, t_port, timeout)
            else:
                resp = await _send_tcp(packet_bytes, t_host, t_port, timeout)
            
            raw_resp = resp if resp else "None"

            if resp is None: status = "Timeout (No Reply)"
            elif resp == "": status = "Connection Closed (No Data)"
            elif resp.startswith("ERR:"): status = f"Socket Error: {resp[4:]}"
            elif "ACK" in resp: return True, f"ACK (Attempt {attempt})", raw_resp
            elif "NAK" in resp: status = "NAK Received"
            elif "DUH" in resp: status = "DUH Received"
            else: status = f"Unknown Reply: {resp.strip()}"
                
            if attempt < retries: await asyncio.sleep(2) 
                
        return False, f"Failed: {status}", raw_resp

    async def send_event(code, zone=1, message="", url=""):
        packet_bytes, readable_string = create_sia_packet(code, zone, message, url)
        mem = hass.data[DOMAIN][entry.entry_id]
        
        p_host = merged_conf.get("host")
        p_port = merged_conf.get("port")
        p_proto = merged_conf.get("protocol", "TCP")
        s_host = merged_conf.get("secondary_host")
        s_port = merged_conf.get("secondary_port")
        s_proto = merged_conf.get("secondary_protocol", "TCP")
        
        retries = merged_conf.get("max_retries", 3)
        timeout = merged_conf.get("retry_timeout", 20)
        
        log_msgs = []
        success = False
        last_reply = "None"

        # 1. Primary Test (Failback)
        if mem["current_route"] == "secondary" and code == "RP":
            test_success, status, raw_resp = await try_route(p_host, p_port, p_proto, packet_bytes, timeout, 1)
            last_reply = raw_resp
            if test_success:
                log_msgs.append(f"Primary Restored! ({status})")
                mem["current_route"] = "primary"
                success = True
            else:
                log_msgs.append(f"Primary Test: {status}")

        # 2. Main Routing Logic
        if not success:
            if mem["current_route"] == "primary":
                success, status, raw_resp = await try_route(p_host, p_port, p_proto, packet_bytes, timeout, retries)
                last_reply = raw_resp
                log_msgs.append(f"Primary: {status}")
                
                if not success and s_host and s_port:
                    log_msgs.append("Switched Route -> Secondary")
                    mem["current_route"] = "secondary"
                    success, s_status, s_raw_resp = await try_route(s_host, s_port, s_proto, packet_bytes, timeout, retries)
                    last_reply = s_raw_resp
                    log_msgs.append(f"Secondary: {s_status}")
            else:
                success, status, raw_resp = await try_route(s_host, s_port, s_proto, packet_bytes, timeout, retries)
                last_reply = raw_resp
                log_msgs.append(f"Secondary: {status}")

        event_data = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "code": code,
            "msg": message,
            "full_packet": readable_string,
            "reply": last_reply.strip() if last_reply else "None",
            "status": " | ".join(log_msgs)
        }
        mem["history"].appendleft(event_data)
        async_dispatcher_send(hass, f"{DOMAIN}_{entry.entry_id}_event_added")

    # --- POLLING ---
    async def handle_polling(now=None): await send_event("RP", 0, "Heartbeat")

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
            if new_state.state == "disarmed": await send_event("OP", 1, "System_Disarmed")
            elif new_state.state.startswith("armed_"): await send_event("CL", 1, f"System_{new_state.state}")

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

    unsub_interval = async_track_time_interval(hass, handle_polling, timedelta(minutes=merged_conf.get("polling_interval", 30)))
    hass.async_create_task(handle_polling()) 

    unsub_event = async_track_state_change_event(hass, alarm_entity, alarmo_listener)
    
    ac_entities = [e for e in [merged_conf.get("ac_binary_sensor"), merged_conf.get("ac_numeric_sensor")] if e and isinstance(e, str)]
    unsub_ac = async_track_state_change_event(hass, ac_entities, ac_listener) if ac_entities else None

    offline_entities = merged_conf.get("offline_sensors", [])
    unsub_offline = async_track_state_change_event(hass, offline_entities, offline_listener) if offline_entities else None

    unsub_update = entry.add_update_listener(update_listener)
    
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
    for key in ["unsub_interval", "unsub_event", "unsub_ac", "unsub_offline", "unsub_update"]:
        if key in data and callable(data[key]): data[key]()
    for timer_cancel in data.get("timers", {}).values(): timer_cancel()
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True