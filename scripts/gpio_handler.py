#!/usr/bin/env python3
# =============================================================================
# RemoteUSB – GPIO Handler
# Verwaltet RGB-LED (Software-PWM) und Taster (AP-Modus, Shutdown)
# =============================================================================

import time
import signal
import sys
import subprocess
from gpiozero import PWMLED, Button
from configparser import ConfigParser

# -----------------------------------------------------------------------------
# Konfiguration laden
# -----------------------------------------------------------------------------
SETTINGS_FILE = "/etc/remoteusb/settings.conf"

def load_settings():
    """Lädt LED-Helligkeitseinstellungen aus der Konfigurationsdatei."""
    config = ConfigParser()
    defaults = {
        "LED_RED_BRIGHTNESS":   "100",
        "LED_GREEN_BRIGHTNESS": "100",
        "LED_BLUE_BRIGHTNESS":  "100",
    }
    try:
        with open(SETTINGS_FILE) as f:
            # ConfigParser braucht einen Abschnitt – wir fügen einen dummy hinzu
            content = "[settings]\n" + f.read()
        config.read_string(content)
        return {
            "red":   int(config["settings"].get("LED_RED_BRIGHTNESS",   defaults["LED_RED_BRIGHTNESS"]))   / 100,
            "green": int(config["settings"].get("LED_GREEN_BRIGHTNESS", defaults["LED_GREEN_BRIGHTNESS"])) / 100,
            "blue":  int(config["settings"].get("LED_BLUE_BRIGHTNESS",  defaults["LED_BLUE_BRIGHTNESS"]))  / 100,
        }
    except Exception as e:
        print(f"[WARN] Einstellungen konnten nicht geladen werden: {e}. Verwende Standardwerte.")
        return {"red": 1.0, "green": 1.0, "blue": 1.0}

# -----------------------------------------------------------------------------
# GPIO-Pins (aus default.conf via Umgebungsvariablen oder Standardwerte)
# -----------------------------------------------------------------------------
import os

PIN_LED_RED   = int(os.environ.get("GPIO_LED_RED",         25))
PIN_LED_GREEN = int(os.environ.get("GPIO_LED_GREEN",       24))
PIN_LED_BLUE  = int(os.environ.get("GPIO_LED_BLUE",        23))
PIN_BTN_AP    = int(os.environ.get("GPIO_AP_BUTTON",        4))
PIN_BTN_SHUTDOWN = int(os.environ.get("GPIO_SHUTDOWN_BUTTON", 27))
BUTTON_HOLD_TIME = float(os.environ.get("BUTTON_HOLD_TIME",  2.0))

# -----------------------------------------------------------------------------
# LED initialisieren
# -----------------------------------------------------------------------------
led_red   = PWMLED(PIN_LED_RED)
led_green = PWMLED(PIN_LED_GREEN)
led_blue  = PWMLED(PIN_LED_BLUE)

# -----------------------------------------------------------------------------
# LED-Steuerung
# -----------------------------------------------------------------------------
_blink_active = False

def _apply_brightness(r, g, b):
    """Wendet Helligkeitsfaktor aus Einstellungen an."""
    settings = load_settings()
    led_red.value   = r * settings["red"]
    led_green.value = g * settings["green"]
    led_blue.value  = b * settings["blue"]

def _leds_off():
    """LEDs ausschalten ohne Blink-Status zu ändern."""
    led_red.off()
    led_green.off()
    led_blue.off()

def led_off():
    global _blink_active
    _blink_active = False
    _leds_off()

def led_set(r, g, b):
    """Setzt LED auf eine Farbe (Werte 0.0–1.0), stoppt Blinken."""
    global _blink_active
    _blink_active = False
    time.sleep(0.05)  # kurz warten bis Blink-Loop beendet
    _apply_brightness(r, g, b)

def led_blink(r, g, b, interval=0.5):
    """Lässt LED in einer Farbe blinken (blockierend, in eigenem Thread aufrufen)."""
    global _blink_active
    _blink_active = True
    while _blink_active:
        _apply_brightness(r, g, b)
        time.sleep(interval)
        if not _blink_active:
            break
        _leds_off()
        time.sleep(interval)

# -----------------------------------------------------------------------------
# Status-Farben (Convenience-Funktionen für den Watchdog)
# -----------------------------------------------------------------------------
def status_wg_connected():
    """Blau – WLAN + WireGuard verbunden"""
    led_set(0, 0, 1)

def status_wg_off():
    """Grün – WLAN verbunden, WireGuard nicht benötigt (Heimnetz)"""
    led_set(0, 1, 0)

def status_wg_error():
    """Gelb – WLAN verbunden, WireGuard nicht erreichbar"""
    led_set(1, 1, 0)

def status_no_wifi():
    """Rot – kein WLAN"""
    led_set(1, 0, 0)

def status_ap_mode():
    """Gelb blinkend – AP-Modus aktiv"""
    import threading
    threading.Thread(target=led_blink, args=(1, 1, 0, 0.5), daemon=True).start()

def status_shutdown():
    """Rot blinkend – Shutdown läuft"""
    import threading
    threading.Thread(target=led_blink, args=(1, 0, 0, 0.2), daemon=True).start()

# -----------------------------------------------------------------------------
# Taster
# -----------------------------------------------------------------------------
btn_ap       = Button(PIN_BTN_AP,       hold_time=BUTTON_HOLD_TIME, pull_up=True)
btn_shutdown = Button(PIN_BTN_SHUTDOWN, hold_time=BUTTON_HOLD_TIME, pull_up=True)

def on_ap_held():
    """AP-Modus erzwingen – signalisiert dem Watchdog per SIGUSR1."""
    print("[INFO] AP-Taster gehalten – AP-Modus wird erzwungen.")
    try:
        with open("/run/remoteusb/watchdog.pid") as f:
            wd_pid = int(f.read().strip())
        os.kill(wd_pid, signal.SIGUSR1)
    except Exception as e:
        print(f"[WARN] Konnte Watchdog nicht signalisieren: {e}")

def on_shutdown_held():
    """Langer Druck (≥ BUTTON_HOLD_TIME): Sauberer Shutdown."""
    global _shutdown_was_held
    _shutdown_was_held = True
    print("[INFO] Shutdown-Taster gehalten – System wird heruntergefahren.")
    status_shutdown()
    time.sleep(2)
    subprocess.run(["shutdown", "-h", "now"])

_shutdown_was_held = False

def on_shutdown_released():
    """Kurzer Druck (< BUTTON_HOLD_TIME): alle USB/IP-Sessions freigeben.
    Attached Clients werden gekickt, Geräte bleiben exportierbar."""
    global _shutdown_was_held
    if _shutdown_was_held:
        _shutdown_was_held = False
        return
    print("[INFO] Shutdown-Taster kurz gedrückt – USB-Sessions freigeben.")
    subprocess.run(["/usr/local/bin/remoteusb-usb-release.sh"])
    # Kurzer cyan-Flash als Bestätigung, dann zurück zum aktuellen Status
    import threading
    def flash():
        _apply_brightness(0, 1, 1)
        time.sleep(0.2)
        _leds_off()
        # poll_status setzt beim nächsten Tick den richtigen Status zurück
        global _last_status
        _last_status = None
    threading.Thread(target=flash, daemon=True).start()

btn_ap.when_held           = on_ap_held
btn_shutdown.when_held     = on_shutdown_held
btn_shutdown.when_released = on_shutdown_released

# -----------------------------------------------------------------------------
# Sauberes Beenden
# -----------------------------------------------------------------------------
def cleanup(signum=None, frame=None):
    print("[INFO] GPIO Handler beendet.")
    led_off()
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT,  cleanup)
signal.signal(signal.SIGUSR1, lambda s, f: None)  # Ignorieren – Status wird gepollt

# -----------------------------------------------------------------------------
# Status-Polling
# -----------------------------------------------------------------------------
STATUS_FILE = "/run/remoteusb/status"
_last_status = None

def poll_status():
    """Liest die Statusdatei alle 2 Sekunden und setzt die LED entsprechend."""
    global _last_status
    time.sleep(2)  # Warten bis Startanimation fertig
    while True:
        try:
            with open(STATUS_FILE) as f:
                status = f.read().strip()
            if status != _last_status:
                _last_status = status
                if status == "wg_connected":
                    status_wg_connected()
                elif status == "wg_off":
                    status_wg_off()
                elif status == "wg_error":
                    status_wg_error()
                elif status == "no_wifi":
                    status_no_wifi()
                elif status == "ap_mode":
                    status_ap_mode()
        except Exception:
            pass
        time.sleep(2)

# -----------------------------------------------------------------------------
# Main – wartet auf Ereignisse
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("[INFO] RemoteUSB GPIO Handler gestartet.")
    print(f"[INFO] AP-Taster: GPIO {PIN_BTN_AP}, Shutdown-Taster: GPIO {PIN_BTN_SHUTDOWN}")
    print(f"[INFO] LED: R={PIN_LED_RED}, G={PIN_LED_GREEN}, B={PIN_LED_BLUE}")

    # PID speichern
    os.makedirs("/run/remoteusb", exist_ok=True)
    with open("/run/remoteusb/gpio_handler.pid", "w") as f:
        f.write(str(os.getpid()))

    # Startanimation – alle Farben kurz aufleuchten
    for r, g, b in [(1,0,0), (0,1,0), (0,0,1)]:
        _apply_brightness(r, g, b)
        time.sleep(0.3)
    led_off()

    # Status-Polling in eigenem Thread
    import threading
    threading.Thread(target=poll_status, daemon=True).start()

    # Warten – LED-Status wird vom Watchdog gesetzt.
    # signal.pause() returnt bei JEDEM Signal (auch SIGUSR1 vom Watchdog),
    # daher in Schleife – nur SIGTERM/SIGINT beenden via cleanup() -> sys.exit().
    while True:
        signal.pause()
