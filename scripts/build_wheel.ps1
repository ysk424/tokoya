#requires -Version 7
<#
.SYNOPSIS
  Build the hair_sim_physx wheel via scikit-build-core into ./wheels.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venv = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venv)) { throw "Run scripts/setup_venv.ps1 first." }

Write-Host "==> Building wheel" -ForegroundColor Cyan
& $venv -m pip wheel . --no-deps --wheel-dir wheels
Get-ChildItem wheels\*.whl | ForEach-Object { Write-Host "    $($_.Name)" -ForegroundColor Green }
