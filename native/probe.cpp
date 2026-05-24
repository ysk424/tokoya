// Phase 2B/4A/4B placeholder. Module name, function names, and phase
// attribute are experimental and will change before any real solver
// wiring. Phase 4A added describe_curves; Phase 4B added
// probe_position_buffer (read-only buffer round-trip).
#include <pybind11/pybind11.h>

#include <cstddef>
#include <string>

namespace py = pybind11;

int add(int a, int b) { return a + b; }

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

// Phase 4B: accept one frame's float32 position buffer (read-only via
// the Python buffer protocol), validate its shape against expected
// metadata, compute simple statistics, and return them.
//
// Buffer pointer is NOT retained — only used inside this function.
// Buffer contents are NOT modified — read-only via const float*.
py::dict probe_position_buffer(
    unsigned int expected_point_count,
    unsigned int expected_float_count,
    int          frame_current,
    py::buffer   buf)
{
    py::buffer_info info = buf.request(/*writable=*/false);

    const bool itemsize_ok  = (info.itemsize == static_cast<py::ssize_t>(sizeof(float)));
    const bool format_ok    = (info.format == py::format_descriptor<float>::format());
    const bool size_ok      = (info.size == static_cast<py::ssize_t>(expected_float_count));
    const bool count_consistent =
        (expected_float_count == expected_point_count * 3u);

    const bool accepted = itemsize_ok && format_ok && size_ok && count_consistent;

    py::dict d;
    d["accepted"]             = accepted;
    d["itemsize"]             = info.itemsize;
    d["itemsize_ok"]          = itemsize_ok;
    d["format"]               = info.format;
    d["format_ok"]            = format_ok;
    d["buffer_size_floats"]   = info.size;
    d["size_ok"]              = size_ok;
    d["expected_float_count"] = expected_float_count;
    d["expected_point_count"] = expected_point_count;
    d["frame_current"]        = frame_current;
    d["consistent"]           = count_consistent;
    d["ndim"]                 = info.ndim;

    if (!accepted) {
        d["message"] = "buffer validation failed";
        return d;
    }

    const float* p = static_cast<const float*>(info.ptr);
    const std::size_t n_floats = static_cast<std::size_t>(info.size);
    const std::size_t n_points = n_floats / 3u;

    // Initialize min/max from the first point so we don't depend on
    // an artificial sentinel value.
    double min_x = p[0], min_y = p[1], min_z = p[2];
    double max_x = p[0], max_y = p[1], max_z = p[2];
    double sum_x = 0.0, sum_y = 0.0, sum_z = 0.0;

    for (std::size_t i = 0; i < n_points; ++i) {
        const double x = p[i * 3u + 0];
        const double y = p[i * 3u + 1];
        const double z = p[i * 3u + 2];
        if (x < min_x) min_x = x;
        if (x > max_x) max_x = x;
        if (y < min_y) min_y = y;
        if (y > max_y) max_y = y;
        if (z < min_z) min_z = z;
        if (z > max_z) max_z = z;
        sum_x += x;
        sum_y += y;
        sum_z += z;
    }

    const double avg_x = sum_x / static_cast<double>(n_points);
    const double avg_y = sum_y / static_cast<double>(n_points);
    const double avg_z = sum_z / static_cast<double>(n_points);
    const double checksum = sum_x + sum_y + sum_z;

    d["point_count_actual"] = static_cast<unsigned long long>(n_points);
    d["float_count_actual"] = static_cast<unsigned long long>(n_floats);
    d["first_vec3"]  = py::make_tuple(
        static_cast<double>(p[0]),
        static_cast<double>(p[1]),
        static_cast<double>(p[2]));
    d["last_vec3"]   = py::make_tuple(
        static_cast<double>(p[n_floats - 3u]),
        static_cast<double>(p[n_floats - 2u]),
        static_cast<double>(p[n_floats - 1u]));
    d["min_xyz"]     = py::make_tuple(min_x, min_y, min_z);
    d["max_xyz"]     = py::make_tuple(max_x, max_y, max_z);
    d["sum_xyz"]     = py::make_tuple(sum_x, sum_y, sum_z);
    d["average_xyz"] = py::make_tuple(avg_x, avg_y, avg_z);
    d["checksum_xyz_sum"] = checksum;
    d["message"]     = "buffer accepted and read; pointer not retained";

    return d;
    // 'p' and 'info' go out of scope here — no pointer or reference
    // is preserved beyond this function call.
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
    m.def("probe_position_buffer", &probe_position_buffer,
          py::arg("expected_point_count"),
          py::arg("expected_float_count"),
          py::arg("frame_current"),
          py::arg("buf"));
}
