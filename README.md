# AyuGramDesktop-builder

CI/CD builder for [AyuGram Desktop](https://github.com/AyuGram/AyuGramDesktop) — builds release binaries for Windows (x64 & x86) and Linux (x64) with no debug symbols.

## Workflows

### `build-windows.yml` — Windows x64 & x86

Builds AyuGram for Windows in Release configuration using MSVC on `windows-2022`. Produces stripped binaries (no PDB/debug symbols). Triggered on push to `main`/`dev`, PRs, or manual dispatch.

### `build-linux.yml` — Linux x64

Builds AyuGram for Linux x64 using the official Docker build environment (`ghcr.io/telegramdesktop/tdesktop/centos_env`). Strips debug symbols with `strip`. Triggered on push to `main`/`dev`, PRs, or manual dispatch.

### `release.yml` — Create GitHub Release

Manual dispatch workflow that builds all platforms and creates a GitHub Release with downloadable archives:
- `AyuGram-Windows-x64-{version}.zip`
- `AyuGram-Windows-x86-{version}.zip`
- `AyuGram-Linux-x64-{version}.tar.gz`

## Update Mechanism

The built binaries have the auto-update URL patched to point to this repository. The release workflow pushes an update manifest to the `update-manifest` branch.

### Manual Update Scripts

Standalone update checker scripts are included for manual updates from GitHub Releases:

**Windows (PowerShell):**
```powershell
.\.github\scripts\check-update.ps1 -Repo "RezoxP/AyuGramDesktop-builder"
```

**Linux (Bash):**
```bash
./.github/scripts/check-update.sh "RezoxP/AyuGramDesktop-builder"
```

## Notes

- **API Credentials**: Builds use Telegram API ID `2040` / hash `b18441a1ff607e10a989891a5462e627` (from official AyuGram).
- **Linux x86 (32-bit)**: Not supported upstream — the AyuGram/Telegram Docker build environment only targets x86_64.
- **Windows x86**: Included in the matrix but may require longer build times and separate library caches.
