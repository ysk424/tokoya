# Minimal PhysX 5 locator. Expects PhysX SDK built via its own
# physx/generate_projects.bat into ${PHYSX_ROOT}/install/<preset>/PhysX.
#
# Set PHYSX_PRESET (e.g. vc17win64) and PHYSX_CONFIG (release / profile / debug)
# to point at the variant you built.

set(PHYSX_PRESET "vc17win64" CACHE STRING "PhysX build preset directory name")
set(PHYSX_CONFIG "release"   CACHE STRING "PhysX build configuration")

set(_physx_install "${PHYSX_ROOT}/install/${PHYSX_PRESET}/PhysX")
set(_physx_include "${_physx_install}/include")
set(_physx_lib     "${_physx_install}/bin/win.x86_64.vc143.mt/${PHYSX_CONFIG}")

if(EXISTS "${_physx_include}/PxPhysicsAPI.h")
    add_library(PhysX::PhysX INTERFACE IMPORTED)
    target_include_directories(PhysX::PhysX INTERFACE "${_physx_include}")
    target_link_directories  (PhysX::PhysX INTERFACE "${_physx_lib}")
    target_link_libraries    (PhysX::PhysX INTERFACE
        PhysX_64
        PhysXCommon_64
        PhysXFoundation_64
        PhysXExtensions_static_64
        PhysXPvdSDK_static_64
    )
    set(PhysX_FOUND TRUE)
    message(STATUS "Found PhysX: ${_physx_install}")
else()
    set(PhysX_FOUND FALSE)
    message(WARNING
        "PhysX SDK not found at ${_physx_install}. "
        "Run scripts/build_physx.ps1 first, or set PHYSX_ROOT/PHYSX_PRESET/PHYSX_CONFIG.")
endif()
