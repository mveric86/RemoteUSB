#!/bin/bash
# =============================================================================
# RemoteUSB – Install Script
# =============================================================================
# Dieses Script richtet den Raspberry Pi Zero 2W als mobilen USB/IP-Server ein.
# Voraussetzung: Raspberry Pi OS Lite, SSH-Zugang, Internetverbindung
# =============================================================================

set -e  # Bei Fehler abbrechen

# -----------------------------------------------------------------------------
# Farben für Ausgabe
# -----------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log()    { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()   { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# -----------------------------------------------------------------------------
# Root-Check
# -----------------------------------------------------------------------------
if [ "$EUID" -ne 0 ]; then
    error "Bitte als root ausführen: sudo ./install.sh"
fi

# -----------------------------------------------------------------------------
# Konfiguration laden
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$SCRIPT_DIR/config/default.conf"

if [ ! -f "$CONFIG" ]; then
    error "Konfigurationsdatei nicht gefunden: $CONFIG"
fi

source "$CONFIG"

log "Konfiguration geladen: $CONFIG"
log "AP-SSID: $AP_SSID"
log "AP-IP:   $AP_IP"

# -----------------------------------------------------------------------------
# Schritt 1: System aktualisieren
# -----------------------------------------------------------------------------
log "Schritt 1/8: System aktualisieren..."
apt-get update -qq
apt-get upgrade -y -qq

# -----------------------------------------------------------------------------
# Schritt 2: Pakete installieren
# -----------------------------------------------------------------------------
log "Schritt 2/8: Pakete installieren..."
apt-get install -y -qq \
    usbip \
    wireguard \
    wireguard-tools \
    hostapd \
    dnsmasq \
    python3 \
    python3-pip \
    python3-gpiozero \
    python3-flask \
    python3-pil \
    wireless-tools \
    git

# QR-Code Bibliothek via pip
pip3 install zxing-cpp --break-system-packages

# -----------------------------------------------------------------------------
# Schritt 3: Kernel-Module für USB/IP einrichten
# -----------------------------------------------------------------------------
log "Schritt 3/8: Kernel-Module einrichten..."
grep -qxF 'usbip_core' /etc/modules || echo 'usbip_core' >> /etc/modules
grep -qxF 'usbip_host' /etc/modules || echo 'usbip_host' >> /etc/modules
grep -qxF 'vhci-hcd'   /etc/modules || echo 'vhci-hcd'   >> /etc/modules

# -----------------------------------------------------------------------------
# Schritt 4: Persistente Verzeichnisse anlegen
# -----------------------------------------------------------------------------
log "Schritt 4/8: Persistente Verzeichnisse anlegen..."
mkdir -p /etc/remoteusb
mkdir -p /etc/wireguard
mkdir -p /etc/wpa_supplicant

# Leere Netzwerk-Liste anlegen falls nicht vorhanden
# → ohne networks.json keine WireGuard-Zuordnung, ohne WLAN → AP-Modus
if [ ! -f /etc/remoteusb/networks.json ]; then
    echo "[]" > /etc/remoteusb/networks.json
fi

# Standard-Einstellungen anlegen falls nicht vorhanden
if [ ! -f /etc/remoteusb/settings.conf ]; then
    cat > /etc/remoteusb/settings.conf <<EOF
# RemoteUSB – Allgemeine Einstellungen
LED_RED_BRIGHTNESS=100
LED_GREEN_BRIGHTNESS=100
LED_BLUE_BRIGHTNESS=100
EOF
fi

# -----------------------------------------------------------------------------
# Schritt 5: Scripts deployen
# -----------------------------------------------------------------------------
log "Schritt 5/8: Scripts deployen..."
cp "$SCRIPT_DIR/scripts/watchdog.py"         /usr/local/bin/remoteusb-watchdog.py
cp "$SCRIPT_DIR/scripts/gpio_handler.py"     /usr/local/bin/remoteusb-gpio.py
chmod +x /usr/local/bin/remoteusb-watchdog.py
chmod +x /usr/local/bin/remoteusb-gpio.py

# Webinterface deployen
mkdir -p /opt/remoteusb/webinterface
cp -r "$SCRIPT_DIR/webinterface/"* /opt/remoteusb/webinterface/

# -----------------------------------------------------------------------------
# Schritt 6: Systemd-Services einrichten
# -----------------------------------------------------------------------------
log "Schritt 6/8: Systemd-Services einrichten..."
cp "$SCRIPT_DIR/services/"*.service /etc/systemd/system/

# .env Dateien aus default.conf generieren
cat > /etc/remoteusb/gpio.env <<EOF
GPIO_LED_RED=$GPIO_LED_RED
GPIO_LED_GREEN=$GPIO_LED_GREEN
GPIO_LED_BLUE=$GPIO_LED_BLUE
GPIO_AP_BUTTON=$GPIO_AP_BUTTON
GPIO_SHUTDOWN_BUTTON=$GPIO_SHUTDOWN_BUTTON
BUTTON_HOLD_TIME=$BUTTON_HOLD_TIME
EOF

cat > /etc/remoteusb/watchdog.env <<EOF
WG_PING_TARGET=$WG_PING_TARGET
WG_TIMEOUT=$WG_TIMEOUT
EOF

systemctl daemon-reload
systemctl enable remoteusb-watchdog.service
systemctl enable remoteusb-gpio.service
systemctl enable remoteusb-usbipd.service

# -----------------------------------------------------------------------------
# Schritt 7: hostapd + dnsmasq konfigurieren
# -----------------------------------------------------------------------------
log "Schritt 7/8: AP-Modus konfigurieren (SSID: $AP_SSID)..."

cat > /etc/hostapd/hostapd.conf <<EOF
interface=wlan0
driver=nl80211
ssid=$AP_SSID
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=$AP_PASSWORD
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# hostapd Konfigurationsdatei referenzieren
sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

cat > /etc/dnsmasq.conf <<EOF
interface=wlan0
dhcp-range=$AP_DHCP_START,$AP_DHCP_END,255.255.255.0,24h
address=/#/$AP_IP
EOF

# hostapd und dnsmasq nicht beim Boot starten – nur bei Bedarf per Watchdog
# Trixie maskiert hostapd bei disable → vorher unmasken, danach erneut unmasken
systemctl unmask hostapd
systemctl disable hostapd
systemctl unmask hostapd
systemctl disable dnsmasq

# -----------------------------------------------------------------------------
# Schritt 8: Read-only Filesystem einrichten
# -----------------------------------------------------------------------------
log "Schritt 8/8: Read-only Filesystem einrichten..."
warn "Das System wird nach dem Neustart read-only sein."
warn "Änderungen an der Konfiguration nur über das Webinterface im AP-Modus."

# overlayfs über raspi-config aktivieren
raspi-config nonint enable_overlayfs

# -----------------------------------------------------------------------------
# Abschluss
# -----------------------------------------------------------------------------
echo ""
log "Installation abgeschlossen!"
log "Das Gerät startet neu und ist danach betriebsbereit."
log "WireGuard über das Webinterface im AP-Modus konfigurieren:"
log "  1. Mit WLAN '$AP_SSID' verbinden"
log "  2. Browser öffnen: http://$AP_IP"
echo ""
read -p "Jetzt neu starten? (j/n): " REBOOT
if [ "$REBOOT" = "j" ]; then
    reboot
fi
