#!/bin/bash
# =============================================================================
# RemoteUSB – USB/IP Session-Release
# Kickt alle aktuell attached Clients: unbind aller gebundenen Geräte,
# dann rebind. Der Kernel schmeißt dabei jeden Client raus (sieht aus
# wie physisches Abziehen des USB-Geräts). Danach sind die Geräte
# wieder exportierbar für neue Clients.
# =============================================================================

set -e

# Alle aktuell gebundenen Geräte finden
busids=$(ls /sys/bus/usb/drivers/usbip-host/ 2>/dev/null | grep -vE '^(bind|unbind|module|uevent)$' || true)

if [ -z "$busids" ]; then
    echo "[release] keine gebundenen USB-Geräte."
    exit 0
fi

for busid in $busids; do
    echo "[release] unbind $busid"
    usbip unbind -b "$busid" >/dev/null 2>&1 || true
done

sleep 0.5

# Autobind-Script re-bindet alles (respektiert Exclude-Liste)
/usr/local/bin/remoteusb-usb-autobind.sh
echo "[release] fertig."
