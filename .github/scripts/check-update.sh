#!/bin/bash
set -euo pipefail

REPO="${1:-RezoxP/AyuGramDesktop-builder}"
INSTALL_DIR="${2:-$(cd "$(dirname "$0")" && pwd)}"
FORCE="${FORCE:-false}"
SILENT="${SILENT:-false}"
API_URL="https://api.github.com/repos/${REPO}/releases/latest"

log() { if [ "$SILENT" = "false" ]; then echo "$@"; fi; }

get_installed_version() {
    local exe="$INSTALL_DIR/AyuGram"
    if [ -f "$exe" ] && command -v strings >/dev/null 2>&1; then
        strings "$exe" 2>/dev/null | grep -oP '^\d+\.\d+\.\d+$' | head -1
    fi
}

log "Checking for updates..."

RELEASE=$(curl -sfL -H "User-Agent: AyuGram-Updater/1.0" "$API_URL" 2>/dev/null) || {
    echo "Error: Failed to reach update server. Check your internet connection."
    exit 1
}

LATEST_VERSION=$(echo "$RELEASE" | grep -oP '"tag_name":\s*"\Kv?[^"]+' | sed 's/^v//')
if [ -z "$LATEST_VERSION" ]; then
    echo "Error: Could not determine latest version."
    exit 1
fi

CURRENT_VERSION=$(get_installed_version) || true

log "Current version: ${CURRENT_VERSION:-not installed}"
log "Latest version:  $LATEST_VERSION"

if [ -n "$CURRENT_VERSION" ] && [ "$CURRENT_VERSION" = "$LATEST_VERSION" ] && [ "$FORCE" = "false" ]; then
    log "Already up to date."
    exit 0
fi

ARCH=$(uname -m)
case "$ARCH" in
    x86_64|amd64) PATTERN="Linux-x64" ;;
    *) echo "Error: Unsupported architecture: $ARCH"; exit 1 ;;
esac

DOWNLOAD_URL=$(echo "$RELEASE" | grep -oP '"browser_download_url":\s*"\K[^"]+' | grep "$PATTERN" | grep '\.tar\.gz$' | head -1)
if [ -z "$DOWNLOAD_URL" ]; then
    echo "Error: No download found for Linux $ARCH."
    exit 1
fi

FILENAME=$(basename "$DOWNLOAD_URL")
SIZE=$(echo "$RELEASE" | python3 -c "
import sys, json
r = json.load(sys.stdin)
for a in r.get('assets', []):
    if '$PATTERN' in a['name'] and a['name'].endswith('.tar.gz'):
        print(f\"{a['size'] / 1048576:.1f} MB\")
        break
" 2>/dev/null || echo "unknown size")

log "Found: $FILENAME ($SIZE)"

if [ "$SILENT" = "false" ] && [ "$FORCE" = "false" ]; then
    read -rp "Install update? (y/n) " REPLY
    if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
        log "Cancelled."
        exit 0
    fi
fi

TEMP_DIR=$(mktemp -d)
BACKUP_DIR="${INSTALL_DIR}/.ayugram-backup-$(date +%Y%m%d-%H%M%S)"
trap 'rm -rf "$TEMP_DIR"' EXIT

log "Downloading..."
curl -sfL -H "User-Agent: AyuGram-Updater/1.0" -o "$TEMP_DIR/$FILENAME" "$DOWNLOAD_URL" || {
    echo "Error: Download failed."
    exit 1
}

log "Extracting..."
mkdir -p "$TEMP_DIR/extracted"
tar -xzf "$TEMP_DIR/$FILENAME" -C "$TEMP_DIR/extracted" || {
    echo "Error: Extraction failed. Corrupted download?"
    exit 1
}

if [ -f "$INSTALL_DIR/AyuGram" ]; then
    log "Backing up current installation..."
    mkdir -p "$BACKUP_DIR"
    for f in "$INSTALL_DIR"/*; do
        fname=$(basename "$f")
        case "$fname" in
            check-update.sh|tdata|*.log) continue ;;
            *) cp -a "$f" "$BACKUP_DIR/" ;;
        esac
    done
fi

log "Installing..."
if ! cp -a "$TEMP_DIR/extracted/"* "$INSTALL_DIR/" 2>/dev/null; then
    echo "Error: Failed to copy files. Restoring backup..."
    if [ -d "$BACKUP_DIR" ]; then
        cp -a "$BACKUP_DIR/"* "$INSTALL_DIR/"
        echo "Restored previous version."
    fi
    exit 1
fi

chmod +x "$INSTALL_DIR/AyuGram" 2>/dev/null || true
chmod +x "$INSTALL_DIR/check-update.sh" 2>/dev/null || true

NEW_VERSION=$(get_installed_version)
log "Updated to ${NEW_VERSION:-$LATEST_VERSION}"
if [ -d "$BACKUP_DIR" ]; then log "Backup saved to: $BACKUP_DIR"; fi
log "Restart AyuGram to use the new version."
