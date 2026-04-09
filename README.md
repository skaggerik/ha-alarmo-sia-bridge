# Alarmo SIA DC-09 Bridge

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/version-1.0.4-blue.svg)

An amateur-grade Home Assistant integration that bridges **Alarmo** to any Central Monitoring Station (CMS) using the **SIA DC-09 (SIA-DCS)** protocol. 


## ✨ Features

* **Standard Compliance:** Uses the SIA DC-09 protocol with CRC-16 (ARC) validation.
* **Visual Verification:** Automatically captures snapshots from **multiple cameras** and sends secure URLs to the CMS.
* **Sensor Mapping:** Manually map HA entities to specific SIA codes (`FA` for Fire, `WA` for Water, `PA` for Panic, etc.).
* **Complete Event Lifecycle:** Reports not just alarms, but also Restores (`FH`, `BH`), Cancels (`BC`), and Arming/Disarming (`CL`/`OP`).
* **Automatic Heartbeat:** Sends Routine Test (`RP`) packets to ensure the link is always alive.
* **Professional Logic:** Sanitizes entity names for strict protocol compatibility.
* AC power trouble detection with binary sensor or numeric value.
* Unavailable sensor detection.

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
* **Host/Port:** The IP and Port of your CMS or receiver.
* **Account ID:** Your unique account number provided by the CMS.
* **Protocol:** Choose between TCP (recommended) or UDP.

### 2. Options (The "Configure" Button)
Click **Configure** on the integration card to access advanced features:
* **Alarm Entity:** Select which `alarm_control_panel` to monitor (defaults to Alarmo).
* **OP/CL Reports:** Enable this to notify the CMS whenever the system is armed or disarmed.
* **Photo Verification:** * Select one or more **Camera Entities**.
    * Provide your **Base URL** (e.g., `https://your-ha-instance.duckdns.org`). *Note: Do not add a trailing slash.*
* **Sensor Mapping:** Group your sensors into Fire, Water, Gas, or Panic categories to ensure the correct 2-letter SIA code is transmitted.
* **Offline sensor detection:** add entities to be monitored in *offline_sensors*

## 🛠 How it Works (SIA Payload Anatomy)

The bridge constructs a standard-compliant string for the dispatcher:
`[#1234|Nri1/BA^Kitchen_Window|Url:https://.../photo.jpg]`

* **BA:** The Event Code (Burglary Alarm).
* **ri1:** The Zone Number (defaulting to 1).
* **Kitchen_Window:** The Friendly Name of your sensor.
* **Url:** The visual verification link for the dispatcher.

## ⚠️ Important Notes
* **Networking:** Ensure your Home Assistant instance can communicate with the CMS IP on the specified port.
* **URL Accessibility:** For the camera feature to work, your `Base URL` must be accessible by the CMS receiver.
* **SIA Limits:** Most CMS receivers have a character limit. Avoid selecting more than 3 cameras to keep the packet length stable.

## 📄 License
License stuff. Yes.



