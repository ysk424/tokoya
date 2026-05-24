// Phase 2B/4A placeholder. Module name, function names, and phase
// attribute are experimental and will change before any real solver
// wiring. Phase 4A added describe_curves for metadata round-trip.
#include <pybind11/pybind11.h>

#include <string>

namespace py = pybind11;

int add(int a, int b) { return a + b; }

// Phase 4A: accept Curves metadata, return a summary dict that the
// Python caller can compare against its own observations. No buffer
// data is exchanged here; that is Phase 4B.
py::dict describe_curves(
    const std::string& object_name,
    unsigned int       strand_count,
    unsigned int       points_per_strand,
    unsigned int       point_count,
    unsigned int       floats_per_frame,
    int                frame_current,
    const std::string& attribute_name,
    const std::string& attribute_domain,
    const std::string& data_type)
{
    const bool consistent =
        (point_count == strand_count * points_per_strand) &&
        (floats_per_frame == point_count * 3u);

    const bool attribute_ok =
        (attribute_name   == "position") &&
        (attribute_domain == "POINT")    &&
        (data_type        == "FLOAT_VECTOR");

    const bool accepted = consistent && attribute_ok;

    py::dict d;
    d["accepted"]          = accepted;
    d["object_name_echo"]  = object_name;
    d["strand_count"]      = strand_count;
    d["points_per_strand"] = points_per_strand;
    d["point_count"]       = point_count;
    d["floats_per_frame"]  = floats_per_frame;
    d["frame_current"]     = frame_current;
    d["consistent"]        = consistent;
    d["attribute_ok"]      = attribute_ok;

    std::string msg;
    if (accepted) {
        msg = "metadata consistent; ready for buffer round-trip (Phase 4B)";
    } else if (!consistent) {
        msg = "metadata inconsistent: arithmetic mismatch";
    } else {
        msg = "attribute fingerprint mismatch: expected (position, POINT, FLOAT_VECTOR)";
    }
    d["message"] = msg;

    return d;
}

PYBIND11_MODULE(phase2b_probe, m) {
    m.attr("phase") = "2B";
    m.def("add", &add);
    m.def("describe_curves", &describe_curves,
          py::arg("object_name"),
          py::arg("strand_count"),
          py::arg("points_per_strand"),
          py::arg("point_count"),
          py::arg("floats_per_frame"),
          py::arg("frame_current"),
          py::arg("attribute_name"),
          py::arg("attribute_domain"),
          py::arg("data_type"));
}
