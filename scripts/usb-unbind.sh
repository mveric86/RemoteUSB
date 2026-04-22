#!/bin/bash
# =============================================================================
# RemoteUSB – USB/IP Unbind-Helper
# Löst ein USB-Gerät aus der usbip_host-Bindung (via udev beim Abziehen
# oder manuell). Fehler werden geschluckt, weil Gerät beim remove-Event
# evtl. schon weg ist.
# =============================================================================

busid="$1"
[ -z "$busid" ] && exit 0
usbip unbind -b "$busid" >/dev/null 2>&1 || true
