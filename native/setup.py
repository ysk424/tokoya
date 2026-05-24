# Phase 2B placeholder build script. setuptools + pybind11.
# Will be replaced when Phase 2C decides the long-term build system.
from setuptools import setup
from pybind11.setup_helpers import Pybind11Extension, build_ext

setup(
    name="phase2b_probe",
    ext_modules=[Pybind11Extension("phase2b_probe", ["probe.cpp"], cxx_std=17)],
    cmdclass={"build_ext": build_ext},
)
