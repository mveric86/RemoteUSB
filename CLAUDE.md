# CLAUDE.md – Entwickler-Doku für zukünftige Claude-Sessions

Diese Datei dokumentiert Kontext, Design-Entscheidungen und Stolperfallen des
RemoteUSB-Projekts, damit eine neue Claude-Session effizient weiterarbeiten
kann ohne alles nochmal zu erkunden.

## Kurzbeschreibung

RemoteUSB ist ein USB-over-IP-Server auf einem Raspberry Pi Zero 2W unter
Raspberry Pi OS Lite (Trixie). USB-Geräte werden via USB/IP-Protokoll über
WLAN oder einen WireGuard-Tunnel für beliebige Clients (Linux/Windows/VMs/LXCs)
nutzbar gemacht. Der Pi hat eine RGB-LED für Statusanzeige, zwei Taster
(AP-Modus, Shutdown) und ein kleines Flask-Webinterface fürs Konfigurieren.
Das Root-FS ist read-only (overlayroot), User-Config persistiert in einem
bind-gemounteten ext4-Image auf der FAT-Boot-Partition.

## Code-Layout

```
.
├── README.md                          – Nutzer-Doku
├── CLAUDE.md                          – diese Datei
├── install.sh                         – idempotenter Installer
├── config/
│   ├── default.conf                   – Haupt-Config (AP-SSID, GPIO-Pins, WG-Ping-Target)
│   ├── gpio.env                       – von install.sh aus default.conf generiert
│   └── watchdog.env                   – dito
├── scripts/
│   ├── watchdog.py                    – Hauptlogik: WLAN+WG-Status, AP-Mode-Transitions
│   ├── gpio_handler.py                – LED-Steuerung + Taster-Handling
│   ├── persist.sh                     – bind-mounts die Persistenz-Image-Verzeichnisse (Boot)
│   ├── usb-autobind.sh                – bindet alle angesteckten Nicht-Hub-Geräte an usbip_host
│   ├── usb-unbind.sh                  – unbind pro busid (via udev 'remove')
│   └── usb-release.sh                 – unbind+rebind aller Geräte (Session-Kick)
├── services/                          – systemd unit files, eine pro Script
├── udev/
│   └── 99-remoteusb-autobind.rules    – ACTION=add|remove → autobind/unbind
├── webinterface/
│   ├── app.py                         – Flask-Backend
│   └── templates/index.html           – SPA, Tabs: Netzwerke/LED/WireGuard/USB
├── client/
│   └── remoteusb                      – Bash-Wrapper für usbip list/attach/detach
└── cad/                               – Gehäuse STEP/3MF
```

## Design-Entscheidungen und deren Gründe

### Persistenz über Loop-backed Image statt zweiter Partition

Der Pi nutzt overlayroot=tmpfs → alle Änderungen an `/etc` oder `/usr/local/bin`
sind nach dem Reboot weg. Ursprünglich war Repartitionieren geplant, wurde aber
verworfen: (a) ISOs beim geplanten Imager-Feature werden per Stream direkt an
`dd` gepiped, brauchen also keinen Scratch-Space; (b) Repartitionieren zur
Laufzeit ist fragil. Stattdessen: 32 MB ext4-Image in `/boot/firmware/remoteusb-data.img`,
beim Boot per Loop gemountet, dann Bind-Mounts:

- `/var/lib/remoteusb-data/etc-remoteusb/`   → `/etc/remoteusb/`
- `/var/lib/remoteusb-data/nm-connections/`   → `/etc/NetworkManager/system-connections/`
- `/var/lib/remoteusb-data/etc-wireguard/`    → `/etc/wireguard/`

Siehe `scripts/persist.sh` + `services/remoteusb-persist.service`
(`Before=NetworkManager.service wg-quick@wg0.service remoteusb-*.service`).

### NetworkManager statt wpa_supplicant

Pi OS Trixie nutzt NetworkManager, nicht mehr direkt wpa_supplicant.
`wpa_supplicant.conf` wird von NM IGNORIERT. Alle WLAN-Verbindungen müssen als
NM-Connection unter `/etc/NetworkManager/system-connections/<name>.nmconnection`
existieren. Das Webinterface synchronisiert `networks.json` nach NM via
`nmcli connection add`, siehe `_apply_nm()` in `webinterface/app.py`.

Wichtige Quirks:

- **Offene WLANs** (kein Passwort): NM-Connection muss OHNE `wifi-sec.key-mgmt`
  erstellt werden, sonst lehnt NM ab. `_apply_nm` setzt wifi-sec nur wenn
  `password` gesetzt ist.
- **Vorkonfigurierte Connections** vom Raspberry Pi Imager liegen als
  `netplan-wlan0-<ssid>.nmconnection` vor. Beim Webinterface-Start läuft
  `_migrate_existing_nm()`, importiert diese nach `networks.json` und legt
  sie als `remoteusb-<ssid>` neu an.

### NetworkManager vs. hostapd Co-Existenz

wlan0 kann nur entweder Station-Mode (NM) ODER AP-Mode (hostapd) sein, nicht
beides. Transition in `scripts/watchdog.py`:

```
start_ap_mode():  nmcli device set wlan0 managed no
                  ip addr flush dev wlan0
                  ip addr add 192.168.4.1/24 dev wlan0
                  systemctl restart hostapd dnsmasq

stop_ap_mode():   systemctl stop hostapd dnsmasq
                  ip addr flush dev wlan0
                  nmcli device set wlan0 managed yes
```

**Wichtig: `systemctl restart` statt `start`** für hostapd, weil ein noch
laufender hostapd beim Interface-Wechsel zurückbleibt und systemctl start
dann no-op ist (Service bereits aktiv) – aber das Radio ist tot. Siehe
git log: „start_ap_mode: hostapd/dnsmasq explizit stoppen vor Interface-Reconfig".

### Kein AP-Fallback bei WG-Fehlern

Ursprüngliches Design: watchdog kippt nach `WG_TIMEOUT` (30 s) in AP-Modus
wenn der WG-Tunnel nicht erreichbar ist. Für remote deployte Geräte (genau
der Use-Case) ist das katastrophal: kurze Funkhänger → Pi im AP-Modus →
unerreichbar. Aktuelle Logik (`scripts/watchdog.py:check()`):

- Kein SSID + `has_wifi_configured()` → nur LED rot, kein AP-Wechsel
- Kein SSID + KEINE WLAN-Config → AP-Modus für Ersteinrichtung
- WG unerreichbar → LED gelb (`wg_error`), Retry jeden Check-Interval, KEIN AP

AP-Modus nur noch über Taster erzwingbar (`SIGUSR1` vom gpio_handler).

### Captive-Portal-Unterdrückung

Beim Verbinden mit dem AP detektiert iOS/Android/Windows einen Captive-Portal
(dnsmasq leitet alle DNS-Requests auf 192.168.4.1, Flask catch-all serviert
die Hauptseite). iOS öffnet die Captive-Portal-WebView (gesperrt: Dateiupload,
Kamera) und trennt die Verbindung sobald der User das Sheet schließt.

Lösung in `webinterface/app.py:handle_captive_portal()`: `@app.before_request`
erkennt externe Host-Header und liefert die OS-erwartete Erfolgs-Antwort
(Apple: HTML mit `<TITLE>Success</TITLE>`, Android: HTTP 204, Windows: Text).
Das OS denkt „online", zeigt kein Portal-Sheet, User kann frei SSH/Browser
nutzen. Anfragen an 192.168.4.1/localhost laufen normal durch.

### USB/IP Autobind per udev

Statt manuellem `usbip bind --busid=...` pro Gerät: udev-Rule
`99-remoteusb-autobind.rules` fired bei USB-Add-Events auf Nicht-Hubs
(`ATTR{bDeviceClass}!="09"`), ruft `usb-autobind.sh` auf, das alle aktuell
angesteckten bind-baren Geräte einbindet (außer sie stehen in
`/etc/remoteusb/usb-exclude`). Auf Remove-Event: `usb-unbind.sh <busid>`.

Ergänzend ruft `usbipd.service` beim Start `usb-autobind.sh` auf, um Geräte
nachzuholen, die schon beim Boot gesteckt waren (udev-Rules fire nur bei
neuen Events, nicht für bereits vorhandene Geräte).

### Client-Wrapper `client/remoteusb`

Bash-Script, kapselt drei usbip-Eigenheiten:
- **Busid-Discovery**: Match per Index, exakter busid oder Name-Substring
- **Parser für `usbip list -r`**: Regex-basiert, case-insensitive Name-Match
- **Sauberes Detach**: `trap cleanup EXIT`, Port-Lookup beim Detach (nicht
  beim Attach, wegen Kernel-State-Propagation-Delay), Polling alle 2 s ob die
  busid noch in `usbip port` steht – wenn der Server released (z.B. durch
  Short-Press-Taster), beendet sich das Script selbst.

Ubuntu-Quirk: `linux-tools-generic` ist nur Meta-Paket. Das Script versucht
zuerst `command -v usbip`, dann `/usr/lib/linux-tools/$(uname -r)/usbip`,
dann `sort -V | tail -1` auf alle vorhandenen Versions-Ordner.

## Systemd-Services und Ordering

```
multi-user.target
├── remoteusb-persist.service        (Type=oneshot; mountet Image, bind-mounts)
│   Before=NetworkManager.service wg-quick@wg0.service remoteusb-*.service
├── remoteusb-gpio.service           (LED + Taster; poll_status liest /run/remoteusb/status)
├── remoteusb-watchdog.service       (WLAN+WG-Logik; schreibt /run/remoteusb/status)
│   After=network-online.target remoteusb-gpio.service
├── remoteusb-usbipd.service         (Type=forking; modprobe + usbipd -D + autobind)
└── remoteusb-webinterface.service   (NICHT WantedBy=multi-user.target;
                                      wird vom watchdog bei start_ap_mode gestartet)
```

Persistenz-Service kommt VOR allem anderen, damit NM seine Connections aus dem
Image liest und der Watchdog seine networks.json findet.

Watchdog hat `Wants=network-online.target`, sonst startet er evtl. bevor NM
die erste Connection oben hat.

## Inter-Process-Kommunikation

PID-Dateien:
- `/run/remoteusb/watchdog.pid` ← watchdog schreibt sich rein
- `/run/remoteusb/gpio_handler.pid` ← gpio_handler schreibt sich rein

Status-Datei:
- `/run/remoteusb/status` ← watchdog schreibt, gpio_handler pollt alle 2 s

Signale:
- `SIGUSR1` → watchdog: AP-Modus toggle (vom gpio_handler bei langem AP-Taster)
- `SIGUSR2` → watchdog: Force-AP beenden (vom Webinterface „AP beenden")

Shellskripte:
- `/usr/local/bin/remoteusb-usb-release.sh` ← vom gpio_handler bei kurzem
  Shutdown-Taster und vom Webinterface `/api/usb/release`

## Webinterface-API

- `GET /api/networks` → Array von Network-Objekten aus `networks.json`
- `POST /api/networks` → Neues Netz, triggert `_apply_nm`
- `PUT/DELETE /api/networks/<index>` → Bearbeiten/Löschen
- `GET /api/scan` → iwlist-basierter Scan (funktioniert auch während AP-Modus)
- `GET /api/wireguard` / `POST /api/wireguard` → wg0.conf lesen/schreiben
  (beim Save werden DNS-Zeilen entfernt, weil resolvconf auf Trixie fehlt)
- `POST /api/wireguard/qr` → QR-Bild → zxingcpp → wg0.conf
- `GET/POST /api/settings` → LED-Helligkeit
- `POST /api/connect` → SIGUSR2 an watchdog (AP beenden)
- `GET /api/usb` → Liste angesteckter Nicht-Hub-Geräte mit Bind-Status
- `POST /api/usb/<busid>/toggle` → Exclude-Flag umschalten, unbind/rebind
- `POST /api/usb/release` → `usb-release.sh` aufrufen
- Captive-Portal-Checks (non-eigener Host) → vor allen Routes abgefangen

Alle Templates-Endpoints sind Catch-all (`/<path:path>`) → HTML-Seite, damit
Captive-Portal-Redirects landen.

## Overlay-Dance (Deploy-Workflow)

Standardablauf um Code-Änderungen reboot-fest zu bekommen:

```bash
sudo raspi-config nonint disable_overlayfs  # cmdline.txt ohne overlayroot=tmpfs
sudo reboot

# Nach Reboot: rootfs ist ext4 rw. Deployen:
cd ~/RemoteUSB && git pull
sudo cp scripts/*.py scripts/*.sh /usr/local/bin/     # mit remoteusb-Präfix ggf. umbenennen
sudo cp services/*.service /etc/systemd/system/
sudo cp udev/*.rules /etc/udev/rules.d/
sudo cp webinterface/app.py /opt/remoteusb/webinterface/app.py
sudo cp webinterface/templates/index.html /opt/remoteusb/webinterface/templates/index.html
# ggf. systemctl daemon-reload + udevadm control --reload-rules

sudo raspi-config nonint enable_overlayfs
sudo reboot
```

**Vor-Ort-Variante** via SD-Kartenleser: `cmdline.txt` auf der Boot-FAT-Partition
editieren, `overlayroot=tmpfs` entfernen. Nach dem Deployen wieder einfügen.

Bind-gemountete Persistenz-Daten (`/etc/remoteusb`, `/etc/wireguard`, NM-Connections)
überleben Reboots mit aktivem Overlay, weil sie aus dem Image kommen.

## Stolperfallen (die uns wirklich passiert sind)

### `init=/boot/firmware/fix.sh` funktioniert nicht
FAT-Dateisysteme haben keine Unix-Execute-Permissions; der RPi-OS-Mount gibt
Files 0644. Kernel verweigert `execve` auf non-executable File. Hat in einem
Cafe-Debug dafür gesorgt dass ein Notfall-Bootscript nicht lief.

### `signal.pause()` returnt bei jedem Signal
Im gpio_handler returnte `signal.pause()` sobald der watchdog SIGUSR1 zum
Status-Update sendete (selbst wenn der Handler nichts tut). Fix: `while True: signal.pause()`.

### `led_off()` in `led_blink()`-Loop setzt `_blink_active=False`
Deshalb blinkte die gelbe LED nur einmal und ging dann aus. Fix: separate
`_leds_off()` ohne Flag-Seiteneffekt für die Blink-Schleife, `led_off()` nur
für „richtig ausschalten".

### `wg-quick up wg0` scheitert wenn `DNS=` in Config steht
Fritzbox-exportierte `.conf` enthält DNS-Zeilen, wg-quick versucht die via
resolvconf zu setzen, das fehlt auf Trixie/NM. Fix: `save_wg_config` filtert
DNS-Zeilen raus.

### Fritzbox-Fernzugang-Peers im LAN-Subnet nicht erreichbar
Fritzbox vergibt VPN-Peer-IPs aus dem LAN-Subnet, macht aber kein Proxy-ARP.
LAN-Geräte können den Peer nicht erreichen. Lösung: **Site-to-Site-Konfiguration**
mit separatem Subnet (z.B. 192.168.199.0/30).

### Watchdog auto-start schlug fehl wenn gpio-service `After=multi-user.target` hatte
Widerspricht sich mit `WantedBy=multi-user.target` – systemd-Ordering konfus,
watchdog (per `After=remoteusb-gpio.service`) wurde nicht gestartet. Fix:
`After=multi-user.target` entfernt.

### USB-BusIDs sind nicht stabil
Beim Wechsel auf einen anderen USB-Port ändert sich die busid. Früher band
der usbipd-Service beim Start nur das erste Gerät, alles Danach-Gesteckte war
unsichtbar. Fix: udev-Autobind.

### Double-Trap in Client-Wrapper
`trap cleanup EXIT INT TERM` → INT löste cleanup aus, EXIT danach nochmal →
zweite cleanup findet nichts mehr → irreführende Warnung. Fix: `trap cleanup EXIT`
reicht, EXIT fired nach INT/TERM ohnehin.

## Offene Punkte / Wunschliste

- **Fresh-Install-Test**: install.sh auf einer leeren SD einmal komplett
  durchlaufen lassen. Noch nicht passiert.
- **Imager-Feature**: ISO-Upload im Webinterface, per Stream direkt an
  `dd of=/dev/sda`. Kein Disk-Scratch nötig. Noch nicht implementiert.
- **Session-Management**: Webinterface zeigt aktuell attached Clients,
  Force-Release per Knopfdruck pro Session. Aktuell nur global
  („Alle Sessions freigeben").
- **LED-Defaults**: Rot-Kanal ist oft dimmer als Grün – Defaults in
  `config/default.conf` (aktuell alle 100 %) könnten besser vor-kalibriert
  werden (z.B. Grün/Blau auf 40, Rot bei 100).

## Hinweise für die Deploy-Arbeit

Adressen und Zugangsdaten des konkreten Pi sind Nutzer-spezifisch und werden
**nicht** hier dokumentiert. Bei einer neuen Session fragt Claude den Nutzer
oder findet sie im Chat-Kontext.

Allgemein nützliche Hinweise:

- **Volatiler Deploy zum Testen**: einfach `scp` ins overlay-upper +
  `systemctl restart` der betroffenen Services, ohne Overlay-Dance. Ein Reboot
  revertiert dann. Sehr nützlich wenn man sich Risiko-Deploys ohne Persistenz
  traut und nicht auszusperren droht.
- **Mirror-Delay bei GitHub**: Wenn das Repo über einen selbst gehosteten
  Git-Server (Gitea/Forgejo) nach GitHub gespiegelt wird, hinkt
  `raw.githubusercontent.com` dem Push oft 1–2 Minuten hinterher. Bei
  Cache-Tests Cache-Bust (`?$(date +%s)` Parameter) nutzen oder kurz warten.
- **Zwei-Reboot-Overlay-Dance ist der Standardweg**: disable_overlayfs →
  reboot → deploy → enable_overlayfs → reboot. Siehe vorherige Sektion.
- **Remote-Deploy via WG**: Der Pi ist via WireGuard unter seiner Tunnel-IP
  erreichbar. Man kann das Overlay auch remote ausschalten. Wenn etwas
  schiefgeht, muss der Nutzer physisch eingreifen – also vorher checken,
  dass die persistenten Dateien (`/etc/remoteusb`, NM-Connections,
  `wg0.conf`) alle im Image-Layer liegen, damit der Pi nach dem ersten
  Reboot auch ohne Overlay wieder ins WLAN und den Tunnel findet.
