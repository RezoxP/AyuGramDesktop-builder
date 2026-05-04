param(
    [string]$Repo = "RezoxP/AyuGramDesktop-builder",
    [string]$InstallDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
$apiUrl = "https://api.github.com/repos/$Repo/releases/latest"

Write-Host "Checking for updates from $Repo..."

try {
    $release = Invoke-RestMethod -Uri $apiUrl -Headers @{ "User-Agent" = "AyuGram-Updater" }
} catch {
    Write-Host "Failed to check for updates: $_"
    exit 1
}

$latestVersion = $release.tag_name -replace '^v', ''
Write-Host "Latest version: $latestVersion"

$arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
$asset = $release.assets | Where-Object { $_.name -match "Windows-$arch" -and $_.name -match "\.zip$" } | Select-Object -First 1

if (-not $asset) {
    Write-Host "No matching asset found for Windows $arch."
    exit 1
}

Write-Host "Download URL: $($asset.browser_download_url)"
Write-Host "Asset: $($asset.name)"

$response = Read-Host "Download and install update? (y/n)"
if ($response -ne 'y') {
    Write-Host "Update cancelled."
    exit 0
}

$tempDir = Join-Path $env:TEMP "AyuGram-Update"
$zipPath = Join-Path $tempDir $asset.name

if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
New-Item -ItemType Directory -Path $tempDir | Out-Null

Write-Host "Downloading $($asset.name)..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -Headers @{ "User-Agent" = "AyuGram-Updater" }

Write-Host "Extracting to $InstallDir..."
Expand-Archive -Path $zipPath -DestinationPath $tempDir -Force

Get-ChildItem "$tempDir\*" -Exclude "*.zip" | ForEach-Object {
    $dest = Join-Path $InstallDir $_.Name
    if ($_.PSIsContainer) {
        Copy-Item $_.FullName $dest -Recurse -Force
    } else {
        Copy-Item $_.FullName $dest -Force
    }
}

Remove-Item $tempDir -Recurse -Force
Write-Host "Update complete! Restart AyuGram to use the new version."
