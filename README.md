# AyuGramDesktop-builder

Automated, fast, and multi-platform CI/CD builder for [AyuGram Desktop](https://github.com/AyuGram/AyuGramDesktop) — builds release binaries for **Windows** (x64 & x86), **Linux** (x64 & x86), and **macOS** (Universal Apple Silicon & Intel) with no debug symbols and robust auto-updates.

---

## Key Highlights

- **Multi-Platform Support**:
  - **Windows**: x64 and x86 (MSVC 2022).
  - **Linux**: x64 and experimental 32-bit x86.
  - **macOS**: Universal binary (Apple Silicon arm64 & Intel x86_64).
- **Fast, Cache-Optimized Pipeline**:
  - **Windows**: Builds Qt in release-only mode, halving library build times. Caches to the exact output directories (`Libraries/win64` and `Libraries`), with split restore/save so completed library stages are never discarded on compilation failure.
  - **Linux**: Utilizes prebuilt Docker environments with dynamic `tdesktop_rust` / `tlottie` symbol resolution, bypassing hours of redundant Docker builds.
  - **macOS**: Cached `Libraries/` tree on Apple Silicon (`macos-14`), delivering swift subsequent compilation cycles.
- **Dynamic & Adaptable**:
  - Target branches or exact commit SHAs on demand.
  - Granular build toggles for each platform and architecture.
  - Dynamic SDK resolution from upstream build docs.
  - Collision-free release tagging: `v{version}` or `v{version}-{commit7}` if rebuilds are requested.
- **In-App Auto-Updates (Zero Signature Lock-in)**:
  - Bypasses Telegram's proprietary RSA/SHA1 signature checks using embedded `minizip` plain `.zip` extraction.
  - Automatic `0755` executable permissions for Linux binaries and macOS `.app` bundles upon update.
  - Auto-updates point to this repository's `update-manifest` branch and automatically override legacy prefixes.
- **Automated Upstream Watcher (`auto-update.yml`)**:
  - Runs every 6 hours using `git ls-remote` (no GitHub API rate limits).
  - Dispatches `build.yml` whenever upstream releases new commits.

---

## Workflows

### 1. `build.yml` — Multi-Platform Build & Release

Triggered on schedule (daily fallback) or manually via **workflow_dispatch**.

#### Workflow Parameters (Manual Dispatch):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `branch` | `dev` | Upstream AyuGram branch to checkout |
| `commit` | *(empty)* | Exact upstream commit SHA to build (pins a specific revision) |
| `enable_lto` | `false` | Enable Link-Time Optimization (keep false for fast & stable CI) |
| `create_release` | `true` | Create GitHub Release and push manifest to `update-manifest` |
| `build_windows_x64` | `true` | Build Windows 64-bit |
| `build_windows_x86` | `true` | Build Windows 32-bit |
| `build_linux_x64` | `true` | Build Linux 64-bit |
| `build_macos` | `true` | Build macOS Universal (arm64 & x86_64) |
| `build_linux_x86` | `false` | Build Linux 32-bit (experimental) |

#### Release Artifacts:

- `AyuGram-Windows-x64-{version}.zip`
- `AyuGram-Windows-x86-{version}.zip`
- `AyuGram-Linux-x64-{version}.zip` *(in-app updater compatible)*
- `AyuGram-Linux-x64-{version}.tar.gz`
- `AyuGram-macOS-{version}.zip` *(.app bundle)*
- `SHA256SUMS.txt`

---

### 2. `auto-update.yml` — Automated Upstream Watcher

Monitors `https://github.com/AyuGram/AyuGramDesktop.git` `dev` branch tip.

- Uses `git ls-remote` to detect new commits without burning GitHub API rate limits.
- Compares the remote tip with the `Upstream commit:` recorded in the latest release.
- If upstream changed and no build is running, it dispatches `build.yml` pinned to that commit.
- If a build fails, the release remains on the previous version, allowing the next run to automatically retry.

---

## Auto-Update Mechanics

### In-App Auto-Updates

The client polls the raw manifest:
```
https://raw.githubusercontent.com/<OWNER>/<REPO>/update-manifest/current4
```

Example manifest structure:
```json
{
  "win64": { "stable": { "released": "7002009", "link": "https://github.com/OWNER/REPO/releases/download/v7.2.9/AyuGram-Windows-x64-7.2.9.zip" } },
  "win":   { "stable": { "released": "7002009", "link": "https://github.com/OWNER/REPO/releases/download/v7.2.9/AyuGram-Windows-x86-7.2.9.zip" } },
  "mac":   { "stable": { "released": "7002009", "link": "https://github.com/OWNER/REPO/releases/download/v7.2.9/AyuGram-macOS-7.2.9.zip" } },
  "armac": { "stable": { "released": "7002009", "link": "https://github.com/OWNER/REPO/releases/download/v7.2.9/AyuGram-macOS-7.2.9.zip" } },
  "linux": { "stable": { "released": "7002009", "link": "https://github.com/OWNER/REPO/releases/download/v7.2.9/AyuGram-Linux-x64-7.2.9.zip" } }
}
```

When an update is detected, the client downloads the package directly from GitHub Releases and unpacks it via embedded minizip, writing the required `tupdates/temp/ready` flag and updating seamlessly.

### Standalone Update Scripts

#### Windows (PowerShell):
```powershell
.\.github\scripts\check-update.ps1 -Repo "RezoxP/AyuGramDesktop-builder"
```
*Switches: `-InstallDir <path>`, `-Force`*

#### Linux & macOS (Bash):
```bash
./.github/scripts/check-update.sh "RezoxP/AyuGramDesktop-builder"
```
*Switches: Pass custom directory as second argument, `-y` or `-f` for unattended updates.*

---

## Notes & Credentials

- **API Credentials**: Public defaults `2040` / `b18441a1ff607e10a989891a5462e627`. To use custom API keys, configure repository secrets `TDESKTOP_API_ID` and `TDESKTOP_API_HASH`.
- **First Build (Cold Cache)**: Cold cache builds take longer on Windows while building libraries. Subsequent builds hit the cache and complete in ~15-25 minutes.
