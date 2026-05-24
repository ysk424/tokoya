#requires -Version 7
<#
.SYNOPSIS
  Install the most recent built extension zip into local Blender 5.1.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$blender = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
$zip = Get-ChildItem dist\*.zip -ErrorAction Stop | Sort-Object LastWriteTime -Descending | Select-Object -First 1

Write-Host "==> Installing $($zip.Name) into Blender 5.1" -ForegroundColor Cyan
& $blender --command extension install-file --repo user_default $zip.FullName
