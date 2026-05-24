@echo off
rem Phase 2B local build wrapper. Initializes the VS 2022 BuildTools
rem x64 dev env and invokes setuptools through the repo .venv.
setlocal

set "VSDEV=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VSDEV%" (
    echo Error: VS 2022 BuildTools vcvars64.bat not found at "%VSDEV%".
    exit /b 1
)

call "%VSDEV%" >nul
if errorlevel 1 exit /b 1

cd /d "%~dp0"
set DISTUTILS_USE_SDK=1
"%~dp0..\.venv\Scripts\python.exe" setup.py build_ext --inplace
