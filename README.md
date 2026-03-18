# RemoteUSB

![Status](https://img.shields.io/badge/status-work%20in%20progress-yellow)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)

Mobiler USB/IP-Server auf Basis eines Raspberry Pi Zero 2W.
Ermöglicht das drahtlose Einbinden beliebiger USB-Geräte über WLAN in ein System im lokalen Netzwerk oder ein entferntes System über WireGuard VPN – standortunabhängig und ohne physischen Zugang zum Zielrechner.

-----

## Features

- Beliebige USB 2.0-Geräte drahtlos einbinden (optional mit USB-Hub)
- WireGuard VPN – pro Netzwerk konfigurierbar (z.B. im Heimnetz deaktivierbar)
- Automatischer AP-Modus bei fehlendem oder nicht erreichbarem Netzwerk
- Webinterface (nur im AP-Modus erreichbar) zur Verwaltung von:
  - WLAN-Netzwerken (Scan, Priorität, Aktivieren/Deaktivieren)
  - WireGuard-Konfiguration (manuell oder per QR-Code Import)
  - LED-Helligkeit (pro Farbe)
- RGB-LED Statusanzeige
- 2 Taster (AP-Modus erzwingen, sauberer Shutdown)
- Read-only Filesystem – schützt SD-Karte bei Stromverlust
- Stromversorgung per USB-C Powerbank (5V/3A)

-----

## Kompatibilität

**Server:** Raspberry Pi Zero 2W

**Client:**

- Linux (Ubuntu, Debian, Arch, u.a.) – nativ
- Windows 11 – offizieller Microsoft USB/IP-Treiber
- Windows 10 – Open-Source-Alternativen (usbipd-win)
- macOS – nicht unterstützt

-----

## Hardware

|Komponente          |Beschreibung                                         |
|--------------------|-----------------------------------------------------|
|Raspberry Pi Zero 2W|Hauptboard                                           |
|RGB-LED             |Gemeinsame Kathode, Vorwiderstände je nach Datenblatt|
|Taster AP           |GPIO 4, gegen GND                                    |
|Taster Shutdown     |GPIO 27, gegen GND                                   |
|USB-C Buchse        |5V/3A, CC1+CC2 je 5,1kΩ gegen GND                    |

### Pinbelegung

|Funktion       |GPIO|Pin|Anmerkung                           |
|---------------|----|---|------------------------------------|
|AP-Taster      |4   |7  |gegen GND (Pin 9), interner Pull-up |
|Shutdown-Taster|27  |36 |gegen GND (Pin 34), interner Pull-up|
|RGB Anode Blau |23  |33 |Vorwiderstand (siehe Datenblatt)    |
|RGB Anode Grün |24  |35 |Vorwiderstand (siehe Datenblatt)    |
|RGB Anode Rot  |25  |37 |Vorwiderstand (siehe Datenblatt)    |
|RGB Kathode    |GND |39 |gemeinsame Kathode                  |


> **Hinweis:** Die Widerstandswerte sind abhängig von der verwendeten RGB-LED. Jede Farbe hat eine unterschiedliche Vorwärtsspannung – bitte das Datenblatt der verwendeten LED konsultieren.

-----

## Installation

```bash
# Raspberry Pi OS Lite flashen (Raspberry Pi Imager)
# SSH + WLAN in den erweiterten Einstellungen konfigurieren
# Dann per SSH:

git clone https://github.com/mveric86/RemoteUSB
cd RemoteUSB
sudo ./install.sh
```

Nach dem Neustart mit WLAN `RemoteUSB` verbinden und WireGuard unter `http://192.168.4.1` konfigurieren.

-----

## LED-Statusanzeige

|Status                                    |Farbe|Muster   |
|------------------------------------------|-----|---------|
|WLAN verbunden, WireGuard off (Heimnetz)  |Grün |Dauerhaft|
|WLAN verbunden, WireGuard nicht erreichbar|Gelb |Dauerhaft|
|WLAN verbunden + WireGuard verbunden      |Blau |Dauerhaft|
|AP-Modus aktiv                            |Gelb |Blinkend |
|Kein WLAN                                 |Rot  |Dauerhaft|
|Shutdown läuft                            |Rot  |Blinkend |

-----

## Lizenz

Copyright (c) 2026 Marco Veric

Dieses Projekt steht unter der [GPL-3.0 Lizenz](LICENSE).

-----

## Acknowledgements

Dieses Projekt verwendet folgende Open-Source-Software:

|Komponente     |Lizenz       |Link                                  |
|---------------|-------------|--------------------------------------|
|Linux USB/IP   |GPL-2.0      |https://www.kernel.org                |
|WireGuard      |GPL-2.0      |https://www.wireguard.com             |
|hostapd        |BSD / GPL-2.0|https://w1.fi/hostapd                 |
|dnsmasq        |GPL-2.0      |https://thekelleys.org.uk/dnsmasq     |
|wpa_supplicant |BSD / GPL-2.0|https://w1.fi/wpa_supplicant          |
|Flask          |BSD-3-Clause |https://flask.palletsprojects.com     |
|gpiozero       |BSD-3-Clause |https://gpiozero.readthedocs.io       |
|Pillow         |HPND         |https://python-pillow.org             |
|zxing-cpp      |Apache-2.0   |https://github.com/zxing-cpp/zxing-cpp|
|Raspberry Pi OS|Various      |https://www.raspberrypi.com/software  |