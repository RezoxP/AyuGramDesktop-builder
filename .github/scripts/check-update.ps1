param(
    [string]$Repo = "RezoxP/AyuGramDesktop-builder",
    [string]$InstallDir = $PSScriptRoot,
    [switch]$Force = $false
)

$ErrorActionPreference = "Stop"
$apiUrl = "https://api.github.com/repos/$Repo/releases/latest"

Write-Host "Checking for updates from $Repo..." -ForegroundColor Cyan

try {
    $release = Invoke-RestMethod -Uri $apiUrl -Headers @{ "User-Agent" = "AyuGram-Updater" }
} catch {
    Write-Host "Failed to check for updates: $_" -ForegroundColor Red
    exit 1
}

$latestVersion = $release.tag_name -replace '^v', ''
Write-Host "Latest available release: v$latestVersion" -ForegroundColor Green

# Determine current local version if AyuGram.exe exists
$exePath = Join-Path $InstallDir "AyuGram.exe"
if (-not (Test-Path $exePath)) {
    $exePath = Join-Path $InstallDir "Telegram.exe"
}

if (Test-Path $exePath) {
    try {
        $localVer = (Get-Item $exePath).VersionInfo.ProductVersion
        if ($localVer) {
            Write-Host "Installed version: $localVer" -ForegroundColor Gray
            if ($localVer -eq $latestVersion -and -not $Force) {
                Write-Host "AyuGram is already up to date!" -ForegroundColor Green
                exit 0
            }
        }
    } catch {
        # Non-critical, continue
    }
}

$arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
$asset = $release.assets | Where-Object { $_.name -match "Windows-$arch" -and $_.name -match "\.zip$" } | Select-Object -First 1

if (-not $asset) {
    Write-Host "No matching asset found for Windows $arch." -ForegroundColor Red
    exit 1
}

Write-Host "Asset: $($asset.name)" -ForegroundColor Yellow
Write-Host "Download URL: $($asset.browser_download_url)" -ForegroundColor Gray

if (-not $Force) {
    $response = Read-Host "Download and install update? (y/n)"
    if ($response -notmatch '^[Yy]$') {
        Write-Host "Update cancelled." -ForegroundColor Yellow
        exit 0
    }
}

# Check if AyuGram or Telegram is running
$running = Get-Process -Name AyuGram, Telegram, Updater -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "AyuGram/Telegram is currently running." -ForegroundColor Yellow
    if (-not $Force) {
        $close = Read-Host "Close AyuGram to proceed with update? (y/n)"
        if ($close -notmatch '^[Yy]$') {
            Write-Host "Cannot update while application is running. Update cancelled." -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "Stopping running AyuGram processes..." -ForegroundColor Yellow
    $running | Stop-Process -Force
    Start-Sleep -Seconds 1
}

$tempDir = Join-Path $env:TEMP "AyuGram-Update-$(Get-Random)"
$zipPath = Join-Path $tempDir $asset.name

try {
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    Write-Host "Downloading $($asset.name)..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -Headers @{ "User-Agent" = "AyuGram-Updater" }

    Write-Host "Extracting update..." -ForegroundColor Cyan
    $extractDir = Join-Path $tempDir "extracted"
    Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

    Write-Host "Installing to $InstallDir..." -ForegroundColor Cyan
    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }

    Get-ChildItem -Path $extractDir | ForEach-Object {
        $dest = Join-Path $InstallDir $_.Name
        if ($_.PSIsContainer) {
            Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
        } else {
            Copy-Item -Path $_.FullName -Destination $dest -Force
        }
    }

    Write-Host "Update to v$latestVersion complete! You can now launch AyuGram." -ForegroundColor Green
} finally {
    if (Test-Path $tempDir) {
        Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
