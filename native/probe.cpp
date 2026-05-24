// Phase 2B/4A/4B/4C/5A placeholder module. Module name, function names,
// and phase attribute are experimental and will change before any real
// solver wiring.
//
// Phase history of this file:
//   4A: describe_curves           (metadata round-trip only)
//   4B: probe_position_buffer     (read-only float32 buffer ingest)
//   4C: deform_position_buffer    (C++ allocates new result, writes
//                                  deterministic deformation, returns
//                                  as py::bytes)
//   5A: physx_probe_open/status/close   (PhysX 5 CPU-only lifecycle;
//                                        no simulation, no rigid bodies,
//                                        no collision, no GPU)
#include <pybind11/pybind11.h>

#include <PxPhysicsAPI.h>

#include <cstddef>
#include <string>
#include <vector>

namespace py = pybind11;
using namespace physx;

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
}

py::dict deform_position_buffer(
    unsigned int expected_point_count,
    unsigned int expected_float_count,
    unsigned int points_per_strand,
    int          frame_current,
    float        amplitude,
    py::buffer   input_buf)
{
    py::buffer_info info = input_buf.request(/*writable=*/false);

    const bool itemsize_ok = (info.itemsize == static_cast<py::ssize_t>(sizeof(float)));
    const bool format_ok   = (info.format == py::format_descriptor<float>::format());
    const bool size_ok     = (info.size == static_cast<py::ssize_t>(expected_float_count));
    const bool count_consistent =
        (expected_float_count == expected_point_count * 3u);
    const bool pps_ok =
        (points_per_strand >= 2u) &&
        (expected_point_count % points_per_strand == 0u);

    const bool accepted = itemsize_ok && format_ok && size_ok
                       && count_consistent && pps_ok;

    py::dict d;
    d["accepted"]          = accepted;
    d["amplitude"]         = amplitude;
    d["points_per_strand"] = points_per_strand;
    d["frame_current"]     = frame_current;
    d["float_count"]       = info.size;
    d["point_count"]       = info.size / 3;
    d["itemsize_ok"]       = itemsize_ok;
    d["format_ok"]         = format_ok;
    d["size_ok"]           = size_ok;
    d["consistent"]        = count_consistent;
    d["pps_ok"]            = pps_ok;

    if (!accepted) {
        d["message"] = "input validation failed (itemsize/format/size/consistency/pps)";
        return d;
    }

    const float* in_p = static_cast<const float*>(info.ptr);
    const std::size_t n_floats = static_cast<std::size_t>(info.size);
    const std::size_t n_points = n_floats / 3u;
    const std::size_t pps      = static_cast<std::size_t>(points_per_strand);
    const float       inv_max  = 1.0f / static_cast<float>(pps - 1u);
    const std::size_t tip_idx  = pps - 1u;

    const double f0_in[3]  = { in_p[0], in_p[1], in_p[2] };
    const double tip_in[3] = { in_p[tip_idx * 3u + 0],
                               in_p[tip_idx * 3u + 1],
                               in_p[tip_idx * 3u + 2] };

    std::vector<char> result_bytes(n_floats * sizeof(float));
    float* out_p = reinterpret_cast<float*>(result_bytes.data());

    double cs_before = 0.0;
    double cs_after  = 0.0;

    for (std::size_t i = 0; i < n_points; ++i) {
        const std::size_t pps_idx = i % pps;
        const float factor = static_cast<float>(pps_idx) * inv_max;
        const float dz     = factor * amplitude;

        const float x = in_p[i * 3u + 0];
        const float y = in_p[i * 3u + 1];
        const float z = in_p[i * 3u + 2];

        out_p[i * 3u + 0] = x;
        out_p[i * 3u + 1] = y;
        out_p[i * 3u + 2] = z + dz;

        cs_before += static_cast<double>(x) + static_cast<double>(y) + static_cast<double>(z);
        cs_after  += static_cast<double>(out_p[i * 3u + 0])
                  +  static_cast<double>(out_p[i * 3u + 1])
                  +  static_cast<double>(out_p[i * 3u + 2]);
    }

    const double f0_out[3]  = { out_p[0], out_p[1], out_p[2] };
    const double tip_out[3] = { out_p[tip_idx * 3u + 0],
                                out_p[tip_idx * 3u + 1],
                                out_p[tip_idx * 3u + 2] };

    d["first_vec3_before"] = py::make_tuple(f0_in[0],  f0_in[1],  f0_in[2]);
    d["first_vec3_after"]  = py::make_tuple(f0_out[0], f0_out[1], f0_out[2]);
    d["tip_vec3_before"]   = py::make_tuple(tip_in[0], tip_in[1], tip_in[2]);
    d["tip_vec3_after"]    = py::make_tuple(tip_out[0], tip_out[1], tip_out[2]);
    d["checksum_before"]   = cs_before;
    d["checksum_after"]    = cs_after;
    d["checksum_delta"]    = cs_after - cs_before;
    d["message"]           = "deformation applied to new result buffer; input untouched";

    d["result_buffer"] = py::bytes(result_bytes.data(),
                                   static_cast<py::ssize_t>(result_bytes.size()));

    return d;
}

// ---------------------------------------------------------------------- //
// Phase 5A: PhysX lifecycle probe
//
// CPU only. No GPU dispatcher, no CUDA context, no simulation step, no
// rigid actors, no collision data, no Curves access. The PhysX state is
// confined to this translation unit and exists only through the three
// functions below.
// ---------------------------------------------------------------------- //

namespace {

PxDefaultAllocator       g_allocator;
PxDefaultErrorCallback   g_error_callback;

PxFoundation*            g_foundation  = nullptr;
PxPhysics*               g_physics     = nullptr;
PxDefaultCpuDispatcher*  g_dispatcher  = nullptr;
PxScene*                 g_scene       = nullptr;
PxMaterial*              g_material    = nullptr;

}  // anonymous namespace

py::dict physx_probe_open()
{
    py::dict d;

    if (g_foundation != nullptr) {
        d["accepted"]       = true;
        d["already_open"]   = true;
        d["opened"]         = true;
        d["message"]        = "PhysX context already open";
        return d;
    }

    g_foundation = PxCreateFoundation(PX_PHYSICS_VERSION, g_allocator, g_error_callback);
    if (g_foundation == nullptr) {
        d["accepted"] = false;
        d["opened"]   = false;
        d["message"]  = "PxCreateFoundation failed";
        return d;
    }

    g_physics = PxCreatePhysics(
        PX_PHYSICS_VERSION,
        *g_foundation,
        PxTolerancesScale(),
        /*trackOutstandingAllocations*/ false,
        /*pvd*/ nullptr);
    if (g_physics == nullptr) {
        g_foundation->release();
        g_foundation = nullptr;
        d["accepted"] = false;
        d["opened"]   = false;
        d["message"]  = "PxCreatePhysics failed";
        return d;
    }

    g_dispatcher = PxDefaultCpuDispatcherCreate(/*numThreads*/ 2);
    if (g_dispatcher == nullptr) {
        g_physics->release();    g_physics = nullptr;
        g_foundation->release(); g_foundation = nullptr;
        d["accepted"] = false;
        d["opened"]   = false;
        d["message"]  = "PxDefaultCpuDispatcherCreate failed";
        return d;
    }

    PxSceneDesc scene_desc(g_physics->getTolerancesScale());
    scene_desc.gravity        = PxVec3(0.0f, -9.81f, 0.0f);
    scene_desc.cpuDispatcher  = g_dispatcher;
    scene_desc.filterShader   = PxDefaultSimulationFilterShader;
    g_scene = g_physics->createScene(scene_desc);
    if (g_scene == nullptr) {
        g_dispatcher->release(); g_dispatcher = nullptr;
        g_physics->release();    g_physics    = nullptr;
        g_foundation->release(); g_foundation = nullptr;
        d["accepted"] = false;
        d["opened"]   = false;
        d["message"]  = "createScene failed";
        return d;
    }

    g_material = g_physics->createMaterial(0.5f, 0.5f, 0.6f);
    // material is optional for open/close probe; ignore if it fails

    d["accepted"]      = true;
    d["already_open"]  = false;
    d["opened"]        = true;
    d["px_version"]    = static_cast<unsigned int>(PX_PHYSICS_VERSION);
    d["px_version_str"] = std::string("major=") + std::to_string(PX_PHYSICS_VERSION_MAJOR)
                        + " minor=" + std::to_string(PX_PHYSICS_VERSION_MINOR)
                        + " bugfix=" + std::to_string(PX_PHYSICS_VERSION_BUGFIX);
    d["gpu_enabled"]   = false;
    d["message"]       = "PhysX context opened (CPU only, no simulation, no rigid bodies)";
    return d;
}

py::dict physx_probe_status()
{
    py::dict d;
    d["foundation_ptr_nonnull"] = (g_foundation != nullptr);
    d["physics_ptr_nonnull"]    = (g_physics    != nullptr);
    d["dispatcher_ptr_nonnull"] = (g_dispatcher != nullptr);
    d["scene_ptr_nonnull"]      = (g_scene      != nullptr);
    d["material_ptr_nonnull"]   = (g_material   != nullptr);
    d["opened"] = (g_foundation != nullptr);
    d["state"]  = (g_foundation != nullptr) ? "opened" : "closed";
    return d;
}

py::dict physx_probe_close()
{
    py::dict d;

    if (g_foundation == nullptr) {
        d["accepted"]        = true;
        d["already_closed"]  = true;
        d["opened"]          = false;
        d["message"]         = "PhysX context already closed";
        return d;
    }

    // Release in reverse order of dependency.
    if (g_material != nullptr) {
        g_material->release();
        g_material = nullptr;
    }
    if (g_scene != nullptr) {
        g_scene->release();
        g_scene = nullptr;
    }
    if (g_dispatcher != nullptr) {
        g_dispatcher->release();
        g_dispatcher = nullptr;
    }
    if (g_physics != nullptr) {
        g_physics->release();
        g_physics = nullptr;
    }
    if (g_foundation != nullptr) {
        g_foundation->release();
        g_foundation = nullptr;
    }

    d["accepted"]        = true;
    d["already_closed"]  = false;
    d["opened"]          = false;
    d["message"]         = "PhysX context closed cleanly; all pointers nulled";
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
    m.def("probe_position_buffer", &probe_position_buffer,
          py::arg("expected_point_count"),
          py::arg("expected_float_count"),
          py::arg("frame_current"),
          py::arg("buf"));
    m.def("deform_position_buffer", &deform_position_buffer,
          py::arg("expected_point_count"),
          py::arg("expected_float_count"),
          py::arg("points_per_strand"),
          py::arg("frame_current"),
          py::arg("amplitude"),
          py::arg("input_buf"));
    m.def("physx_probe_open",   &physx_probe_open);
    m.def("physx_probe_status", &physx_probe_status);
    m.def("physx_probe_close",  &physx_probe_close);
}
