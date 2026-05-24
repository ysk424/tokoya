#pragma once

#include <cstdint>
#include <vector>

namespace hairsim {

struct StrandLayout {
    std::uint32_t strand_count   = 0;
    std::uint32_t points_per_strand = 0;
};

struct SolverConfig {
    float    timestep        = 1.0f / 60.0f;
    float    gravity[3]      = {0.0f, 0.0f, -9.81f};
    bool     use_gpu         = true;
    std::uint32_t substeps   = 4;
};

class HairSolver {
public:
    HairSolver();
    ~HairSolver();

    HairSolver(const HairSolver&) = delete;
    HairSolver& operator=(const HairSolver&) = delete;

    bool initialize(const SolverConfig& cfg);
    void shutdown();

    // points: flat xyz buffer length = strand_count * points_per_strand * 3
    void set_strands(const StrandLayout& layout, const float* points);
    void step(float dt);
    void get_points(float* out_points) const;

    [[nodiscard]] bool   is_gpu_enabled() const noexcept;
    [[nodiscard]] StrandLayout layout()  const noexcept;

private:
    struct Impl;
    Impl* impl_;
};

}  // namespace hairsim
