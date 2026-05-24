#requires -Version 7
<#
.SYNOPSIS
  Create .venv with system Python 3.13 and install dev deps.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = (Get-Command py -ErrorAction SilentlyContinue) `
    ? "py -3.13" : "python"

Write-Host "==> Creating .venv with $python" -ForegroundColor Cyan
& $python.Split()[0] $python.Split()[1..($python.Split().Count-1)] -m venv .venv

$pip = ".\.venv\Scripts\python.exe"
& $pip -m pip install --upgrade pip wheel
& $pip -m pip install -r requirements-dev.txt
Write-Host "==> Done. Activate with: .\.venv\Scripts\Activate.ps1" -ForegroundColor Green
