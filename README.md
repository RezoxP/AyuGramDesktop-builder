# AyuGramDesktop-builder

Automated CI/CD builder for [AyuGram Desktop](https://github.com/AyuGram/AyuGramDesktop) — builds release binaries for Windows (x64 & x86) and Linux (x64) with no debug symbols and working automatic updates.

---

## Features

- **Automated Upstream Tracking**: A daily scheduled workflow checks for new upstream AyuGram releases. If a new version is detected, a full automated build and release cycle is triggered.
- **In-App Auto-Updates**: Built binaries are patched to use plain `.zip` archives and download updates from this repository's `update-manifest` branch, bypassing Telegram's proprietary RSA/SHA1 signature requirement.
- **Future-Proof Build Environment**:
  - Automatically migrates Windows dependencies to MSYS2 UCRT64 toolchains (`mingw-w64-ucrt-x86_64-*`).
  - Resolves Linux `tlottie` symbol consolidation into `libtdesktop_rust.a` in newer centos_env Docker images.
  - Automatically overrides and ignores obsolete official `ayugram.one` prefixes saved in `tdata/prefix`.
- **Standalone Update Checkers**: Handy PowerShell and Bash scripts for external or portable updates.

---

## Workflow

### `build.yml` — Automated & On-Demand Builds

The workflow runs on **schedule** (daily at 03:00 UTC) and can also be triggered manually via **GitHub Actions `workflow_dispatch`**.

#### Workflow Parameters (Manual Dispatch):
- `branch`: Git branch of AyuGram to build (default: `dev`).
- `enable_lto`: Enable Link-Time Optimization (default: `true`).
- `force_build`: Rebuild and re-release even if a release for the upstream version already exists (default: `false`).

#### Pipeline Architecture:

1. **`check` (Fast gatekeeper)**:
   - Queries upstream `Telegram/build/version`.
   - Checks if a release tag `v{version}` already exists in this repository.
   - If already built and `force_build` is false, cleanly finishes in ~15 seconds without consuming runner hours.
2. **`windows` (Matrix `x64`, `x86`)**:
   - Patches source tree with UCRT64 MSYS2 environment & updater zip support.
   - Builds static dependencies with caching.
   - Builds Release `AyuGram.exe` and `Updater.exe`.
   - Packages into `AyuGram-Windows-{arch}-{version}.zip`.
3. **`linux` (`x64`)**:
   - Pulls Telegram Desktop CentOS Docker build environment.
   - Patches `tlottie` / `tdesktop_rust` resolution and zip updater support.
   - Compiles Release binaries in Docker.
   - Packages into both `AyuGram-Linux-x64-{version}.zip` (for in-app updater) and `AyuGram-Linux-x64-{version}.tar.gz`.
4. **`release`**:
   - Runs once all builds succeed (`needs: [check, windows, linux]`).
   - Publishes GitHub Release with all 4 artifacts.
   - Generates and commits `current4` manifest to the orphan `update-manifest` branch.

---

## Auto-Update Mechanism

### In-App Auto-Updates

The client checks for updates against:
```
https://raw.githubusercontent.com/<OWNER>/<REPO>/update-manifest/current4
```
When an update is found:
- The client downloads the `.zip` update payload directly from GitHub Releases.
- The patched updater extracts the zip using embedded minizip, sets executable permissions on Linux (`AyuGram`, `Telegram`, `Updater`), writes `tupdates/temp/ready` and `tdata/version`, and seamlessly restarts.

### Standalone Update Scripts

Portable and standalone installations can also be kept up to date using the included scripts:

#### Windows (PowerShell):
```powershell
.\.github\scripts\check-update.ps1 -Repo "RezoxP/AyuGramDesktop-builder"
```
*Optional switches*:
- `-InstallDir <path>`: Directory containing AyuGram (defaults to script directory).
- `-Force`: Update without prompt and automatically close running AyuGram process.

#### Linux (Bash):
```bash
./.github/scripts/check-update.sh "RezoxP/AyuGramDesktop-builder"
```
*Optional switches*:
- Pass directory as second argument: `./.github/scripts/check-update.sh "RezoxP/AyuGramDesktop-builder" /opt/ayugram`
- `-y` / `--yes` / `-f` for unattended updates.

---

## Notes

- **API Credentials**: Builds use Telegram API ID `2040` / hash `b18441a1ff607e10a989891a5462e627`.
- **Linux 32-bit (x86)**: Not supported upstream — the Telegram Desktop CentOS Docker environment only supports `x86_64`.
- **Release Gating**: GitHub Releases are published only if all three platform targets (Windows x64, Windows x86, Linux x64) build cleanly.
