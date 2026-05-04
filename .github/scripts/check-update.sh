#!/bin/bash
set -e

REPO="${1:-RezoxP/AyuGramDesktop-builder}"
INSTALL_DIR="${2:-$(dirname "$(readlink -f "$0")")}"
API_URL="https://api.github.com/repos/${REPO}/releases/latest"

echo "Checking for updates from ${REPO}..."

RELEASE=$(curl -sL -H "User-Agent: AyuGram-Updater" "$API_URL")
LATEST_VERSION=$(echo "$RELEASE" | grep -oP '"tag_name":\s*"\K[^"]+' | sed 's/^v//')

if [ -z "$LATEST_VERSION" ]; then
    echo "Failed to check for updates."
    exit 1
fi

echo "Latest version: ${LATEST_VERSION}"

ARCH=$(uname -m)
case "$ARCH" in
    x86_64) PATTERN="Linux-x64" ;;
    *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

DOWNLOAD_URL=$(echo "$RELEASE" | grep -oP '"browser_download_url":\s*"\K[^"]+' | grep "$PATTERN" | grep '\.tar\.gz$' | head -1)

if [ -z "$DOWNLOAD_URL" ]; then
    echo "No matching asset found for Linux ${ARCH}."
    exit 1
fi

FILENAME=$(basename "$DOWNLOAD_URL")
echo "Download URL: ${DOWNLOAD_URL}"
echo "Asset: ${FILENAME}"

read -p "Download and install update? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Update cancelled."
    exit 0
fi

TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

echo "Downloading ${FILENAME}..."
curl -sL -H "User-Agent: AyuGram-Updater" -o "${TEMP_DIR}/${FILENAME}" "$DOWNLOAD_URL"

echo "Extracting to ${INSTALL_DIR}..."
tar -xzf "${TEMP_DIR}/${FILENAME}" -C "$INSTALL_DIR"

echo "Update complete! Restart AyuGram to use the new version."
