# Alarmo SIA DC-09 Bridge

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)

A Home Assistant integration that bridges **Alarmo** to any Central Monitoring Station (CMS) using the **SIA DC-09 (SIA-DCS)** protocol. All code happens to be machine generated but seems to work well. 

## ✨ Features (New in v1.1.0)

* **Failover Routing:** True Primary/Secondary CMS redundancy with application-level `[ACK]` validation and automatic failback capabilities.
* **Persistent Sequence Tracking:** Saves the packet sequence to your local storage to prevent CMS synchronization errors during Home Assistant restarts.
* **Custom Sequence Override:** Allows you to manually inject the next sequence number during a fresh installation.
* **Live Diagnostic Sensors:** Exposes unencrypted packet logs, exact routing statuses (Tx/Rx), and the current sequence number directly to your Home Assistant dashboard.
* **3 Visual Verification Methods:** Captures snapshots from multiple cameras and formats the packet according to your specific CMS requirements (Extended DC-03, Ajax 'V', or Modern DC-09-2021).
* **Advanced Health Monitoring:** Tracks AC Power loss and Offline sensors with configurable grace periods to prevent false dispatches during brief network flickers.

---

## 🚀 Installation

### Via HACS (Recommended)
1. Open **HACS** in Home Assistant.
2. Click the three dots in the top right and select **Custom repositories**.
3. Paste this repository URL and select **Integration** as the category.
4. Click **Install**.
5. Restart Home Assistant.

---

## ⚙️ Configuration & Options

After installation, go to **Settings > Devices & Services > Add Integration** and search for **Alarmo SIA DC-09 Bridge**. 

### Initial Setup & Sequence Override
During the initial setup, you will configure your Primary CMS, Account ID, Protocol, and **Starting Sequence**.
* **Starting Sequence (Important for Re-installs):** If you are reinstalling this integration, your CMS expects the sequence number to pick up exactly where it left off. Check your previous `sensor.sia_sequence` (or ask your CMS). **Always enter the NEXT number.** For example, if your last successfully transmitted packet was `0063`, you must enter `64` here to prevent a "Sequence Out of Order" error at the CMS.

### Polling & System Health Grace Periods
To prevent spamming the CMS during internet flickers or brief Home Assistant reboots, timers must be configured:
* **Polling Interval:** Defined in **Minutes** (Default: 30). This determines how often a Routine Test (`RP` / Heartbeat) is sent to the CMS to prove your system is online.
* **AC Grace Period:** Defined in **Seconds** (Default: 60). The system will wait this long after detecting a power drop before reporting an AC Trouble (`AT`) alarm.
* **Offline Grace Period:** Defined in **Seconds** (Default: 300). The system will wait this long after a sensor goes unavailable before reporting an Offline (`UT`) alarm.

### Offline Sensor Monitoring
By default, the bridge does not track offline sensors. **For offline detection to work, you must manually add the entities you want to monitor** in the Options menu under the *Offline Sensors* field.

### AC Power Monitoring (Binary vs. Numeric)
You can monitor your home's main power using either a Binary Sensor (on/off) or a Numeric Sensor (voltage/percentage). 
* **Numeric Sensor:** Select your sensor and set the `ac_threshold` (e.g., `210` for voltage, or `10` for battery percentage). If the sensor drops *below* this value, it triggers an AC Trouble alarm.
* **Binary Sensor:** The integration uses the sensor's assigned `device_class` to determine what state constitutes an alarm:
  * If the device class is **`problem`** or **`battery`**: The state **`on`** means trouble (power lost).
  * For **all other device classes** (e.g., `power`, `plug`, or no class): The state **`off`** means trouble (power lost).

---

## 🔄 Primary & Backup Failover Logic

Version 1.1.0 introduces true commercial hardware routing. You can optionally configure a **Secondary CMS** (including different IP, Port, and Protocol) in the Options menu. 

Here is exactly how the bridge handles routing:

1. **Strict `[ACK]` Validation:** When an event occurs, the bridge opens a connection to the Primary CMS and sends the packet. It does not just assume it worked—it actively waits for the receiver to send back an `[ACK]` (Acknowledge) command. 
2. **The Failover:** If the bridge receives a `[NAK]`, a `[DUH]`, or times out (configurable, default 20 seconds) after the maximum number of retries (default 3 attempts), it instantly flags the Primary CMS as offline and reroutes the alarm to the Secondary CMS.
3. **The Failback (Reverting to Primary):** Once the bridge has failed over to the Secondary CMS, it doesn't stay there forever. When it is time to send the next Routine Test / Heartbeat (`RP`), the bridge uses this non-emergency packet to "ping" the Primary CMS. If the Primary CMS replies with an `[ACK]`, the bridge restores the connection route and locks back onto the Primary IP for all future alarms.

*Note: You can monitor this entire process live by checking the `sensor.[cms_name]_sia_history` entity on your dashboard.*

---

## 🛠 Payload Anatomy

The bridge utilizes a **Zone 0 / Zone 1** architecture. Zone 0 is reserved strictly for system health (Heartbeats, Power), while all physical sensors are reported on Zone 1 using their Home Assistant "Friendly Name" for dispatcher clarity.

The payload structure adapts dynamically based on your chosen **Photo Verification Method**:

* **Standard (No Photo):** `[#1234|Nri1/BA^Kitchen_Window]`
* **Extended (SIA-DC-03):** `[#1234|Nri1/BA^Kitchen_Window|Url:https://...]`
* **Ajax 'V' (Dedicated Video Block):** `[#1234|Nri1/BA^Kitchen_Window][Vhttps://...]`
* **Modern (SIA-DC-09-2021):** `[#1234|Nri1/BA^Kitchen_Window][#1234|Mhttps://...]`

---

## ⚠️ Important Notes
* **Networking:** Ensure your Home Assistant instance can communicate with the CMS IP on the specified port. If using TCP, ensure the receiver cleanly closes sockets to prevent `[Errno 104]` resets.
* **URL Accessibility:** For the camera feature to work, your `Base URL` must be publicly accessible by the CMS receiver.
* **SIA Limits:** Most CMS receivers have a character limit. Avoid selecting more than 3 cameras at once to keep the packet length stable.

---

## 📄 License
This project is licensed under the GPL-3.0 license.
