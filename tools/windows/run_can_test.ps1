[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{40}$")]
    [string]$FirmwareCommit,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{40}$")]
    [string]$BridgeCommit,

    [ValidateRange(1, 3600)]
    [int]$Seconds = 15
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputDirectory = Join-Path $RepoRoot "artifacts\$FirmwareCommit\$Timestamp"
$OutboxDirectory = Join-Path $RepoRoot "outbox"
$ZipPath = Join-Path $OutboxDirectory "$FirmwareCommit-$Timestamp.zip"

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $OutboxDirectory -Force | Out-Null

$SetupOutput = & (Join-Path $PSScriptRoot "setup_vendor.ps1")
$DllLine = $SetupOutput | Where-Object { $_ -like "CONTROLCAN_DLL=*" } | Select-Object -Last 1
if (-not $DllLine) {
    throw "Vendor setup did not report CONTROLCAN_DLL"
}
$DllPath = $DllLine.Substring("CONTROLCAN_DLL=".Length)

& py -3 (Join-Path $PSScriptRoot "canalyst_controlcan.py") `
    --dll $DllPath `
    --output-dir $OutputDirectory `
    --firmware-commit $FirmwareCommit `
    --bridge-commit $BridgeCommit `
    --seconds $Seconds `
    --bitrate 1000000 `
    --channel 1 `
    --require-frames
$TestExitCode = $LASTEXITCODE

Compress-Archive -Path (Join-Path $OutputDirectory "*") -DestinationPath $ZipPath -Force
Write-Output "RESULT_ZIP=$ZipPath"
exit $TestExitCode

