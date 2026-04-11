#!/bin/bash
# =============================================================================
# RemoteUSB – Persistence Layer
# Mountet ein Loop-backed ext4-Image als /var/lib/remoteusb-data und
# bind-mountet Unterverzeichnisse über die wirklich persistenten Configs.
# Läuft früh im Boot, VOR NetworkManager + wg-quick + remoteusb-watchdog.
# =============================================================================

set -e

IMG=/boot/firmware/remoteusb-data.img
SIZE_MB=32
MNT=/var/lib/remoteusb-data

log() { echo "[persist] $*"; }

# ---------------------------------------------------------------------------
# 1. Image anlegen falls noch nicht vorhanden
# ---------------------------------------------------------------------------
if [ ! -f "$IMG" ]; then
    log "Erzeuge ${SIZE_MB}M ext4-Image in $IMG"
    dd if=/dev/zero of="$IMG" bs=1M count=$SIZE_MB status=none
    mkfs.ext4 -q -F -L remoteusb-data "$IMG"
fi

# ---------------------------------------------------------------------------
# 2. Image mounten
# ---------------------------------------------------------------------------
mkdir -p "$MNT"
if ! mountpoint -q "$MNT"; then
    log "Mounte $IMG auf $MNT"
    mount -o loop "$IMG" "$MNT"
fi

# ---------------------------------------------------------------------------
# 3. Seed-Daten aus /etc beim allerersten Start übernehmen
# ---------------------------------------------------------------------------
seed_dir() {
    local src="$1"
    local dst="$2"
    mkdir -p "$dst"
    if [ -d "$src" ] && [ -z "$(ls -A "$dst" 2>/dev/null)" ]; then
        log "Seed: $src → $dst"
        cp -a "$src/." "$dst/" 2>/dev/null || true
    fi
}

seed_dir /etc/remoteusb                         "$MNT/etc-remoteusb"
seed_dir /etc/NetworkManager/system-connections "$MNT/nm-connections"
seed_dir /etc/wireguard                         "$MNT/etc-wireguard"

# ---------------------------------------------------------------------------
# 4. Bind-Mounts
# ---------------------------------------------------------------------------
bind_mount() {
    local src="$1"
    local dst="$2"
    mkdir -p "$dst"
    if ! mountpoint -q "$dst"; then
        log "Bind: $src → $dst"
        mount --bind "$src" "$dst"
    fi
}

bind_mount "$MNT/etc-remoteusb"   /etc/remoteusb
bind_mount "$MNT/nm-connections"  /etc/NetworkManager/system-connections
bind_mount "$MNT/etc-wireguard"   /etc/wireguard

log "Persistenz-Layer bereit."
