#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include "hair_solver.h"

namespace py = pybind11;
using hairsim::HairSolver;
using hairsim::SolverConfig;
using hairsim::StrandLayout;

PYBIND11_MODULE(_core, m) {
    m.doc() = "PhysX-backed hair solver core (pybind11 bindings)";

#if defined(HAIRSIM_HAVE_PHYSX)
    m.attr("HAVE_PHYSX") = true;
#else
    m.attr("HAVE_PHYSX") = false;
#endif
#if defined(HAIRSIM_ENABLE_GPU)
    m.attr("ENABLE_GPU") = true;
#else
    m.attr("ENABLE_GPU") = false;
#endif

    py::class_<StrandLayout>(m, "StrandLayout")
        .def(py::init<>())
        .def_readwrite("strand_count",     &StrandLayout::strand_count)
        .def_readwrite("points_per_strand", &StrandLayout::points_per_strand);

    py::class_<SolverConfig>(m, "SolverConfig")
        .def(py::init<>())
        .def_readwrite("timestep", &SolverConfig::timestep)
        .def_readwrite("use_gpu",  &SolverConfig::use_gpu)
        .def_readwrite("substeps", &SolverConfig::substeps)
        .def_property("gravity",
            [](const SolverConfig& c) {
                return py::make_tuple(c.gravity[0], c.gravity[1], c.gravity[2]);
            },
            [](SolverConfig& c, py::sequence g) {
                c.gravity[0] = py::cast<float>(g[0]);
                c.gravity[1] = py::cast<float>(g[1]);
                c.gravity[2] = py::cast<float>(g[2]);
            });

    py::class_<HairSolver>(m, "HairSolver")
        .def(py::init<>())
        .def("initialize", &HairSolver::initialize)
        .def("shutdown",   &HairSolver::shutdown)
        .def("step",       &HairSolver::step, py::arg("dt"))
        .def("is_gpu_enabled", &HairSolver::is_gpu_enabled)
        .def("set_strands",
            [](HairSolver& self,
               std::uint32_t strand_count,
               std::uint32_t points_per_strand,
               py::array_t<float, py::array::c_style | py::array::forcecast> points) {
                if (points.size() != py::ssize_t(strand_count) * points_per_strand * 3) {
                    throw py::value_error("points must have shape (strand_count, points_per_strand, 3)");
                }
                StrandLayout l{strand_count, points_per_strand};
                self.set_strands(l, points.data());
            },
            py::arg("strand_count"), py::arg("points_per_strand"), py::arg("points"))
        .def("get_points",
            [](const HairSolver& self) {
                auto l = self.layout();
                py::array_t<float> out({py::ssize_t(l.strand_count),
                                        py::ssize_t(l.points_per_strand),
                                        py::ssize_t(3)});
                self.get_points(out.mutable_data());
                return out;
            });
}
