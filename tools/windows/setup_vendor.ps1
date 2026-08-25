[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VendorRoot = Join-Path $RepoRoot "vendor\Can_analyze"

function Find-ControlCanDll {
    if (-not (Test-Path $VendorRoot)) {
        return $null
    }

    return Get-ChildItem -Path $VendorRoot -Filter "ControlCAN.dll" -File -Recurse |
        Where-Object { $_.Directory.Name -eq "x64(64bit)" } |
        Select-Object -First 1 -ExpandProperty FullName
}

$DllPath = Find-ControlCanDll

if (-not $DllPath) {
    if (Test-Path $VendorRoot) {
        throw "Vendor directory exists but ControlCAN.dll is missing: $VendorRoot"
    }

    New-Item -ItemType Directory -Path (Split-Path $VendorRoot) -Force | Out-Null
    git clone --depth 1 https://github.com/houhouoch/Can_analyze.git $VendorRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to clone Can_analyze vendor source"
    }

    $DllPath = Find-ControlCanDll
}

if (-not $DllPath) {
    throw "ControlCAN.dll was not found after vendor setup: $VendorRoot"
}

Write-Output "CONTROLCAN_DLL=$DllPath"
