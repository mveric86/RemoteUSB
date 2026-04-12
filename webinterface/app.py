#!/usr/bin/env python3
# =============================================================================
# RemoteUSB – Webinterface Backend (Flask)
# Nur im AP-Modus erreichbar (http://192.168.4.1)
# =============================================================================

import os
import json
import subprocess
import signal
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# -----------------------------------------------------------------------------
# Dateipfade
# -----------------------------------------------------------------------------
NETWORKS_FILE   = "/etc/remoteusb/networks.json"
SETTINGS_FILE   = "/etc/remoteusb/settings.conf"
WG_CONFIG_FILE  = "/etc/wireguard/wg0.conf"

# -----------------------------------------------------------------------------
# Hilfsfunktionen – Netzwerke
# -----------------------------------------------------------------------------
def load_networks():
    try:
        with open(NETWORKS_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def save_networks(networks):
    with open(NETWORKS_FILE, "w") as f:
        json.dump(networks, f, indent=2)
    _apply_nm(networks)

NM_PREFIX = "remoteusb-"

def _nm_list_managed():
    """Namen aller NM-Verbindungen die uns gehören (remoteusb-*)."""
    result = subprocess.run(
        ["nmcli", "-t", "-f", "NAME", "connection", "show"],
        capture_output=True, text=True
    )
    return [n for n in result.stdout.splitlines() if n.startswith(NM_PREFIX)]

def _nm_delete_by_ssid(ssid):
    """Löscht NM-Verbindungen mit passender SSID (auch nicht von uns verwaltete)."""
    result = subprocess.run(
        ["nmcli", "-t", "-f", "NAME,802-11-wireless.ssid", "connection", "show"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        name, con_ssid = line.split(":", 1)
        if con_ssid == ssid:
            subprocess.run(["nmcli", "connection", "delete", name],
                           capture_output=True)

def _migrate_existing_nm():
    """Importiert bestehende NM-WLAN-Verbindungen nach networks.json
    falls dort noch nicht vorhanden. So tauchen z.B. per Raspberry Pi
    Imager (netplan) angelegte WLANs direkt in der UI auf.
    Wird einmalig beim Webinterface-Start aufgerufen.
    """
    existing = load_networks()
    existing_ssids = {n["ssid"] for n in existing}
    result = subprocess.run(
        ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
        capture_output=True, text=True
    )
    changed = False
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        name, ctype = line.split(":", 1)
        if ctype != "802-11-wireless" or name.startswith(NM_PREFIX):
            continue
        ssid_res = subprocess.run(
            ["nmcli", "-t", "-g", "802-11-wireless.ssid",
             "connection", "show", name],
            capture_output=True, text=True
        )
        ssid = ssid_res.stdout.strip()
        if not ssid or ssid in existing_ssids:
            continue
        psk_res = subprocess.run(
            ["nmcli", "-s", "-t", "-g", "802-11-wireless-security.psk",
             "connection", "show", name],
            capture_output=True, text=True
        )
        psk = psk_res.stdout.strip()
        existing.append({
            "ssid":          ssid,
            "password":      psk,
            "priority":      1,
            "disabled":      False,
            "use_wireguard": False,
        })
        existing_ssids.add(ssid)
        changed = True
    if changed:
        with open(NETWORKS_FILE, "w") as f:
            json.dump(existing, f, indent=2)
        _apply_nm(existing)

def _apply_nm(networks):
    """Synchronisiert NetworkManager-Verbindungen mit networks.json.

    Strategie: Alle remoteusb-* Connections löschen und aus networks.json
    neu anlegen. Deaktivierte Netze werden mit autoconnect=no angelegt,
    damit Passwort/Priorität erhalten bleiben.
    """
    for name in _nm_list_managed():
        subprocess.run(["nmcli", "connection", "delete", name],
                       capture_output=True)

    for net in networks:
        ssid = net["ssid"]
        con_name = f"{NM_PREFIX}{ssid}"
        # Auch fremde Connections mit gleicher SSID entfernen, sonst
        # konkurriert z.B. eine alte 'preconfigured'-Verbindung mit unserer.
        _nm_delete_by_ssid(ssid)
        cmd = [
            "nmcli", "connection", "add",
            "type", "wifi",
            "ifname", "wlan0",
            "con-name", con_name,
            "ssid", ssid,
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk", net["password"],
            "connection.autoconnect", "no" if net.get("disabled") else "yes",
            "connection.autoconnect-priority", str(net.get("priority", 1)),
        ]
        subprocess.run(cmd, capture_output=True)

# -----------------------------------------------------------------------------
# Hilfsfunktionen – Einstellungen
# -----------------------------------------------------------------------------
def load_settings():
    settings = {
        "LED_RED_BRIGHTNESS":   100,
        "LED_GREEN_BRIGHTNESS": 100,
        "LED_BLUE_BRIGHTNESS":  100,
    }
    try:
        with open(SETTINGS_FILE) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    if key.strip() in settings:
                        settings[key.strip()] = int(val.strip())
    except Exception:
        pass
    return settings

def save_settings(settings):
    lines = ["# RemoteUSB – Allgemeine Einstellungen"]
    for key, val in settings.items():
        lines.append(f"{key}={val}")
    with open(SETTINGS_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
    # GPIO Handler neu starten damit neue Helligkeit übernommen wird
    subprocess.run(["systemctl", "restart", "remoteusb-gpio.service"])

# -----------------------------------------------------------------------------
# Hilfsfunktionen – WireGuard
# -----------------------------------------------------------------------------
def load_wg_config():
    try:
        with open(WG_CONFIG_FILE) as f:
            return f.read()
    except Exception:
        return ""

def save_wg_config(content):
    # DNS-Zeilen entfernen – auf Trixie/NM fehlt resolvconf,
    # wg-quick bricht sonst ab und reißt das Interface wieder runter.
    lines = [l for l in content.splitlines() if not l.strip().startswith("DNS")]
    with open(WG_CONFIG_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")

# -----------------------------------------------------------------------------
# Routen – Hauptseite
# -----------------------------------------------------------------------------
# Captive-Portal-Catch-all: alle unbekannten Hosts/Pfade auf die Hauptseite.
# dnsmasq leitet im AP-Modus sämtliche DNS-Anfragen auf 192.168.4.1 um,
# also schlagen Captive-Portal-Checks der Handys (connectivitycheck.*,
# captive.apple.com, msftconnecttest.*) hier auf. Ohne Catch-all → 404 → hängt.
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def index(path):
    return render_template("index.html")

# -----------------------------------------------------------------------------
# Routen – Netzwerke
# -----------------------------------------------------------------------------
@app.route("/api/networks", methods=["GET"])
def get_networks():
    return jsonify(load_networks())

@app.route("/api/networks", methods=["POST"])
def add_network():
    data = request.json
    networks = load_networks()
    networks.append({
        "ssid":          data["ssid"],
        "password":      data["password"],
        "priority":      int(data.get("priority", 1)),
        "disabled":      bool(data.get("disabled", False)),
        "use_wireguard": bool(data.get("use_wireguard", True)),
    })
    save_networks(networks)
    return jsonify({"ok": True})

@app.route("/api/networks/<int:index>", methods=["PUT"])
def update_network(index):
    data = request.json
    networks = load_networks()
    if index < 0 or index >= len(networks):
        return jsonify({"ok": False, "error": "Index out of range"}), 400
    networks[index].update({
        "ssid":          data.get("ssid",          networks[index]["ssid"]),
        "password":      data.get("password",      networks[index]["password"]),
        "priority":      int(data.get("priority",  networks[index].get("priority", 1))),
        "disabled":      bool(data.get("disabled", networks[index].get("disabled", False))),
        "use_wireguard": bool(data.get("use_wireguard", networks[index].get("use_wireguard", True))),
    })
    save_networks(networks)
    return jsonify({"ok": True})

@app.route("/api/networks/<int:index>", methods=["DELETE"])
def delete_network(index):
    networks = load_networks()
    if index < 0 or index >= len(networks):
        return jsonify({"ok": False, "error": "Index out of range"}), 400
    networks.pop(index)
    save_networks(networks)
    return jsonify({"ok": True})

# -----------------------------------------------------------------------------
# Routen – Einstellungen (LED-Helligkeit)
# -----------------------------------------------------------------------------
@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())

@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.json
    settings = load_settings()
    for key in ["LED_RED_BRIGHTNESS", "LED_GREEN_BRIGHTNESS", "LED_BLUE_BRIGHTNESS"]:
        if key in data:
            val = int(data[key])
            if 0 <= val <= 100:
                settings[key] = val
    save_settings(settings)
    return jsonify({"ok": True})

# -----------------------------------------------------------------------------
# Routen – WireGuard
# -----------------------------------------------------------------------------
@app.route("/api/wireguard", methods=["GET"])
def get_wg_config():
    return jsonify({"config": load_wg_config()})

@app.route("/api/wireguard", methods=["POST"])
def update_wg_config():
    data = request.json
    save_wg_config(data.get("config", ""))
    return jsonify({"ok": True})

# -----------------------------------------------------------------------------
# Routen – WLAN-Scan
# -----------------------------------------------------------------------------
@app.route("/api/scan", methods=["GET"])
def scan_networks():
    """WLAN-Scan via iwlist – funktioniert unabhängig von NM-Management-Status."""
    try:
        result = subprocess.run(
            ["iwlist", "wlan0", "scan"],
            capture_output=True, text=True, timeout=15
        )
        ssids = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("ESSID:"):
                ssid = line.split('"', 2)[1] if '"' in line else ""
                if ssid and ssid not in ssids:
                    ssids.append(ssid)
        return jsonify({"ssids": ssids})
    except Exception as e:
        return jsonify({"ssids": [], "error": str(e)}), 500

# -----------------------------------------------------------------------------
# Routen – WireGuard QR-Code Upload
# -----------------------------------------------------------------------------
@app.route("/api/wireguard/qr", methods=["POST"])
def upload_wg_qr():
    try:
        import base64
        from PIL import Image
        import io
        import zxingcpp

        data = request.json.get("image", "")
        if "," in data:
            data = data.split(",", 1)[1]
        img_bytes = base64.b64decode(data)
        img = Image.open(io.BytesIO(img_bytes))
        results = zxingcpp.read_barcodes(img)
        if not results:
            return jsonify({"ok": False, "error": "Kein QR-Code erkannt"}), 400
        config_text = results[0].text
        save_wg_config(config_text)
        return jsonify({"ok": True, "config": config_text})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# -----------------------------------------------------------------------------
# Routen – AP-Modus beenden (Verbinden mit neuem WLAN)
# -----------------------------------------------------------------------------
@app.route("/api/connect", methods=["POST"])
def connect():
    """AP-Modus beenden und Watchdog wieder ins Station-Netz gehen lassen."""
    try:
        pid = int(open("/run/remoteusb/watchdog.pid").read().strip())
        os.kill(pid, signal.SIGUSR2)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        _migrate_existing_nm()
    except Exception as e:
        print(f"[WARN] NM-Migration fehlgeschlagen: {e}")
    app.run(host="0.0.0.0", port=80, debug=False)
