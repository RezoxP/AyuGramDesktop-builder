#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-RezoxP/AyuGramDesktop-builder}"
INSTALL_DIR="${2:-$(dirname "$(readlink -f "$0")")}"
FORCE=0

for arg in "$@"; do
    case "$arg" in
        -y|--yes|-f|--force) FORCE=1 ;;
    esac
done

API_URL="https://api.github.com/repos/${REPO}/releases/latest"

echo "Checking for updates from ${REPO}..."

RELEASE=$(curl -sL -H "User-Agent: AyuGram-Updater" "$API_URL" || true)
if [ -z "$RELEASE" ]; then
    echo "Error: Failed to connect to GitHub API." >&2
    exit 1
fi

LATEST_VERSION=$(echo "$RELEASE" | grep -oP '"tag_name":\s*"\K[^"]+' | head -1 | sed 's/^v//')

if [ -z "$LATEST_VERSION" ]; then
    echo "Error: Failed to parse latest version tag from release." >&2
    exit 1
fi

echo "Latest available release: v${LATEST_VERSION}"

ARCH=$(uname -m)
case "$ARCH" in
    x86_64) PATTERN="Linux-x64" ;;
    *) echo "Error: Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

# Find download URL: prefer .tar.gz, fallback to .zip
DOWNLOAD_URL=$(echo "$RELEASE" | grep -oP '"browser_download_url":\s*"\K[^"]+' | grep "$PATTERN" | grep '\.tar\.gz$' | head -1 || true)
if [ -z "$DOWNLOAD_URL" ]; then
    DOWNLOAD_URL=$(echo "$RELEASE" | grep -oP '"browser_download_url":\s*"\K[^"]+' | grep "$PATTERN" | grep '\.zip$' | head -1 || true)
fi

if [ -z "$DOWNLOAD_URL" ]; then
    echo "Error: No matching asset found for Linux ${ARCH}." >&2
    exit 1
fi

FILENAME=$(basename "$DOWNLOAD_URL")
echo "Asset: ${FILENAME}"
echo "Download URL: ${DOWNLOAD_URL}"

if [ "$FORCE" -ne 1 ]; then
    read -p "Download and install update? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Update cancelled."
        exit 0
    fi
fi

# Check for running AyuGram / Telegram processes
if pgrep -x "AyuGram" >/dev/null 2>&1 || pgrep -x "Telegram" >/dev/null 2>&1; then
    echo "Warning: AyuGram or Telegram is currently running."
    if [ "$FORCE" -ne 1 ]; then
        read -p "Terminate running process to proceed with update? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Cannot update while application is running. Update cancelled."
            exit 1
        fi
    fi
    pkill -x "AyuGram" || true
    pkill -x "Telegram" || true
    sleep 1
fi

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

echo "Downloading ${FILENAME}..."
curl -sL -H "User-Agent: AyuGram-Updater" -o "${TEMP_DIR}/${FILENAME}" "$DOWNLOAD_URL"

echo "Extracting to ${INSTALL_DIR}..."
mkdir -p "$INSTALL_DIR"

if [[ "$FILENAME" == *.tar.gz ]]; then
    tar -xzf "${TEMP_DIR}/${FILENAME}" -C "$INSTALL_DIR"
elif [[ "$FILENAME" == *.zip ]]; then
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "${TEMP_DIR}/${FILENAME}" -d "$INSTALL_DIR"
    elif command -v 7z >/dev/null 2>&1; then
        7z x -y "${TEMP_DIR}/${FILENAME}" -o"$INSTALL_DIR" >/dev/null
    else
        echo "Error: Neither unzip nor 7z found to extract .zip update." >&2
        exit 1
    fi
fi

# Ensure executable permissions
chmod +x "$INSTALL_DIR"/AyuGram "$INSTALL_DIR"/Telegram "$INSTALL_DIR"/Updater 2>/dev/null || true

echo "Update to v${LATEST_VERSION} complete! Restart AyuGram to use the new version."
