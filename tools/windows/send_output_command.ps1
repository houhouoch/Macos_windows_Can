[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("On", "Off")]
    [string]$Target,

    [ValidateRange(1, 30)]
    [int]$ListenSeconds = 3
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputDirectory = Join-Path $RepoRoot "artifacts\output-command\$Timestamp"
$OutboxDirectory = Join-Path $RepoRoot "outbox"
$ZipPath = Join-Path $OutboxDirectory "output-$($Target.ToLower())-$Timestamp.zip"

$BlockingProcess = Get-Process -Name "USB_CAN_Tool" -ErrorAction SilentlyContinue
if ($BlockingProcess) {
    $BlockingIds = ($BlockingProcess | Select-Object -ExpandProperty Id) -join ","
    throw "USB_CAN_Tool.exe is using CANalyst-II (PID $BlockingIds). Close it before the headless command."
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $OutboxDirectory -Force | Out-Null

$SetupOutput = & (Join-Path $PSScriptRoot "setup_vendor.ps1")
$DllLine = $SetupOutput | Where-Object { $_ -like "CONTROLCAN_DLL=*" } | Select-Object -Last 1
if (-not $DllLine) {
    throw "Vendor setup did not report CONTROLCAN_DLL"
}
$DllPath = $DllLine.Substring("CONTROLCAN_DLL=".Length)

& py -3 (Join-Path $PSScriptRoot "canalyst_output_command.py") `
    --dll $DllPath `
    --output-dir $OutputDirectory `
    --target $Target.ToLower() `
    --listen-seconds $ListenSeconds `
    --bitrate 1000000
$TestExitCode = $LASTEXITCODE

Compress-Archive -Path (Join-Path $OutputDirectory "*") -DestinationPath $ZipPath -Force
Write-Output "RESULT_ZIP=$ZipPath"
exit $TestExitCode

