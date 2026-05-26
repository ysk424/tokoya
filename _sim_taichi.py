"""Taichi XPBD solver for hair simulation.

Usage:
    cls = get_solver_class()        # lazy ti.init()
    solver = cls(n_total, n_strands, pps, init_positions, ...)
    solver.set_positions_velocities(pos_np, vel_np)
    pos_out = solver.run_frame(dt, n_substeps, n_iter, gravity,
                               new_root_world, seg_ke, bend_ke,
                               damping, bending_enabled)
    vel_out = solver.get_velocities_numpy()
"""
from __future__ import annotations

import sys
import site
import numpy as np

_PYTHON_USER_SITE = r"C:\Users\azoo\AppData\Roaming\Python\Python313\site-packages"

_ti              = None   # cached taichi module
_SolverClass     = None   # cached @ti.data_oriented class


def _ensure_taichi():
    global _ti
    if _ti is not None:
        return _ti
    if _PYTHON_USER_SITE not in sys.path:
        site.addsitedir(_PYTHON_USER_SITE)
    import taichi as ti
    try:
        ti.init(arch=ti.cuda, device_memory_fraction=0.5)
        print("[hair_sim/taichi] CUDA initialized (sm_120 OK)")
    except Exception as e:
        print(f"[hair_sim/taichi] CUDA failed ({e}), falling back to CPU")
        ti.init(arch=ti.cpu)
        print("[hair_sim/taichi] CPU initialized")
    _ti = ti
    return ti


def get_solver_class():
    """Return (creating if needed) the TaichiXPBDSolver class.
    Must be called after Taichi is importable."""
    global _SolverClass
    if _SolverClass is not None:
        return _SolverClass

    ti = _ensure_taichi()

    @ti.data_oriented
    class TaichiXPBDSolver:
        """XPBD strand solver. All coordinates in world space."""

        def __init__(
            self,
            n_total:        int,
            n_strands:      int,
            pps:            int,            # points per strand
            init_pos:       np.ndarray,     # (n_total, 3) float32 world
            particle_mass:  float,
            bending_enabled: bool,
        ):
            self.n_total   = n_total
            self.n_strands = n_strands
            self.pps       = pps

            self.pos       = ti.Vector.field(3, dtype=ti.f32, shape=n_total)
            self.vel       = ti.Vector.field(3, dtype=ti.f32, shape=n_total)
            self.pos_pred  = ti.Vector.field(3, dtype=ti.f32, shape=n_total)
            self.inv_mass  = ti.field(dtype=ti.f32, shape=n_total)
            self.seg_rest  = ti.field(dtype=ti.f32, shape=(n_strands, pps - 1))
            # bend_rest allocated even when disabled (dummy shape prevents
            # out-of-bounds in the kernel; just unused)
            bend_shape = (n_strands, max(pps - 2, 1))
            self.bend_rest = ti.field(dtype=ti.f32, shape=bend_shape)

            self._setup(init_pos, particle_mass, bending_enabled)

        # ------------------------------------------------------------------ #

        def _setup(self, init_pos: np.ndarray, particle_mass: float, bending_enabled: bool):
            n, ns, pps = self.n_total, self.n_strands, self.pps
            pos_f = np.ascontiguousarray(init_pos, dtype=np.float32)

            self.pos.from_numpy(pos_f)
            self.vel.from_numpy(np.zeros((n, 3), dtype=np.float32))
            self.pos_pred.from_numpy(pos_f)

            inv_m = np.full(n, 1.0 / particle_mass, dtype=np.float32)
            inv_m[np.arange(ns, dtype=np.int32) * pps] = 0.0   # roots kinematic
            self.inv_mass.from_numpy(inv_m)

            sr = np.zeros((ns, pps - 1), dtype=np.float32)
            for s in range(ns):
                b = s * pps
                for k in range(pps - 1):
                    sr[s, k] = max(float(np.linalg.norm(pos_f[b+k] - pos_f[b+k+1])), 1e-6)
            self.seg_rest.from_numpy(sr)

            if bending_enabled and pps >= 3:
                br = np.zeros((ns, pps - 2), dtype=np.float32)
                for s in range(ns):
                    b = s * pps
                    for k in range(pps - 2):
                        br[s, k] = max(float(np.linalg.norm(pos_f[b+k] - pos_f[b+k+2])), 1e-6)
                self.bend_rest.from_numpy(br)

        # ------------------------------------------------------------------ #
        # Upload / download
        # ------------------------------------------------------------------ #

        def set_positions_velocities(self, pos_np: np.ndarray, vel_np: np.ndarray):
            self.pos.from_numpy(np.ascontiguousarray(pos_np, dtype=np.float32))
            self.vel.from_numpy(np.ascontiguousarray(vel_np, dtype=np.float32))

        def get_positions_numpy(self) -> np.ndarray:
            return self.pos.to_numpy()

        def get_velocities_numpy(self) -> np.ndarray:
            return self.vel.to_numpy()

        # ------------------------------------------------------------------ #
        # Kernels
        # ------------------------------------------------------------------ #

        @ti.kernel
        def _set_roots(self, roots: ti.types.ndarray(ndim=2)):
            """roots: (n_strands, 3) float32 — new world positions for root particles."""
            for s in range(self.n_strands):
                i = s * self.pps
                p = ti.Vector([roots[s, 0], roots[s, 1], roots[s, 2]])
                self.pos[i]      = p
                self.pos_pred[i] = p

        @ti.kernel
        def _predict(self, dt: ti.f32, gravity: ti.f32):
            for i in range(self.n_total):
                if self.inv_mass[i] > 0.0:
                    self.vel[i][2] += gravity * dt
                    self.pos_pred[i] = self.pos[i] + self.vel[i] * dt
                # kinematic roots: already set by _set_roots

        @ti.kernel
        def _solve_springs(
            self, dt: ti.f32,
            seg_ke: ti.f32, bend_ke: ti.f32,
            do_bend: int,
        ):
            for s in range(self.n_strands):   # ← parallel over strands
                base = s * self.pps

                # Segment springs (i, i+1) — sequential within strand
                for k in range(self.pps - 1):
                    i = base + k
                    j = base + k + 1
                    wi = self.inv_mass[i]
                    wj = self.inv_mass[j]
                    if wi + wj > 1e-10:
                        d    = self.pos_pred[i] - self.pos_pred[j]
                        dist = d.norm()
                        if dist > 1e-8:
                            C     = dist - self.seg_rest[s, k]
                            alpha = 1.0 / (seg_ke * dt * dt)
                            dlam  = -C / (wi + wj + alpha)
                            grad  = d / dist
                            self.pos_pred[i] += wi * dlam * grad
                            self.pos_pred[j] -= wj * dlam * grad

                # Bending springs (i, i+2)
                if do_bend == 1:
                    for k in range(self.pps - 2):
                        i = base + k
                        j = base + k + 2
                        wi = self.inv_mass[i]
                        wj = self.inv_mass[j]
                        if wi + wj > 1e-10:
                            d    = self.pos_pred[i] - self.pos_pred[j]
                            dist = d.norm()
                            if dist > 1e-8:
                                C     = dist - self.bend_rest[s, k]
                                alpha = 1.0 / (bend_ke * dt * dt)
                                dlam  = -C / (wi + wj + alpha)
                                grad  = d / dist
                                self.pos_pred[i] += wi * dlam * grad
                                self.pos_pred[j] -= wj * dlam * grad

        @ti.kernel
        def _update_vel_pos(self, dt: ti.f32, damping: ti.f32):
            for i in range(self.n_total):
                if self.inv_mass[i] > 0.0:
                    self.vel[i] = (self.pos_pred[i] - self.pos[i]) / dt * (1.0 - damping)
                    self.pos[i] = self.pos_pred[i]

        @ti.kernel
        def _upload_pos(self, positions: ti.types.ndarray(ndim=2)):
            """Push corrected positions (e.g. after body collision) back into pos."""
            for i in range(self.n_total):
                self.pos[i] = ti.Vector([positions[i, 0], positions[i, 1], positions[i, 2]])

        # ------------------------------------------------------------------ #
        # High-level entry point
        # ------------------------------------------------------------------ #

        def run_frame(
            self,
            dt:              float,
            n_substeps:      int,
            n_iter:          int,
            gravity:         float,
            new_root_world:  np.ndarray,   # (n_strands, 3)
            seg_ke:          float,
            bend_ke:         float,
            damping:         float,
            bending_enabled: bool,
        ) -> np.ndarray:
            """Run one Blender frame → return final (n_total, 3) positions."""
            dt_sub   = float(dt) / float(n_substeps)
            roots_np = np.ascontiguousarray(new_root_world, dtype=np.float32)
            do_bend  = int(bending_enabled)

            for _ in range(n_substeps):
                self._set_roots(roots_np)
                self._predict(dt_sub, float(gravity))
                for _ in range(n_iter):
                    self._solve_springs(dt_sub, float(seg_ke), float(bend_ke), do_bend)
                self._update_vel_pos(dt_sub, float(damping))

            return self.pos.to_numpy()

    _SolverClass = TaichiXPBDSolver
    return TaichiXPBDSolver


# ------------------------------------------------------------------ #
# Body collision (Python / Blender BVHTree — called after run_frame)
# ------------------------------------------------------------------ #

def build_body_bvh(body_name: str):
    """Build a BVHTree from the evaluated (skinned) body mesh."""
    import bpy
    from mathutils.bvhtree import BVHTree
    body_obj = bpy.data.objects.get(body_name)
    if body_obj is None or body_obj.type != "MESH":
        return None
    dg = bpy.context.evaluated_depsgraph_get()
    return BVHTree.FromObject(body_obj.evaluated_get(dg), dg, epsilon=0.0)


def apply_body_collision(positions: np.ndarray, bvh, margin: float = 0.003) -> None:
    """Push hair particles out of body mesh. Modifies positions in-place.

    Uses BVHTree.find_nearest: if a particle is closer than `margin` to the
    surface (measured along the face normal), it is pushed outward.
    """
    from mathutils import Vector
    for i in range(len(positions)):
        pt       = Vector(positions[i])
        loc, normal, _, _ = bvh.find_nearest(pt)
        if loc is None or normal is None:
            continue
        depth = (pt - loc).dot(normal)   # >0 outside, <0 inside
        if depth < margin:
            c = normal * (margin - depth)
            positions[i, 0] += c.x
            positions[i, 1] += c.y
            positions[i, 2] += c.z
