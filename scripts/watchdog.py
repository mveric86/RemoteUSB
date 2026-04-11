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
    """Prüft ob für die aktuelle SSID WireGuard benötigt wird."""
    try:
        with open(WLAN_CONFIG) as f:
            networks = json.load(f)
        for net in networks:
            if net.get("ssid") == ssid:
                return net.get("use_wireguard", True)
        # SSID nicht in der Liste – AP-Modus starten
        return None
    except Exception:
        # Keine networks.json – AP-Modus starten
        return None

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
    subprocess.run(["systemctl", "start", "hostapd"])
    subprocess.run(["systemctl", "start", "dnsmasq"])
    subprocess.run(["systemctl", "start", "remoteusb-webinterface.service"])
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
    _ap_mode_active = False

# -----------------------------------------------------------------------------
# Hauptschleife
# -----------------------------------------------------------------------------
_wg_error_since = None
_no_ssid_count = 0
NO_SSID_THRESHOLD = 3  # 3 aufeinanderfolgende Fehlschläge (~15s) vor AP-Modus

def check():
    global _wg_error_since, _ap_mode_active, _no_ssid_count

    ssid = get_current_ssid()

    # Kein WLAN – erst nach mehreren Fehlschlägen in Folge reagieren
    if not ssid:
        _no_ssid_count += 1
        if _no_ssid_count < NO_SSID_THRESHOLD:
            print(f"[WARN] Kein SSID ({_no_ssid_count}/{NO_SSID_THRESHOLD}) – warte...")
            return
        if not _ap_mode_active:
            print("[INFO] Kein WLAN – AP-Modus wird gestartet.")
            start_ap_mode()
        else:
            set_status("no_wifi")
        return

    _no_ssid_count = 0

    # WLAN verbunden
    wg_required = is_wg_required(ssid)

    # SSID unbekannt → AP-Modus starten falls nicht bereits aktiv
    if wg_required is None:
        if not _ap_mode_active:
            print(f"[INFO] SSID '{ssid}' nicht in networks.json – AP-Modus wird gestartet.")
            start_ap_mode()
        return

    # SSID bekannt – AP-Modus beenden falls aktiv
    if _ap_mode_active:
        stop_ap_mode()

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
        set_status("wg_error")
        if _wg_error_since is None:
            _wg_error_since = time.time()
            print(f"[WARN] WireGuard nicht erreichbar – warte {WG_TIMEOUT}s...")
        elif time.time() - _wg_error_since >= WG_TIMEOUT:
            print("[WARN] WireGuard Timeout – AP-Modus wird gestartet.")
            start_ap_mode()
            _wg_error_since = None

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
    print("[INFO] AP-Modus wird erzwungen (Taster).")
    stop_ap_mode()  # reset falls bereits aktiv
    start_ap_mode()

signal.signal(signal.SIGUSR1, force_ap_mode)

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
