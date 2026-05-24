cmake_minimum_required(VERSION 3.27)
project(hair_sim_physx LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(HAIRSIM_BUILD_PYTHON "Build pybind11 Python module" ON)
option(HAIRSIM_ENABLE_GPU   "Enable PhysX GPU (CUDA) pipeline" ON)

# Honor PHYSX_ROOT env or cache var; default to extern/PhysX/physx submodule layout.
if(NOT DEFINED PHYSX_ROOT)
    if(DEFINED ENV{PHYSX_ROOT})
        set(PHYSX_ROOT "$ENV{PHYSX_ROOT}" CACHE PATH "PhysX SDK root")
    else()
        set(PHYSX_ROOT "${CMAKE_SOURCE_DIR}/extern/PhysX/physx" CACHE PATH "PhysX SDK root")
    endif()
endif()
message(STATUS "PHYSX_ROOT = ${PHYSX_ROOT}")

include(cmake/FindPhysX.cmake OPTIONAL)

add_subdirectory(src)
