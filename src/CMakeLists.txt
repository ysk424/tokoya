if(NOT HAIRSIM_BUILD_PYTHON)
    return()
endif()

find_package(Python 3.13 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(_core MODULE
    bindings.cpp
    hair_solver.cpp
)

target_compile_definitions(_core PRIVATE
    $<$<BOOL:${HAIRSIM_ENABLE_GPU}>:HAIRSIM_ENABLE_GPU=1>
)

if(TARGET PhysX::PhysX)
    target_link_libraries(_core PRIVATE PhysX::PhysX)
    target_compile_definitions(_core PRIVATE HAIRSIM_HAVE_PHYSX=1)
else()
    message(WARNING "Building _core without PhysX (stub mode). Solver calls will no-op.")
endif()

if(MSVC)
    target_compile_options(_core PRIVATE /W4 /permissive- /Zc:__cplusplus)
endif()

install(TARGETS _core LIBRARY DESTINATION hair_sim_physx)
