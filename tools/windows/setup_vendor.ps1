[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VendorRoot = Join-Path $RepoRoot "vendor\Can_analyze"
$DllPath = Join-Path $VendorRoot "二次开发库文件\x64(64bit)\ControlCAN.dll"

if (-not (Test-Path $DllPath)) {
    if (Test-Path $VendorRoot) {
        throw "Vendor directory exists but ControlCAN.dll is missing: $VendorRoot"
    }

    New-Item -ItemType Directory -Path (Split-Path $VendorRoot) -Force | Out-Null
    git clone --depth 1 https://github.com/houhouoch/Can_analyze.git $VendorRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to clone Can_analyze vendor source"
    }
}

if (-not (Test-Path $DllPath)) {
    throw "ControlCAN.dll was not found after vendor setup: $DllPath"
}

Write-Output "CONTROLCAN_DLL=$DllPath"

