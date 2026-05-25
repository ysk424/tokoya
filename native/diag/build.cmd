@echo off
rem Standalone diagnostic build for Phase 7A-2 Step 2.
rem Builds arm_a_b_probe.exe into ..\..\native\ so the PhysX runtime DLLs
rem (PhysXFoundation_64.dll etc., already present in native\) are
rem resolvable by Windows DLL search next to the .exe.
setlocal

set "VSDEV=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VSDEV%" (
    echo Error: VS 2022 BuildTools vcvars64.bat not found at "%VSDEV%".
    exit /b 1
)
call "%VSDEV%" >nul
if errorlevel 1 exit /b 1

rem PhysX 5 GPU build (same install as native\setup.py uses).
set "PHYSX_INSTALL=C:\Users\azoo\git\PhysX\physx\install\vc17win64-gpu-md\PhysX"
set "PHYSX_INC=%PHYSX_INSTALL%\include"
set "PHYSX_LIB=%PHYSX_INSTALL%\bin\win.x86_64.vc143.md\release"

set "HERE=%~dp0"
set "SRC=%HERE%arm_a_b_probe.cpp"
set "BUILD_DIR=%HERE%build"
set "OUT_EXE=%HERE%..\arm_a_b_probe.exe"

if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"
pushd "%BUILD_DIR%"

cl.exe /nologo /MD /O2 /EHsc /std:c++17 ^
    /D NDEBUG ^
    /I"%PHYSX_INC%" ^
    "%SRC%" ^
    /Fe"%OUT_EXE%" ^
    /Fo"%BUILD_DIR%\\" ^
    /link /MACHINE:X64 ^
    /LIBPATH:"%PHYSX_LIB%" ^
    PhysXFoundation_64.lib ^
    PhysX_64.lib ^
    PhysXCommon_64.lib ^
    PhysXCooking_64.lib ^
    PhysXExtensions_static_64.lib ^
    PhysXPvdSDK_static_64.lib

set RC=%errorlevel%
popd
exit /b %RC%
