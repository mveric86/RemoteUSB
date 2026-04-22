# RemoteUSB

![Status](https://img.shields.io/badge/status-work%20in%20progress-yellow)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)

Mobiler USB/IP-Server auf Basis eines Raspberry Pi Zero 2W.
Ermöglicht das drahtlose Einbinden beliebiger USB-Geräte über WLAN in ein System im lokalen Netzwerk oder ein entferntes System über WireGuard VPN – standortunabhängig und ohne physischen Zugang zum Zielrechner.

-----

## Features

- **Beliebige USB 2.0-Geräte** drahtlos einbinden (optional mit USB-Hub)
- **Automatisches Binding**: Jedes angesteckte Gerät ist sofort per USB/IP exportierbar, kein `busid`-Handling nötig
- **WireGuard VPN** – pro Netzwerk konfigurierbar (z.B. im Heimnetz deaktivierbar)
- **Automatischer AP-Modus** bei Ersteinrichtung (keine WLAN-Konfiguration vorhanden)
- **Webinterface im AP-Modus** (`http://192.168.4.1`) zur Verwaltung von:
  - WLAN-Netzwerken (Scan, Priorität, Aktivieren/Deaktivieren, WireGuard pro Netz)
  - WireGuard-Konfiguration (manuell, `.conf`-Upload oder QR-Code-Import)
  - USB-Geräte (Export-Override + Session-Release)
  - LED-Helligkeit (pro Farbe)
- **RGB-LED-Statusanzeige** (WLAN/WireGuard/AP/Shutdown)
- **2 Taster**:
  - *AP-Taster*: AP-Modus erzwingen (toggle, bleibt bis nächster Druck oder Reboot)
  - *Shutdown-Taster*: kurz drücken = USB-Sessions freigeben, 2 s halten = sauberer Shutdown
- **Persistente Konfiguration** auf ext4-Image auf der Boot-FAT-Partition (überlebt Reboots trotz Read-only Root-FS)
- **Read-only Root-Filesystem** (overlayroot) – schützt SD-Karte bei Stromverlust
- **Stromversorgung** per USB-C Powerbank (5 V/3 A)

-----

## Kompatibilität

**Server:** Raspberry Pi Zero 2W mit Raspberry Pi OS Lite (Trixie)

**Client:**

- Linux (Debian/Ubuntu/Arch, ...) – nativ über `usbip`
- Windows 11 – offizieller Microsoft USB/IP-Treiber (usbipd-win)
- Windows 10 – Open-Source-Alternativen (usbipd-win)
- macOS – nicht unterstützt (USB/IP nicht im Kernel)

Innerhalb einer Proxmox-VM: funktioniert out-of-the-box. In einem LXC-Container funktioniert es mit einmaligem Host-Setup (`vhci-hcd` + Mount-Entry), siehe [Client-Nutzung in LXC](#client-nutzung-in-lxc).

-----

## Hardware

| Komponente          | Beschreibung                                         |
|---------------------|------------------------------------------------------|
| Raspberry Pi Zero 2W | Hauptboard                                          |
| RGB-LED             | Gemeinsame Kathode, Vorwiderstände je nach Datenblatt |
| Taster AP           | GPIO 4, gegen GND                                    |
| Taster Shutdown     | GPIO 27, gegen GND                                   |
| USB-C Buchse        | 5 V/3 A, CC1+CC2 je 5,1 kΩ gegen GND                 |

### Pinbelegung

| Funktion         | GPIO | Pin | Anmerkung                            |
|------------------|------|-----|--------------------------------------|
| AP-Taster        | 4    | 7   | gegen GND (Pin 9), interner Pull-up  |
| Shutdown-Taster  | 27   | 36  | gegen GND (Pin 34), interner Pull-up |
| RGB Anode Blau   | 23   | 33  | Vorwiderstand (siehe Datenblatt)     |
| RGB Anode Grün   | 24   | 35  | Vorwiderstand (siehe Datenblatt)     |
| RGB Anode Rot    | 25   | 37  | Vorwiderstand (siehe Datenblatt)     |
| RGB Kathode      | GND  | 39  | gemeinsame Kathode                   |

> **Hinweis:** Die Widerstandswerte sind abhängig von der verwendeten RGB-LED. Jede Farbe hat eine unterschiedliche Vorwärtsspannung – bitte das Datenblatt der LED konsultieren. Rot hat oft merklich weniger Leuchtkraft als Grün – die Helligkeit kann pro Farbe im Webinterface (LED-Tab) ausgeglichen werden.

-----

## Installation (Server)

```bash
# 1. Raspberry Pi OS Lite flashen (Raspberry Pi Imager)
#    In den erweiterten Einstellungen des Imagers:
#      - Benutzer + Passwort setzen
#      - SSH aktivieren
#      - (Optional) WLAN konfigurieren – wird bei Erstinstallation übernommen
#
# 2. Per SSH verbinden und installieren:
git clone https://github.com/mveric86/RemoteUSB
cd RemoteUSB
sudo ./install.sh
```

Das Installations-Script:

- Installiert alle Pakete (USB/IP, WireGuard, hostapd, dnsmasq, Python-Deps)
- Lädt die benötigten Kernel-Module (`usbip_core`, `usbip_host`, `vhci-hcd`)
- Deployt Scripts nach `/usr/local/bin/`, Services nach `/etc/systemd/system/`
- Richtet hostapd + dnsmasq für den AP-Modus ein (SSID und Passwort in `config/default.conf`)
- Legt ein persistentes 32 MB-ext4-Image auf der Boot-FAT-Partition an und bindet `/etc/remoteusb`, `/etc/NetworkManager/system-connections` und `/etc/wireguard` dort hinein
- Aktiviert overlayroot (Read-only Root-FS)
- Fragt am Ende nach einem Neustart

Nach dem Reboot:

- Falls ein WLAN via Imager vorkonfiguriert war: Pi verbindet sich, LED grün.
- Falls nicht: Pi geht in AP-Modus (LED gelb blinkend). Mit WLAN `RemoteUSB` verbinden (Default-Passwort `remoteusb`, bitte ändern!) und unter `http://192.168.4.1` konfigurieren.

-----

## Erstkonfiguration (Webinterface, AP-Modus)

1. Pi läuft, LED gelb blinkt → AP-Modus aktiv
2. Mit WLAN `RemoteUSB` (oder wie in `config/default.conf` gesetzt) verbinden
3. Browser: `http://192.168.4.1`
4. **WLAN-Tab**: Heim-WLAN hinzufügen (Scan nutzen oder SSID manuell), Priorität setzen, WireGuard pro Netz aktivieren
5. **WireGuard-Tab**: Tunnel-Konfiguration eintragen. Drei Wege:
   - Im Textfeld manuell eingeben
   - `.conf`-Datei hochladen (z.B. aus dem Fritzbox-WireGuard-Export)
   - QR-Code-Bild hochladen (aus der WireGuard-App exportiert)
6. **USB-Tab**: angesteckte Geräte ansehen, Export einzeln deaktivieren falls gewünscht
7. **LED-Tab**: Helligkeit pro Farbe kalibrieren
8. Button **„AP beenden und mit gespeichertem Netz verbinden"** → Pi verbindet sich mit dem konfigurierten WLAN

> **Hinweis zu iOS/Android:** Beim Verbinden mit dem AP öffnet das OS oft eine Captive-Portal-Ansicht. Datei-Upload (Config, QR-Bild) ist dort vom System gesperrt. Verlasse die Portal-Ansicht und öffne `http://192.168.4.1` im normalen Browser.

-----

## WireGuard-Setup mit einer Fritzbox

Die Fritzbox unterstützt WireGuard nativ. **Wichtig:** Richte auf der Fritzbox eine **„WireGuard-Netzwerkverbindung" (Site-to-Site)** ein, *nicht* einen „Fernzugang für ein Gerät". Fernzugangs-Peers bekommen Adressen aus dem Heimnetz-Subnet; Heimnetz-Geräte können diese aber nicht erreichen, weil die Fritzbox kein Proxy-ARP macht.

Fritzbox → Internet → Freigaben → VPN (WireGuard) → **„WireGuard-Verbindung hinzufügen"**:

- Domain: `remoteusb.local` (beliebig, nur interner Name)
- Entferntes IPv4-Netzwerk: `192.168.199.0`, Subnetzmaske `255.255.255.252` (ein /30 für den Pi, frei wählbares nicht-kollidierendes Subnet)
- Entfernte IPv6-Adresse: leer
- „Gesamten Traffic leiten": **aus**
- „Nur bestimmte Geräte erreichbar": **aus** (dann erreichen alle Heimnetz-Geräte den Pi)

Fritzbox liefert eine `.conf` zum Download. Die hochladen im Webinterface (`.conf`-Button). Der Pi ist danach **unter `192.168.199.1`** aus dem Heimnetz erreichbar, egal von welchem externen WLAN aus.

-----

## LED-Statusanzeige

| Status                                       | Farbe | Muster       |
|----------------------------------------------|-------|--------------|
| WLAN verbunden, WireGuard off (Heimnetz)     | Grün  | Dauerhaft    |
| WLAN verbunden, WireGuard nicht erreichbar   | Gelb  | Dauerhaft    |
| WLAN verbunden + WireGuard verbunden         | Blau  | Dauerhaft    |
| AP-Modus aktiv                               | Gelb  | Blinkend     |
| Kein WLAN                                    | Rot   | Dauerhaft    |
| USB-Sessions-Release bestätigen              | Cyan  | Kurzer Flash |
| Shutdown läuft                               | Rot   | Blinkend     |

Bei WireGuard-Fehlern (gelb) bleibt der Pi im Station-Mode und probiert den Tunnel weiter. Kein automatischer AP-Fallback – Fernzugriff bleibt erhalten wenn nur der Tunnel hängt.

-----

## Tasterfunktionen

| Taster    | Kurz (<2 s)                              | Lang (≥2 s) halten           |
|-----------|------------------------------------------|------------------------------|
| AP        | —                                        | AP-Modus toggle (an/aus)     |
| Shutdown  | Alle USB/IP-Sessions freigeben           | Sauberer Shutdown            |

Der AP-Taster ist ein Toggle: einmal halten startet Force-AP (bleibt bis zum Reboot oder erneuten Druck), nochmal halten kehrt zurück in den Normalbetrieb. Nützlich wenn man den Pi umkonfigurieren will ohne sich auszusperren.

Short-Press-Release auf dem Shutdown-Taster disconnected alle gerade attachten Clients und macht die Geräte direkt wieder exportierbar. Praktisch wenn ein Client hängt oder man das Gerät schnell an einen anderen Rechner weiterreichen will.

-----

## Client-Nutzung

### Direkte Verwendung mit `usbip`

**Einmalige Client-Einrichtung** (Debian/Ubuntu):

```bash
# Debian:
sudo apt install usbip
# Ubuntu (Paket heißt dort anders):
sudo apt install linux-tools-generic hwdata

# Kernel-Modul laden (persistent):
sudo modprobe vhci-hcd
echo vhci-hcd | sudo tee /etc/modules-load.d/vhci-hcd.conf
```

**Tägliche Nutzung:**

```bash
# Verfügbare Geräte am Server listen:
usbip list -r 192.168.178.32          # Heimnetz-IP des Pi
usbip list -r 192.168.199.1           # VPN-IP über WireGuard

# Gerät attachen (Port 0 ist der erste freie vhci-Slot):
sudo usbip attach -r 192.168.199.1 -b 1-1.4

# Nach Gebrauch detachen:
sudo usbip port                       # Port-Nummer des Geräts suchen
sudo usbip detach -p 0
```

### Komfort-Wrapper `remoteusb`

Das Repo enthält unter [client/remoteusb](client/remoteusb) ein Bash-Script, das die drei nervigsten Eigenheiten kapselt: busid-Discovery, Zwei-Schritt-Ablauf und vergessene Detaches.

```bash
sudo curl -o /usr/local/bin/remoteusb \
     https://raw.githubusercontent.com/mveric86/RemoteUSB/master/client/remoteusb
sudo chmod +x /usr/local/bin/remoteusb
```

Verwendung:

```bash
# Liste zeigen:
remoteusb 192.168.199.1

# Ausgabe:
#   Exportable devices on 192.168.199.1:
#     [1]  1-1.4       Google Inc. : Nexus/Pixel Device (MTP)  (18d1:4ee1)

# Attachen und Session halten bis Ctrl-C (danach automatisches Detach):
remoteusb 192.168.199.1 pixel         # Name-Match (case-insensitive)
remoteusb 192.168.199.1 1-1.4         # per exakter busid
remoteusb 192.168.199.1 1             # per Index aus der Liste

# Alle eigenen Sessions killen:
remoteusb --detach-all
```

Das Script beendet sich automatisch wenn der Server die Session released (z.B. durch den Short-Press-Taster oder das Webinterface), und achtet beim Exit (auch bei Ctrl-C/SIGTERM) auf sauberes Detach.

### Client-Nutzung in LXC

LXC-Container teilen sich den Kernel mit dem Host, können also `vhci-hcd` nicht selbst laden. Einmalige Einrichtung:

**Auf dem Proxmox-Host:**

```bash
modprobe vhci-hcd
echo vhci-hcd > /etc/modules-load.d/vhci-hcd.conf
```

**In der LXC-Config** (`/etc/pve/lxc/<CT-ID>.conf`):

```
lxc.cgroup2.devices.allow: c 10:200 rwm
lxc.mount.entry: /dev/vhci dev/vhci none bind,optional,create=file
```

Container neu starten (`pct restart <ID>`). Anschließend im Container wie in einer VM: `apt install`, `modprobe` (diesmal nur als No-op), `usbip` oder `remoteusb`-Wrapper verwenden.

-----

## Architektur-Überblick

```
┌─────────────────── Pi Zero 2W ───────────────────┐
│                                                   │
│  usbipd ← udev (auto-bind)     ← USB-Geräte       │
│     ↑                                              │
│     │ TCP:3240                                     │
│  wlan0 ←→ hostapd (AP mode) XOR NetworkManager    │
│     │                        (Station mode)        │
│     ↓                                              │
│  wg0 (WireGuard Tunnel, optional)                  │
│     │                                              │
│  Watchdog: NM-Status + WG-Ping → LED-Status-File   │
│                                  ↑                 │
│  gpio_handler: LED + Taster -----┘                 │
│                                                    │
│  Persistenz: /boot/firmware/remoteusb-data.img     │
│    bind-mounted: /etc/remoteusb, /etc/wireguard,   │
│                  /etc/NetworkManager/system-connections │
└────────────────────────────────────────────────────┘

USB/IP Clients (VM, Laptop, LXC, Windows):
  usbip list -r <pi>     → enumeriert exportable Geräte
  usbip attach -r ...    → vhci-hcd macht Gerät lokal verfügbar
```

Siehe [CLAUDE.md](CLAUDE.md) für Details zu den Design-Entscheidungen, Code-Layout und dem Deploy-Workflow bei Änderungen.

-----

## Netzwerk-Rollen

- **Stationsmodus (Normalbetrieb):** wlan0 ist von NetworkManager gemanagt. WireGuard (wg0) zusätzlich falls für das aktuelle Netz aktiviert. SSH-Zugriff via wlan0-IP oder VPN-IP.
- **AP-Modus (Konfiguration):** NetworkManager lässt wlan0 los (`managed no`), hostapd übernimmt. DHCP via dnsmasq. Pi unter `192.168.4.1`. WireGuard aus. Webinterface aktiv.

Übergänge laufen sauber per `nmcli device set wlan0 managed no/yes` + expliziter Stop/Restart von hostapd + dnsmasq.

-----

## Updates / Änderungen deployen

Wegen des Read-only Root-FS überstehen einfache `cp`-Änderungen an `/usr/local/bin` den nächsten Reboot nicht. Persistenter Deploy:

```bash
# Auf dem Pi:
sudo raspi-config nonint disable_overlayfs
sudo reboot

# Nach Reboot:
cd ~/RemoteUSB && git pull
sudo ./install.sh            # oder manuelle cp-Kommandos für einzelne Dateien

sudo raspi-config nonint enable_overlayfs
sudo reboot
```

Alternativ vor Ort per SD-Kartenleser: Overlay nur temporär aus, dann normal deployen.

Die persistent bind-gemounteten Verzeichnisse (`/etc/remoteusb`, `/etc/wireguard`, NM-Connections) überleben Reboots auch mit aktivem Overlay, weil sie aus dem Image auf der Boot-Partition kommen.

-----

## Lizenz

Copyright (c) 2026 Marco Veric

Dieses Projekt steht unter der [GPL-3.0 Lizenz](LICENSE).

-----

## Acknowledgements

Dieses Projekt verwendet folgende Open-Source-Software:

| Komponente       | Lizenz        | Link                                      |
|------------------|---------------|-------------------------------------------|
| Linux USB/IP     | GPL-2.0       | https://www.kernel.org                    |
| WireGuard        | GPL-2.0       | https://www.wireguard.com                 |
| hostapd          | BSD / GPL-2.0 | https://w1.fi/hostapd                     |
| dnsmasq          | GPL-2.0       | https://thekelleys.org.uk/dnsmasq         |
| NetworkManager   | GPL-2.0       | https://networkmanager.dev                |
| Flask            | BSD-3-Clause  | https://flask.palletsprojects.com         |
| gpiozero         | BSD-3-Clause  | https://gpiozero.readthedocs.io           |
| Pillow           | HPND          | https://python-pillow.org                 |
| zxing-cpp        | Apache-2.0    | https://github.com/zxing-cpp/zxing-cpp    |
| Raspberry Pi OS  | Various       | https://www.raspberrypi.com/software      |
