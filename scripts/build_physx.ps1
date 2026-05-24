#requires -Version 7
<#
.SYNOPSIS
  Configure and build the NVIDIA PhysX 5 SDK that lives at extern/PhysX.

  Uses PhysX's own generate_projects.bat (which fetches packman deps),
  then builds the requested preset/config with MSBuild.
#>
param(
    [string]$Preset = "vc17win64",
    [ValidateSet("debug","checked","profile","release")]
    [string]$Config = "release"
)
$ErrorActionPreference = "Stop"
$root  = Split-Path -Parent $PSScriptRoot
$physx = Join-Path $root "extern\PhysX\physx"

if (-not (Test-Path $physx)) {
    throw "PhysX submodule missing. Run: git submodule update --init --recursive"
}

Push-Location $physx
try {
    Write-Host "==> generate_projects.bat $Preset" -ForegroundColor Cyan
    & .\generate_projects.bat $Preset

    $sln = Get-ChildItem -Path "compiler\$Preset" -Filter "*.sln" | Select-Object -First 1
    if (-not $sln) { throw "Solution not found under compiler\$Preset" }

    $vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    $vsroot  = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
    $msbuild = Join-Path $vsroot "MSBuild\Current\Bin\MSBuild.exe"

    Write-Host "==> MSBuild $($sln.FullName) /p:Configuration=$Config" -ForegroundColor Cyan
    & $msbuild $sln.FullName "/p:Configuration=$Config" "/p:Platform=x64" /m /v:m
}
finally {
    Pop-Location
}
Write-Host "==> PhysX build complete." -ForegroundColor Green
