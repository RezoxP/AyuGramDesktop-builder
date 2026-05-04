# AyuGramDesktop-builder

CI/CD builder for [AyuGram Desktop](https://github.com/AyuGram/AyuGramDesktop) — builds release binaries for Windows (x64 & x86) and Linux (x64) with no debug symbols.

## Workflow

### `build.yml` — Build & Release

Single workflow triggered via **manual dispatch** (`workflow_dispatch`). Builds all platforms in parallel, then creates a GitHub Release only if every build succeeds.

**Jobs:**

| Job | Platform | Architecture | Runner |
|-----|----------|-------------|--------|
| `windows` (matrix) | Windows | x64, x86 | `windows-2022` |
| `linux` | Linux | x64 | `ubuntu-22.04` (Docker) |
| `release` | — | — | `ubuntu-latest` |

**Artifacts:**
- `AyuGram-Windows-x64-{version}.zip`
- `AyuGram-Windows-x86-{version}.zip`
- `AyuGram-Linux-x64-{version}.tar.gz`

The release job runs only after all build jobs pass (`needs: [windows, linux]`). It creates a tagged GitHub Release and pushes an update manifest to the `update-manifest` branch.

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
- **Release gating**: The GitHub Release is only created when all three builds (Windows x64, Windows x86, Linux x64) succeed.
