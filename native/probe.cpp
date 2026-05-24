// Phase 2B placeholder. Module name, function name, and file name
// are experimental and will change before any real solver wiring.
#include <pybind11/pybind11.h>

namespace py = pybind11;

int add(int a, int b) { return a + b; }

PYBIND11_MODULE(phase2b_probe, m) {
    m.attr("phase") = "2B";
    m.def("add", &add);
}
