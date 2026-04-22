#!/bin/bash
# =============================================================================
# RemoteUSB – USB/IP Autobind
# Bindet alle aktuell angesteckten Nicht-Hub USB-Geräte, außer sie stehen
# in der User-Blacklist (/etc/remoteusb/usb-exclude). Aufgerufen von:
#   - udev-Rule beim Hot-Plug
#   - usbipd-Service beim Start (für Geräte die schon beim Boot drin waren)
# =============================================================================

set -e

EXCLUDE_FILE=/etc/remoteusb/usb-exclude

is_excluded() {
    local busid="$1"
    [ -f "$EXCLUDE_FILE" ] || return 1
    grep -qxF "$busid" "$EXCLUDE_FILE"
}

# `usbip list -pl` liefert Zeilen wie: busid=1-1.4#usbid=0483:5740#
usbip list -pl 2>/dev/null | while IFS= read -r line; do
    busid=$(echo "$line" | sed -n 's/^busid=\([^#]*\)#.*/\1/p')
    [ -z "$busid" ] && continue
    is_excluded "$busid" && continue
    # Nur binden wenn noch nicht gebunden (vermeidet Fehlermeldungen)
    if [ ! -L "/sys/bus/usb/drivers/usbip-host/$busid" ]; then
        usbip bind -b "$busid" >/dev/null 2>&1 || true
    fi
done
