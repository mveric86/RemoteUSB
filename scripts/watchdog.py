#!/usr/bin/env python3
# =============================================================================
# RemoteUSB – Watchdog
# Überwacht WLAN- und WireGuard-Verbindung, steuert LED-Status und AP-Modus
# =============================================================================

import os
import time
import signal
import sys
import subprocess
import json

# -----------------------------------------------------------------------------
# Konfiguration
# -----------------------------------------------------------------------------
WG_PING_TARGET  = os.environ.get("WG_PING_TARGET", "10.0.0.1")
WG_TIMEOUT      = int(os.environ.get("WG_TIMEOUT", 30))
CHECK_INTERVAL  = 5   # Sekunden zwischen Prüfungen
WLAN_CONFIG     = "/etc/remoteusb/networks.json"

# -----------------------------------------------------------------------------
# LED-Status über gpio_handler kommunizieren (via Signale / Statusdatei)
# -----------------------------------------------------------------------------
STATUS_FILE = "/run/remoteusb/status"

def set_status(status):
    """Schreibt aktuellen Status in Statusdatei für gpio_handler."""
    os.makedirs("/run/remoteusb", exist_ok=True)
    with open(STATUS_FILE, "w") as f:
        f.write(status)
    # gpio_handler per Signal benachrichtigen
    try:
        pid = int(open("/run/remoteusb/gpio_handler.pid").read().strip())
        os.kill(pid, signal.SIGUSR1)
    except Exception:
        pass

# -----------------------------------------------------------------------------
# WLAN-Hilfsfunktionen
# -----------------------------------------------------------------------------
def get_current_ssid():
    """Gibt die aktuell verbundene SSID zurück, oder None."""
    try:
        result = subprocess.run(
            ["iwgetid", "-r"],
            capture_output=True, text=True, timeout=5
        )
        ssid = result.stdout.strip()
        return ssid if ssid else None
    except Exception:
        return None

def is_wg_required(ssid):
    """Prüft ob für die aktuelle SSID WireGuard benötigt wird.

    Rückgabewerte:
      True  – WireGuard benötigt
      False – kein WireGuard (oder SSID unbekannt → Default)

    Unbekannte SSIDs werden nicht mehr als AP-Modus-Trigger behandelt,
    damit die Bridge direkt nach dem Flashen mit vorkonfiguriertem WLAN
    funktioniert. Zuordnung kann später über das Webinterface erfolgen.
    """
    try:
        with open(WLAN_CONFIG) as f:
            networks = json.load(f)
        for net in networks:
            if net.get("ssid") == ssid:
                return net.get("use_wireguard", False)
    except Exception:
        pass
    return False

def has_wifi_configured():
    """Prüft ob NetworkManager mindestens eine WLAN-Verbindung kennt.
    Wenn ja, ist der Pi 'vorkonfiguriert' und soll bei Verbindungsproblemen
    NICHT automatisch in den AP-Modus fallen – nur per Taster.
    """
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "TYPE", "connection", "show"],
            capture_output=True, text=True, timeout=5
        )
        return any(line.strip() == "802-11-wireless"
                   for line in result.stdout.splitlines())
    except Exception:
        return False

def is_wg_connected():
    """Prüft ob WireGuard-Verbindung aktiv ist (Ping auf WG-Server)."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "3", WG_PING_TARGET],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False

WG_CONFIG = "/etc/wireguard/wg0.conf"

def is_wg_interface_up():
    """Prüft ob wg0 als Interface existiert."""
    result = subprocess.run(
        ["ip", "link", "show", "wg0"],
        capture_output=True
    )
    return result.returncode == 0

def start_wireguard():
    """Startet WireGuard – nur wenn Konfiguration existiert."""
    if not os.path.exists(WG_CONFIG):
        return
    if is_wg_interface_up():
        return
    subprocess.run(["wg-quick", "up", "wg0"], capture_output=True)

def stop_wireguard():
    """Stoppt WireGuard – nur wenn Interface aktiv."""
    if not is_wg_interface_up():
        return
    subprocess.run(["wg-quick", "down", "wg0"], capture_output=True)

# -----------------------------------------------------------------------------
# AP-Modus
# -----------------------------------------------------------------------------
_ap_mode_active = False

def start_ap_mode():
    global _ap_mode_active
    if _ap_mode_active:
        return
    print("[INFO] AP-Modus wird gestartet...")
    stop_wireguard()
    # Alte hostapd/dnsmasq-Instanzen unbedingt killen – sonst hängt ein
    # toter Radio-State am Interface und der AP sendet nicht mehr.
    subprocess.run(["systemctl", "stop", "hostapd"], capture_output=True)
    subprocess.run(["systemctl", "stop", "dnsmasq"], capture_output=True)
    # wlan0 aus NetworkManager lösen damit hostapd es übernehmen kann
    subprocess.run(["nmcli", "device", "set", "wlan0", "managed", "no"],
                   capture_output=True)
    time.sleep(1)
    subprocess.run(["ip", "addr", "flush", "dev", "wlan0"], capture_output=True)
    subprocess.run(["ip", "addr", "add", "192.168.4.1/24", "dev", "wlan0"],
                   capture_output=True)
    subprocess.run(["ip", "link", "set", "wlan0", "up"], capture_output=True)
    subprocess.run(["systemctl", "restart", "hostapd"])
    subprocess.run(["systemctl", "restart", "dnsmasq"])
    subprocess.run(["systemctl", "restart", "remoteusb-webinterface.service"])
    _ap_mode_active = True
    set_status("ap_mode")

def stop_ap_mode():
    global _ap_mode_active
    if not _ap_mode_active:
        return
    print("[INFO] AP-Modus wird beendet...")
    subprocess.run(["systemctl", "stop", "remoteusb-webinterface.service"])
    subprocess.run(["systemctl", "stop", "dnsmasq"])
    subprocess.run(["systemctl", "stop", "hostapd"])
    subprocess.run(["ip", "addr", "flush", "dev", "wlan0"], capture_output=True)
    subprocess.run(["nmcli", "device", "set", "wlan0", "managed", "yes"],
                   capture_output=True)
    _ap_mode_active = False

# -----------------------------------------------------------------------------
# Hauptschleife
# -----------------------------------------------------------------------------
_wg_error_since = None
_no_ssid_count = 0
_force_ap = False   # wird vom AP-Taster (SIGUSR1) gesetzt, bleibt bis Reboot
NO_SSID_THRESHOLD = 3  # 3 aufeinanderfolgende Fehlschläge (~15s) vor AP-Modus

def check():
    global _wg_error_since, _ap_mode_active, _no_ssid_count

    # AP-Modus wurde per Taster erzwungen – nicht verlassen
    if _force_ap:
        if not _ap_mode_active:
            start_ap_mode()
        else:
            set_status("ap_mode")
        return

    ssid = get_current_ssid()

    # Kein WLAN verbunden
    # Im AP-Modus liefert iwgetid leer weil wlan0 im Master-Mode ist –
    # Status NICHT zu no_wifi ändern, sonst LED rot statt gelb blinkend.
    if not ssid:
        if _ap_mode_active:
            set_status("ap_mode")
            return
        # AP-Fallback nur wenn NetworkManager GAR KEIN WLAN kennt
        # (Ersteinrichtung). Sonst LED rot, aber kein Modus-Wechsel –
        # sonst kommt man remote nie wieder an den Pi ran.
        set_status("no_wifi")
        if not has_wifi_configured():
            _no_ssid_count += 1
            if _no_ssid_count < NO_SSID_THRESHOLD:
                print(f"[INFO] Kein WLAN konfiguriert ({_no_ssid_count}/{NO_SSID_THRESHOLD}) – Ersteinrichtung...")
                return
            print("[INFO] Keine WLAN-Konfiguration – AP-Modus für Ersteinrichtung.")
            start_ap_mode()
        return

    _no_ssid_count = 0

    # WLAN verbunden – AP-Modus beenden falls aktiv
    if _ap_mode_active:
        stop_ap_mode()

    wg_required = is_wg_required(ssid)

    # WireGuard nicht benötigt (z.B. Heimnetz)
    if not wg_required:
        stop_wireguard()
        set_status("wg_off")
        _wg_error_since = None
        return

    # WireGuard benötigt – sicherstellen dass es läuft
    start_wireguard()

    if is_wg_connected():
        set_status("wg_connected")
        _wg_error_since = None
    else:
        # Kein AP-Fallback mehr – WG-Fehler löst nur LED gelb aus,
        # Tunnel wird bei jedem Intervall erneut geprüft. Für remote
        # deployte Geräte ist AP-Modus hier kontraproduktiv.
        set_status("wg_error")
        if _wg_error_since is None:
            _wg_error_since = time.time()
            print("[WARN] WireGuard nicht erreichbar – Retry läuft.")

# -----------------------------------------------------------------------------
# Sauberes Beenden
# -----------------------------------------------------------------------------
def cleanup(signum=None, frame=None):
    print("[INFO] Watchdog beendet.")
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT,  cleanup)

# -----------------------------------------------------------------------------
# AP-Modus erzwingen (Signal von gpio_handler via systemd)
# -----------------------------------------------------------------------------
def force_ap_mode(signum=None, frame=None):
    """AP-Modus-Taster: toggelt zwischen Force-AP und normalem Betrieb."""
    global _force_ap
    if _force_ap:
        print("[INFO] AP-Modus-Toggle AUS – kehre zu normalem Betrieb zurück.")
        _force_ap = False
        stop_ap_mode()
        # check() läuft beim nächsten Intervall und setzt den richtigen Status
    else:
        print("[INFO] AP-Modus-Toggle AN – Taster erzwungen.")
        _force_ap = True
        start_ap_mode()

signal.signal(signal.SIGUSR1, force_ap_mode)

def exit_force_ap(signum=None, frame=None):
    """Wird vom Webinterface nach 'mit Netz verbinden' gesendet."""
    global _force_ap
    print("[INFO] Force-AP-Exit angefordert (Webinterface).")
    _force_ap = False
    stop_ap_mode()

signal.signal(signal.SIGUSR2, exit_force_ap)

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"[INFO] RemoteUSB Watchdog gestartet.")
    print(f"[INFO] WireGuard Ping-Target: {WG_PING_TARGET}")
    print(f"[INFO] WireGuard Timeout: {WG_TIMEOUT}s")

    # PID speichern
    os.makedirs("/run/remoteusb", exist_ok=True)
    with open("/run/remoteusb/watchdog.pid", "w") as f:
        f.write(str(os.getpid()))

    while True:
        try:
            check()
        except Exception as e:
            print(f"[ERROR] Watchdog-Fehler: {e}")
        time.sleep(CHECK_INTERVAL)
