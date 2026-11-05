# AyuGramDesktop-builder

Automated, fast, and multi-platform CI/CD builder for [AyuGram Desktop](https://github.com/AyuGram/AyuGramDesktop) — builds release binaries for **Windows** (x64 & x86), **Linux** (x64), and **macOS** (Universal Apple Silicon & Intel) with robust, future-proof, zero-bloat in-app auto-updates.

---

## Key Highlights

- **Multi-Platform Support**:
  - **Windows**: x64 and x86 (MSVC 2022 v143 toolset, `windows-2022` runner, Windows 7+ compatible).
  - **Linux**: x64 (glibc-compatible Docker `centos_env`).
  - **macOS**: Universal binary (Apple Silicon arm64 & Intel x86_64, `macos-latest` runner).
- **Runner-Image & Actions Future-Proofing**:
  - Pinned to stable, reliable GitHub runner images (`windows-2022` with native VS 2022, `ubuntu-24.04`, `macos-latest`).
  - Visual Studio installation path dynamically resolved via `vswhere`, with toolset pinned to VS 2022 (`v143`) for maximum stability.
  - All GitHub Actions upgraded to the latest major runtimes (`checkout@v7`, `cache@v6`, `upload-artifact@v7`, `download-artifact@v8`, `setup-python@v7`).
- **Fast, Cache-Optimized & Resumable Pipeline**:
  - **Windows**: Qt built in release-only mode, halving build time. Split restore/save cache logic saves caches with `!cancelled()`, so builds interrupted by timeouts or errors **resume** from the last completed stage instead of rebuilding from scratch.
  - **Linux**: Docker container with parallel build support (`--target Telegram`), multi-directory output discovery, and stripped binaries.
  - **macOS**: Aggressive runner disk cleanup, cached `Libraries/` and Qt trees on Apple Silicon (`macos-latest`), ad-hoc codesigning (`codesign --force --deep --sign -`), and Swift 6 compatibility guard (`DESKTOP_APP_DISABLE_SWIFT6=ON`).
- **Network-Resilient Dependency Fetching**:
  - `dav1d` and `breakpad` mirrored to GitHub remotes (no DNS or 503 failures).
  - MSYS2 installer URL dynamically resolved with pinned fallback, pacman GPG SigLevel bypass for expired keyrings, and pinned NASM 2.16.03 to eliminate NASM 3.02 crashes in libvpx.
  - Linux `cppgir` submodule fetched with 5 retries and exponential backoff, with support for an optional `CPPGIR_MIRROR` secret/variable (never fetched on Windows or macOS).
- **Bulletproof In-App Auto-Updates**:
  - **Universal `/current` & `current1`..`current9` Manifests**: Clients on modern Linux (glibc >= 2.28), modern Windows, and macOS request `/current6` by default. Manifest publishing writes `current` and `current1` through `current9` covering all updater revisions with both `stable` and `beta` channels.
  - **Client-Side Manifest Fallback**: If a version-specific manifest endpoint (e.g. `/current6`) returns 404 or fails, the client automatically falls back to universal `/current`.
  - **2 GB Download Ceiling**: Bumps `AbstractDedicatedLoader::kMaxFileSize` from 256 MB to 2 GB, eliminating download aborts on large archives (such as macOS Universal release zips >= 270 MB).
  - **Windows on ARM64 Support**: Publishes `"winarm"` mapped to Windows x64 binaries, with client platform fallback in `ParseCommonMap` (`winarm` -> `win64` -> `win`, `armac` <-> `mac`).
  - **HTTP 302 Redirect & CDN Handling**: Patches `HttpLoaderActor` to seamlessly handle GitHub Releases 302 redirects to AWS S3 without aborting, inspecting both `Content-Range` and `Content-Length`.
  - **Cross-Platform Rename Resilience**: Platform updaters (`updater_win.cpp`, `updater_linux.cpp`, `updater_osx.m`) safely skip running `Updater` executables without aborting, and seamlessly rename `AyuGram` and `Telegram` binary names.
  - **Dynamic macOS App Bundle & Symlinks**: Restores Unix symlinks (`::symlink`) for macOS `.app` Frameworks and dynamically resolves `AyuGram.app` bundles.
  - **Anti-Virus & Lock Resilience**: Handles transient file locks on Windows temp `Updater.exe` and `tupdates/temp` without failing the update.
  - **Locked Update Prefix**: Hard-locks `readAutoupdatePrefixRaw()` to prevent stale `tdata` from corrupting or hijacking the update URL.
- **Self-Healing Release Pipeline (`auto-update.yml`)**:
  - Monitors both `Telegram/build/version` and `changelog.txt` for upstream version bumps.
  - **Partial Releases**: Releases whatever platforms succeeded — a single platform failure never holds other artifacts hostage.
  - **Self-Tested Decision Engine** (`.github/scripts/update_decision.py`): Retries only stale platforms after a 30-minute quiet period, preventing CI minute exhaustion.
  - **Manifest Self-Healing**: Automatically repairs broken or missing manifests on subsequent runs.

---

## Workflows

### 1. `build.yml` — Multi-Platform Build & Release

Triggered manually via **workflow_dispatch** or automatically by `auto-update.yml`.

#### Workflow Parameters (Manual Dispatch):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `branch` | `dev` | Upstream AyuGram branch to checkout |
| `commit` | *(empty)* | Exact upstream commit SHA to build (pins a specific revision) |
| `enable_lto` | `false` | Enable Link-Time Optimization (keep false for fast & stable CI) |
| `create_release` | `true` | Create GitHub Release and push manifest to `update-manifest` |
| `build_windows_x64` | `true` | Build Windows 64-bit |
| `build_windows_x86` | `true` | Build Windows 32-bit (uses x64 host cross-compiler to prevent OOM) |
| `build_linux_x64` | `true` | Build Linux 64-bit |
| `build_macos` | `true` | Build macOS Universal (arm64 & x86_64) |

#### Release Artifacts:

- `AyuGram-Windows-x64-{version}.zip`
- `AyuGram-Windows-x86-{version}.zip`
- `AyuGram-Linux-x64-{version}.zip` *(in-app updater compatible)*
- `AyuGram-Linux-x64-{version}.tar.gz`
- `AyuGram-macOS-{version}.zip` *(.app bundle with preserved symlinks & ad-hoc signature)*
- `SHA256SUMS.txt`

---

### 2. `auto-update.yml` — Self-Healing Upstream Watcher

Monitors `https://github.com/AyuGram/AyuGramDesktop.git` `dev` branch changelog and version file.

Every 30 minutes it evaluates repository and upstream state via `.github/scripts/update_decision.py`:

| Decision | Trigger | Action |
|---|---|---|
| `full` | Upstream version > latest release version (or fresh repo) | Dispatch `build.yml` for **all** platforms |
| `retry` | Latest release is current but manifest platform(s) are stale | Dispatch `build.yml` for **only stale platforms**, after a 30-minute quiet period |
| `none` | Everything current, or a build is currently running/queued | Do nothing |

#### Optional Configuration

| Variable / Secret | Purpose |
|---|---|
| `WORKFLOW_DISPATCH_TOKEN` / `GH_PAT` (secret) | Personal Access Token (classic `repo` / `workflow` scope) used by `auto-update.yml` to trigger `build.yml` if default repository permissions restrict `GITHUB_TOKEN`. |
| `CPPGIR_MIRROR` (secret or variable) | Git URL of a mirror of `https://gitlab.com/mnauw/cppgir.git`, bypassing gitlab.com on Linux cloud runners. |
| `TDESKTOP_API_ID` / `TDESKTOP_API_HASH` (secrets) | Custom Telegram API credentials (defaults to AyuGram public keys). |

---

## Auto-Update Mechanics

The client polls the manifest files in the `update-manifest` branch:
```
https://raw.githubusercontent.com/<OWNER>/<REPO>/update-manifest/current6
```
*(With universal fallback to `.../current`)*

Example manifest structure (written to `current` and `current1` through `current9` with `stable` and `beta` channels):
```json
{
  "win64":  { "stable": { "released": "7002009", "testing": "7002009", "link": "https://github.com/OWNER/REPO/releases/download/v7.2.9/AyuGram-Windows-x64-7.2.9.zip" } },
  "win":    { "stable": { "released": "7002009", "testing": "7002009", "link": "https://github.com/OWNER/REPO/releases/download/v7.2.9/AyuGram-Windows-x86-7.2.9.zip" } },
  "winarm": { "stable": { "released": "7002009", "testing": "7002009", "link": "https://github.com/OWNER/REPO/releases/download/v7.2.9/AyuGram-Windows-x64-7.2.9.zip" } },
  "mac":    { "stable": { "released": "7002009", "testing": "7002009", "link": "https://github.com/OWNER/REPO/releases/download/v7.2.9/AyuGram-macOS-7.2.9.zip" } },
  "armac":  { "stable": { "released": "7002009", "testing": "7002009", "link": "https://github.com/OWNER/REPO/releases/download/v7.2.9/AyuGram-macOS-7.2.9.zip" } },
  "linux":  { "stable": { "released": "7002009", "testing": "7002009", "link": "https://github.com/OWNER/REPO/releases/download/v7.2.9/AyuGram-Linux-x64-7.2.9.zip" } }
}
```

When an update is detected:
1. Client downloads the zip directly from GitHub Releases, following HTTP 302 redirects without aborting.
2. The zip is extracted via embedded minizip with Zip-Slip protection, Unix symlink restoration, and executable permission restoration.
3. The exact version is extracted from the archive name and written to `tdata/version`.
4. The downloaded zip is deleted immediately upon extraction (anti-bloat).
5. Client transitions cleanly to `Ready` state and prompts for restart.

---

## Notes & Credentials

- **API Credentials**: Public defaults `2040` / `b18441a1ff607e10a989891a5462e627`. To use custom API keys, configure repository secrets `TDESKTOP_API_ID` and `TDESKTOP_API_HASH`.
- **First Build (Cold Cache)**: Cold cache builds take longer while compiling libraries. Subsequent builds hit the cache and complete swiftly. If a build step is interrupted, completed stages are cached anyway so the next attempt **resumes** where it left off.
