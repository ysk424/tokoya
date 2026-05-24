#include "hair_solver.h"

#include <algorithm>
#include <cstring>

#if defined(HAIRSIM_HAVE_PHYSX)
    // PhysX includes are intentionally not pulled in yet — the actual
    // solver wiring lands once extern/PhysX is built. We keep the
    // translation unit valid so the module builds end-to-end first.
#endif

namespace hairsim {

struct HairSolver::Impl {
    SolverConfig          cfg{};
    StrandLayout          layout{};
    std::vector<float>    positions;
    bool                  initialized = false;
};

HairSolver::HairSolver()  : impl_(new Impl()) {}
HairSolver::~HairSolver() { shutdown(); delete impl_; }

bool HairSolver::initialize(const SolverConfig& cfg) {
    impl_->cfg = cfg;
    impl_->initialized = true;
    return true;
}

void HairSolver::shutdown() {
    if (!impl_) return;
    impl_->initialized = false;
    impl_->positions.clear();
    impl_->layout = {};
}

void HairSolver::set_strands(const StrandLayout& layout, const float* points) {
    impl_->layout = layout;
    const std::size_t n = std::size_t(layout.strand_count) * layout.points_per_strand * 3u;
    impl_->positions.assign(points, points + n);
}

void HairSolver::step(float dt) {
    if (!impl_->initialized) return;

    // Placeholder integrator: apply gravity to every point so the build
    // can be smoke-tested before PhysX is wired in.
    const float* g = impl_->cfg.gravity;
    const std::size_t n = impl_->positions.size() / 3u;
    for (std::size_t i = 0; i < n; ++i) {
        impl_->positions[i * 3 + 0] += g[0] * dt * dt;
        impl_->positions[i * 3 + 1] += g[1] * dt * dt;
        impl_->positions[i * 3 + 2] += g[2] * dt * dt;
    }
}

void HairSolver::get_points(float* out_points) const {
    std::memcpy(out_points, impl_->positions.data(),
                impl_->positions.size() * sizeof(float));
}

bool         HairSolver::is_gpu_enabled() const noexcept { return impl_->cfg.use_gpu; }
StrandLayout HairSolver::layout()         const noexcept { return impl_->layout; }

}  // namespace hairsim
