#requires -Version 7
<#
.SYNOPSIS
  Validate and package the Blender extension zip using Blender's CLI.
  Uses the wheel built by build_wheel.ps1 and writes hair_sim_physx-<ver>.zip.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$blender = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
if (-not (Test-Path $blender)) { throw "Blender 5.1 not found at $blender" }

# Refresh wheels list in manifest from what's currently in ./wheels
$wheels = Get-ChildItem wheels\*.whl -ErrorAction SilentlyContinue | ForEach-Object { "./wheels/$($_.Name)" }
if (-not $wheels) { Write-Warning "No wheels in ./wheels — extension will load with stub only." }

$manifest = Get-Content blender_manifest.toml -Raw
$wheelsLine = "wheels = [$(($wheels | ForEach-Object { "`"$_`"" }) -join ', ')]"
$manifest = [regex]::Replace($manifest, "(?m)^wheels\s*=.*$", $wheelsLine)
Set-Content blender_manifest.toml $manifest -NoNewline

Write-Host "==> blender --command extension validate" -ForegroundColor Cyan
& $blender --command extension validate

Write-Host "==> blender --command extension build" -ForegroundColor Cyan
& $blender --command extension build --output-dir dist
Get-ChildItem dist\*.zip | ForEach-Object { Write-Host "    $($_.FullName)" -ForegroundColor Green }
