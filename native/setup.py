# Phase 2B/4A/4B/4C/5A placeholder build script. setuptools + pybind11.
# Will be replaced when a later phase decides the long-term build system.
import os

from setuptools import setup
from pybind11.setup_helpers import Pybind11Extension, build_ext

# PhysX 5 SDK is expected at ../../PhysX (sibling to this repo) — see
# CLAUDE.md "External dependencies" section. Phase 5G adds the
# vc17win64-gpu-md preset (CPU + GPU, dynamic CRT to match pybind11).
# The GPU install is a superset of cpu-md for the CPU lib names that
# Phase 5A-5F linked against, so switching the default here keeps all
# earlier probes intact while making PhysXGpu_64 available for Phase 5G.
# Override via PHYSX_INSTALL_DIR to point back at vc17win64-cpu-md.
_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_PHYSX_INSTALL = os.path.abspath(os.path.join(
    _HERE, "..", "..", "PhysX", "physx", "install",
    "vc17win64-gpu-md", "PhysX"))
PHYSX_INSTALL = os.environ.get("PHYSX_INSTALL_DIR", _DEFAULT_PHYSX_INSTALL)

PHYSX_INCLUDE = os.path.join(PHYSX_INSTALL, "include")
PHYSX_LIBDIR  = os.path.join(PHYSX_INSTALL, "bin", "win.x86_64.vc143.md", "release")

ext = Pybind11Extension(
    "phase2b_probe",
    ["probe.cpp"],
    cxx_std=17,
    include_dirs=[PHYSX_INCLUDE],
    library_dirs=[PHYSX_LIBDIR],
    libraries=[
        "PhysXFoundation_64",
        "PhysX_64",
        "PhysXCommon_64",
        "PhysXCooking_64",          # Phase 5D: triangle mesh cooking
        "PhysXExtensions_static_64",
        "PhysXPvdSDK_static_64",
    ],
)

setup(
    name="phase2b_probe",
    ext_modules=[ext],
    cmdclass={"build_ext": build_ext},
)
