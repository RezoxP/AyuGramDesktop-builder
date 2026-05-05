param(
    [string]$Repo = "RezoxP/AyuGramDesktop-builder",
    [string]$InstallDir = "",
    [switch]$Force,
    [switch]$Silent
)

$ErrorActionPreference = "Stop"

if (-not $InstallDir) {
    $exe = Get-ChildItem -Path $PSScriptRoot -Filter "AyuGram.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($exe) {
        $InstallDir = $PSScriptRoot
    } else {
        $InstallDir = $PSScriptRoot
    }
}

function Get-InstalledVersion {
    $exePath = Join-Path $InstallDir "AyuGram.exe"
    if (Test-Path $exePath) {
        $ver = (Get-Item $exePath).VersionInfo.FileVersion
        if ($ver) { return $ver.Trim() }
    }
    return $null
}

function Write-Status($msg) {
    if (-not $Silent) { Write-Host $msg }
}

$apiUrl = "https://api.github.com/repos/$Repo/releases/latest"
Write-Status "Checking for updates..."

try {
    $headers = @{ "User-Agent" = "AyuGram-Updater/1.0" }
    $release = Invoke-RestMethod -Uri $apiUrl -Headers $headers
} catch {
    Write-Host "Error: Failed to reach update server. Check your internet connection."
    exit 1
}

$latestVersion = $release.tag_name -replace '^v', ''
$currentVersion = Get-InstalledVersion

Write-Status "Current version: $(if ($currentVersion) { $currentVersion } else { 'not installed' })"
Write-Status "Latest version:  $latestVersion"

if ($currentVersion -and ($currentVersion -eq $latestVersion) -and (-not $Force)) {
    Write-Status "Already up to date."
    exit 0
}

$arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
$asset = $release.assets | Where-Object { $_.name -match "Windows-$arch" -and $_.name -match "\.zip$" } | Select-Object -First 1

if (-not $asset) {
    Write-Host "Error: No download found for Windows $arch."
    exit 1
}

Write-Status "Found: $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB)"

if (-not $Silent -and -not $Force) {
    $response = Read-Host "Install update? (y/n)"
    if ($response -ne 'y') {
        Write-Status "Cancelled."
        exit 0
    }
}

$tempDir = Join-Path $env:TEMP "AyuGram-Update-$(Get-Random)"
$zipPath = Join-Path $tempDir $asset.name
$backupDir = Join-Path $env:TEMP "AyuGram-Backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

try {
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

    Write-Status "Downloading..."
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "AyuGram-Updater/1.0")
    $wc.DownloadFile($asset.browser_download_url, $zipPath)

    Write-Status "Extracting..."
    Expand-Archive -Path $zipPath -DestinationPath "$tempDir\extracted" -Force

    Write-Status "Backing up current installation..."
    if (Test-Path (Join-Path $InstallDir "AyuGram.exe")) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        Get-ChildItem $InstallDir -Exclude "check-update.ps1","tdata","*.log" | ForEach-Object {
            Copy-Item $_.FullName (Join-Path $backupDir $_.Name) -Recurse -Force
        }
    }

    Write-Status "Installing..."
    Get-ChildItem "$tempDir\extracted\*" | ForEach-Object {
        $dest = Join-Path $InstallDir $_.Name
        if ($_.PSIsContainer) {
            Copy-Item $_.FullName $dest -Recurse -Force
        } else {
            Copy-Item $_.FullName $dest -Force
        }
    }

    $newVersion = Get-InstalledVersion
    Write-Status "Updated to $newVersion"
    if (Test-Path $backupDir) { Write-Status "Backup saved to: $backupDir" }
    Write-Status "Restart AyuGram to use the new version."

} catch {
    Write-Host "Error during update: $_"

    if (Test-Path $backupDir) {
        Write-Host "Restoring from backup..."
        Get-ChildItem $backupDir | ForEach-Object {
            Copy-Item $_.FullName (Join-Path $InstallDir $_.Name) -Recurse -Force
        }
        Write-Host "Restored previous version."
    }
    exit 1

} finally {
    if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue }
}
