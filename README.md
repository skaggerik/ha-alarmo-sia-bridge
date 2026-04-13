# Alarmo SIA DC-09 Bridge

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/version-1.0.5-blue.svg)

An amateur-grade Home Assistant integration that bridges **Alarmo** to any Central Monitoring Station (CMS) using the **SIA DC-09 (SIA-DCS)** protocol. 

## ✨ Features (New in v1.0.5)

* **Pro-Standard Sequencing:** Strictly follows chronological reporting logic (Restores -> Cancels -> Disarms) to ensure CMS tickets close automatically without "stuck" alarms.
* **Live Diagnostic Sensor:** Automatically creates a `sensor.sia_history` entity in Home Assistant containing a rolling, unencrypted log of your last 50 transmitted packets for easy dashboard monitoring.
* **3 Visual Verification Methods:** Automatically captures snapshots from multiple cameras and formats the packet according to your specific CMS requirements:
  * *Plaintext Extended Message* (SIA DC-03)
  * *Ajax 'V' Method* (Dedicated hardware block)
  * *Modern Multi-Media URL* (SIA DC-09-2021 standard)
* **Receiver Routing:** Support for assigning specific Receiver Numbers (e.g., `R1`, `R2`) to the packet header.
* **Instant Heartbeats:** Sends a Routine Test (`RP`) packet immediately upon boot/reload, and continues on your set interval.
* **Advanced Monitoring:** Grace-period protected tracking for AC Power loss and Offline/Unavailable sensors to prevent false CMS dispatches during network flickers.

## 🚀 Installation

### Via HACS (Recommended)
1. Open **HACS** in Home Assistant.
2. Click the three dots in the top right and select **Custom repositories**.
3. Paste this repository URL and select **Integration** as the category.
4. Click **Install**.
5. Restart Home Assistant.

## ⚙️ Configuration

### 1. Connection
After installation, go to **Settings > Devices & Services > Add Integration** and search for **Alarmo SIA DC-09 Bridge**.
* **Host / Port:** The IP and Port of your CMS receiver.
* **Protocol:** Choose between TCP (recommended) or UDP.
* **Account ID:** Your unique account number provided by the CMS.
* **Receiver Number:** (Optional) Specific receiver channel (defaults to 1).
* **Encryption Key:** (Optional) 16, 24, or 32-character HEX key for AES encryption.

### 2. Options (The "Configure" Button)
Click **Configure** on the integration card to access advanced features:
* **Alarm Entity:** Select which `alarm_control_panel` to monitor (defaults to Alarmo).
* **OP/CL Reports:** Enable this to notify the CMS whenever the system is armed or disarmed.
* **Photo Verification Method:** Choose how your CMS expects multimedia links to be formatted.
* **Camera Entities & Base URL:** Select your cameras and provide your external Home Assistant URL (e.g., `https://your-ha.duckdns.org`). *Note: Do not add a trailing slash.*
* **Sensor Mapping:** Group your sensors into Fire, Water, Gas, or Panic categories to ensure the correct 2-letter SIA code is transmitted.
* **AC / Offline Monitoring:** Define binary/numeric sensors for system health, along with grace periods to filter out brief outages.

## 🛠 How it Works (SIA Payload Anatomy)

The bridge utilizes a **Zone 0 / Zone 1** architecture. Zone 0 is reserved strictly for system health (Heartbeats, Power), while all physical sensors are reported on Zone 1 using their Home Assistant "Friendly Name" for dispatcher clarity.

The payload structure adapts dynamically based on your chosen **Photo Verification Method**:

* **Standard (No Photo):** `[#1234|Nri1/BA^Kitchen_Window]`
* **Method 1 (Extended):** `[#1234|Nri1/BA^Kitchen_Window|Url:https://...]`
* **Method 2 (Ajax V):** `[#1234|Nri1/BA^Kitchen_Window][Vhttps://...]`
* **Method 3 (Modern M):** `[#1234|Nri1/BA^Kitchen_Window][#1234|Mhttps://...]`

## ⚠️ Important Notes
* **Networking:** Ensure your Home Assistant instance can communicate with the CMS IP on the specified port.
* **URL Accessibility:** For the camera feature to work, your `Base URL` must be publicly accessible by the CMS receiver.
* **SIA Limits:** Most CMS receivers have a character limit. Avoid selecting more than 3 cameras at once to keep the packet length stable.

## 📄 License
This project is licensed under the GPL-3.0 license.