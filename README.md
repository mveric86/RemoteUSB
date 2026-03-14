# USB-over-IP WLAN Bridge – Projektbeschreibung

Mobiler USB/IP-Server auf Basis eines Raspberry Pi Zero 2W.
Ermöglicht das drahtlose Einbinden von USB-Geräten (ESP32, Arduino) in einen Proxmox-LXC über WireGuard VPN.

---

## Hardware

- **Board:** Raspberry Pi Zero 2W
- **USB-Gerät:** ESP32 / Arduino (angeschlossen am einzigen USB-Port per OTG-Adapter)
- **RGB-LED:** gemeinsame Kathode, 3x 330Ω Vorwiderstand
- **Taster 1:** AP-Modus erzwingen
- **Taster 2:** Sauberer Shutdown

---

## Pinbelegung

| Funktion        | GPIO | Pin | Anmerkung                            |
|-----------------|------|-----|--------------------------------------|
| AP-Taster       | 4    | 7   | gegen GND (Pin 9), interner Pull-up  |
| Shutdown-Taster | 27   | 36  | gegen GND (Pin 34), interner Pull-up |
| RGB Anode Blau  | 23   | 33  | 330Ω Vorwiderstand                   |
| RGB Anode Grün  | 24   | 35  | 330Ω Vorwiderstand                   |
| RGB Anode Rot   | 25   | 37  | 330Ω Vorwiderstand                   |
| RGB Kathode     | GND  | 39  | gemeinsame Kathode                   |

---

## Software-Komponenten

- **USB/IP** – Linux-Kernel-Modul, exportiert USB-Geräte über TCP (Port 3240)
- **WireGuard** – VPN-Client, Tunnel ins Heimnetz (pro Netzwerk konfigurierbar)
- **wpa_supplicant** – WLAN-Verwaltung mit Prioritäten
- **hostapd** – Access Point Modus
- **Watchdog-Script** – überwacht WireGuard-Erreichbarkeit
- **Webinterface** – WLAN- und WireGuard-Verwaltung (nur im AP-Modus erreichbar)
- **Read-only Filesystem** – schützt SD-Karte bei Stromverlust

---

## Systemlogik

### Boot-Sequenz

1. Bekannte WLANs prüfen (wpa_supplicant)
1. Verbinden mit höchstpriorisiertem verfügbarem Netz
1. WireGuard starten falls für dieses Netz aktiviert
1. USB/IP-Server starten
1. LED-Status setzen

### Watchdog (läuft dauerhaft)

- Prüft ob aktuelles Netz WireGuard benötigt
- Falls ja: prüft WireGuard-Erreichbarkeit per Ping auf Heimnetz-IP
- WLAN verbunden + WireGuard nicht benötigt → Grün
- WLAN verbunden + WireGuard verbunden → Blau
- WLAN verbunden + WireGuard benötigt aber nicht erreichbar → Gelb + AP-Modus nach Timeout
- Kein WLAN → sofort AP-Modus

### Taster (2 Sekunden halten)

- **GPIO 4** → AP-Modus erzwingen (unabhängig vom WireGuard-Status)
- **GPIO 27** → sauberer Shutdown (`sudo shutdown -h now`)

---

## LED-Statusanzeige (RGB, gemeinsame Kathode)

| Status                                     | Farbe | Muster       |
|--------------------------------------------|-------|--------------|
| WLAN verbunden, WireGuard off (Heimnetz)   | Grün  | Dauerhaft an |
| WLAN verbunden, WireGuard nicht erreichbar | Gelb  | Dauerhaft an |
| WLAN verbunden + WireGuard verbunden       | Blau  | Dauerhaft an |
| AP-Modus aktiv                             | Gelb  | Blinkend     |
| Kein WLAN                                  | Rot   | Dauerhaft an |
| Shutdown läuft                             | Rot   | Blinkend     |

---

## WLAN-Verwaltung (Webinterface im AP-Modus)

Das Webinterface ist **ausschließlich im AP-Modus** erreichbar (`http://192.168.4.1`).

Pro WLAN-Eintrag konfigurierbar:

- SSID + Passwort
- Priorität (wpa_supplicant `priority=`)
- Aktivieren / Deaktivieren (`disabled=1`) ohne Passwort zu löschen
- **WireGuard verwenden** (Checkbox, `use_wireguard=true/false`)
- Löschen

---

## WireGuard-Konfiguration (Webinterface im AP-Modus)

Die WireGuard-Konfiguration ist ebenfalls nur im AP-Modus editierbar:

- Interface (privater Schlüssel, Adresse, DNS)
- Peer (öffentlicher Schlüssel, Endpoint, AllowedIPs)
- Änderungen werden in `/etc/wireguard/wg0.conf` gespeichert

---

## USB/IP – Client-Seite (Proxmox LXC)

```bash
# Verfügbare Geräte anzeigen
usbip list -r <pi-ip>

# Gerät einbinden
usbip attach -r <pi-ip> -b <busid>

# Gerät trennen
usbip detach -p <port>
```

PlatformIO erkennt den ESP32/Arduino danach als lokales Gerät (`/dev/ttyUSB0` o.ä.).

---

## Netzwerk

- Pi Zero 2W erhält feste IP im Heimnetz (z.B. per Pi-hole / DHCP-Reservierung)
- LXC verbindet sich über WireGuard-Tunnel zur Pi-IP
- AP-Modus SSID: `USB-Bridge-AP` (oder frei wählbar)
- AP-Modus IP: `192.168.4.1`
- Webinterface nur im AP-Modus erreichbar (kein Zugriff von außen)

---

## Filesystem

- Root-Partition: **read-only** (overlayfs)
- `/etc/wpa_supplicant/` : **read-write** (tmpfs mit persistenter Synchronisation)
- `/etc/wireguard/` : **read-write** (tmpfs mit persistenter Synchronisation)
- Schützt SD-Karte bei hartem Stromverlust
