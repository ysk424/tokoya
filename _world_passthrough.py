"""Hair simulation — state management + bake + per-frame dispatch.

This module owns:
  * Per-frame hair state (positions + velocities in world coords) in `_prev_state`.
  * Full-animation RAM bake: `_bake_positions / _bake_velocities / _bake_mask`.
  * The simulation step: currently a placeholder (identity passthrough). Taichi
    XPBD implementation will replace `_run_one_simulation_step`.
  * Scrub-restore: baked frames are pushed back to Blender without re-simulating.

α strategy (head-tracked roots + modifier-offset compensation):
  The Surface Deform GN modifier ("サーフェス変形") stays active. Every sim step:
    1. Read evaluated (head-tracked) world positions.
    2. Measure per-particle modifier offset: offset = evaluated − original.
    3. Simulation output (sim_out) is in world coords, head-tracked.
    4. Write to ORIGINAL: sim_out − offset. Modifier then produces
       evaluated = written + offset = sim_out. No double-tracking.

Mode dispatch lives in `__init__.py` (frame_change_post handler).
"""
from __future__ import annotations

from dataclasses import dataclass

import bpy
import numpy as np


TARGET_NAME       = "カーブ.001"
POINTS_PER_STRAND = 8    # Uniform — verified in Phase 3A scene investigation.

# Python user site-packages path (Blender's bundled Python doesn't add it
# to sys.path by default). Used to find Taichi once it is installed.
_PYTHON_USER_SITE = r"C:\Users\azoo\AppData\Roaming\Python\Python313\site-packages"

# ---- Simulation parameters (written from WM at each Start) ----
SPRING_KE             = 1e4
SPRING_KD             = 0.01
PARTICLE_MASS         = 1.0
GRAVITY               = -9.81
ITERATIONS            = 10
SUBSTEPS              = 4
BENDING_ENABLED       = True
BENDING_KE            = 10.0
BENDING_KD            = 0.01
BODY_COLLISION_ENABLED = True
BODY_COLLISION_TARGET  = "CC_Base_Body"


@dataclass
class HairFrameState:
    """One frame's hair snapshot in world coordinates."""
    points_world:     np.ndarray   # (n_total, 3) float32
    velocities_world: np.ndarray   # (n_total, 3) float32
    frame:            int


class WorldPassthrough:
    """Stateful manager: state evolution + RAM bake.

    One instance lives across mode changes (Stop/Bypass do not tear it
    down). Only `unregister()` calls teardown()."""

    def __init__(self) -> None:
        self._initialized       = False
        self._step_error_active = False
        self._target_obj_name   = None

        self._n_total           = 0
        self._root_indices      = None  # (n_strands,) int32

        # State evolution — always updated together.
        self._last_frame        = None
        self._prev_state        = None  # type: HairFrameState | None

        # RAM bake.
        self._bake_positions    = None  # (n_frames, n_total, 3) float32
        self._bake_velocities   = None  # (n_frames, n_total, 3) float32
        self._bake_mask         = None  # (n_frames,) bool
        self._bake_frame_start  = None
        self._bake_frame_end    = None

        self._step_count        = 0

    # ------------------------------------------------------------------ #
    # Bake helpers
    # ------------------------------------------------------------------ #

    def _allocate_bake(self, scene: bpy.types.Scene) -> None:
        fs = int(scene.frame_start)
        fe = int(scene.frame_end)
        if fe < fs:
            fe = fs
        n_frames = fe - fs + 1
        desired_shape = (n_frames, self._n_total, 3)
        if self._bake_positions is None or self._bake_positions.shape != desired_shape:
            self._bake_positions  = np.zeros(desired_shape, dtype=np.float32)
            self._bake_velocities = np.zeros(desired_shape, dtype=np.float32)
            self._bake_mask       = np.zeros(n_frames, dtype=bool)
        else:
            self._bake_mask[:] = False
        self._bake_frame_start = fs
        self._bake_frame_end   = fe

    def _frame_to_bake_index(self, frame: int) -> int | None:
        if self._bake_frame_start is None or self._bake_frame_end is None:
            return None
        if frame < self._bake_frame_start or frame > self._bake_frame_end:
            return None
        return frame - self._bake_frame_start

    def _store_prev_state_to_bake(self) -> bool:
        if self._prev_state is None:
            return False
        idx = self._frame_to_bake_index(self._prev_state.frame)
        if idx is None:
            return False
        self._bake_positions [idx] = self._prev_state.points_world
        self._bake_velocities[idx] = self._prev_state.velocities_world
        self._bake_mask      [idx] = True
        return True

    def _restore_from_bake(self, frame: int) -> bool:
        """Push baked state at `frame` to Blender ORIGINAL Curves."""
        idx = self._frame_to_bake_index(frame)
        if idx is None or not self._bake_mask[idx]:
            return False
        obj = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            return False
        attr = obj.data.attributes.get("position")
        if attr is None or len(attr.data) != self._n_total:
            return False

        n         = self._n_total
        world_pts = self._bake_positions [idx]
        vels      = self._bake_velocities[idx]

        # Apply the same modifier-offset compensation as the SIM path so
        # PLAYBACK and SIMULATING write identical values → identical visuals.
        dg       = bpy.context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(dg)
        eval_w   = self._read_world_positions(obj_eval.data)
        orig_w   = self._read_world_positions(obj.data)
        if eval_w is None or orig_w is None:
            return False
        write_world = world_pts - (eval_w - orig_w)

        mw_inv  = np.array(obj.matrix_world.inverted(), dtype=np.float32)
        world_h = np.column_stack([write_world, np.ones(n, dtype=np.float32)])
        local_pts = (world_h @ mw_inv.T)[:, :3].astype(np.float32, copy=True)

        attr.data.foreach_set("vector", local_pts.ravel())
        obj.data.update_tag()

        self._prev_state = HairFrameState(
            points_world     = world_pts.copy(),
            velocities_world = vels.copy(),
            frame            = frame,
        )
        self._last_frame = frame
        return True

    # ------------------------------------------------------------------ #
    # State capture
    # ------------------------------------------------------------------ #

    def _read_world_positions(self, attributes_owner) -> np.ndarray | None:
        """Read `position` attribute and convert to world coords.
        Returns (n_total, 3) float32, or None on failure."""
        attr = attributes_owner.attributes.get("position")
        if attr is None or len(attr.data) != self._n_total:
            return None
        n = self._n_total
        local_flat = np.zeros(n * 3, dtype=np.float32)
        attr.data.foreach_get("vector", local_flat)
        local_pts = local_flat.reshape(n, 3)
        obj = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            return None
        mw      = np.array(obj.matrix_world, dtype=np.float32)
        local_h = np.column_stack([local_pts, np.ones(n, dtype=np.float32)])
        return (local_h @ mw.T)[:, :3].astype(np.float32, copy=True)

    def _capture_current_state(
        self,
        scene: bpy.types.Scene,
        derive_velocity_from_prev: bool = False,
    ) -> bool:
        """Snapshot current frame's hair state from EVALUATED data.

        `_last_frame` and `_prev_state` are updated atomically — both
        succeed or both are cleared to None. Never left inconsistent."""
        prior = self._prev_state
        frame = scene.frame_current
        obj   = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            self._last_frame = None
            self._prev_state = None
            return False

        dg       = bpy.context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(dg)
        world_pts = self._read_world_positions(obj_eval.data)
        if world_pts is None:
            self._last_frame = None
            self._prev_state = None
            return False

        if (
            derive_velocity_from_prev
            and prior is not None
            and prior.points_world.shape == world_pts.shape
        ):
            dt = float(scene.render.fps_base) / float(scene.render.fps)
            vels = ((world_pts - prior.points_world) / dt).astype(np.float32, copy=False)
        else:
            vels = np.zeros_like(world_pts)

        self._prev_state = HairFrameState(
            points_world     = world_pts,
            velocities_world = vels,
            frame            = frame,
        )
        self._last_frame = frame
        return True

    # ------------------------------------------------------------------ #
    # Simulation step — Taichi XPBD goes here
    # ------------------------------------------------------------------ #

    def _run_one_simulation_step(self, scene: bpy.types.Scene) -> bool:
        """Advance hair state by one frame.

        TODO: replace the identity placeholder below with Taichi XPBD.

        Contract (must be preserved by any replacement):
          * Read EVALUATED world positions for roots (head boundary).
          * Compute modifier offset = evaluated − original.
          * Produce sim_out (n_total, 3) float32 in world coords.
          * Write: original ← sim_out − offset  (modifier adds offset back).
          * Atomically update self._prev_state and self._last_frame.
          * Return True on success, False on any failure (state unchanged).
        """
        if self._prev_state is None:
            return False
        obj = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            return False

        n  = self._n_total
        dt = float(scene.render.fps_base) / float(scene.render.fps)

        dg       = bpy.context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(dg)
        eval_world = self._read_world_positions(obj_eval.data)
        orig_world = self._read_world_positions(obj.data)
        if eval_world is None or orig_world is None:
            return False
        offset_world = eval_world - orig_world

        # ---- Taichi XPBD will replace this block ----
        # Placeholder: identity passthrough (hair follows head, no physics).
        sim_out = eval_world.copy()
        # ---- end placeholder ----

        write_world = sim_out - offset_world
        mw_inv  = np.array(obj.matrix_world.inverted(), dtype=np.float32)
        world_h = np.column_stack([write_world, np.ones(n, dtype=np.float32)])
        local_pts = (world_h @ mw_inv.T)[:, :3].astype(np.float32, copy=True)

        attr = obj.data.attributes.get("position")
        if attr is None or len(attr.data) != n:
            return False
        attr.data.foreach_set("vector", local_pts.ravel())
        obj.data.update_tag()

        new_vel = ((sim_out - self._prev_state.points_world) / dt).astype(
            np.float32, copy=False
        )
        self._prev_state = HairFrameState(
            points_world     = sim_out,
            velocities_world = new_vel,
            frame            = scene.frame_current,
        )
        self._last_frame = scene.frame_current
        return True

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def start(self, obj, scene: bpy.types.Scene) -> bool:
        """Initialize at the current frame. Allocates (or reuses) the bake,
        captures the initial state, and stores it."""
        self._step_error_active = False
        self._initialized       = False
        self._last_frame        = None
        self._prev_state        = None

        if obj is None or obj.type != "CURVES":
            print(f"[hair_sim] start failed: target must be CURVES (got {obj})")
            return False
        attr = obj.data.attributes.get("position")
        if attr is None:
            print("[hair_sim] start failed: no 'position' attribute on target")
            return False
        n_total = len(attr.data)
        if n_total == 0:
            print(f"[hair_sim] start failed: empty Curves")
            return False
        if n_total % POINTS_PER_STRAND != 0:
            print(
                f"[hair_sim] start failed: n_total ({n_total}) not divisible "
                f"by POINTS_PER_STRAND ({POINTS_PER_STRAND})"
            )
            return False

        fs, fe, fc = int(scene.frame_start), int(scene.frame_end), int(scene.frame_current)
        if fc < fs or fc > fe:
            print(
                f"[hair_sim] start failed: frame {fc} outside range [{fs}..{fe}]"
            )
            return False

        self._target_obj_name = obj.name
        self._n_total         = n_total
        self._step_count      = 0
        self._initialized     = True

        n_strands = n_total // POINTS_PER_STRAND
        self._root_indices = (np.arange(n_strands, dtype=np.int32) * POINTS_PER_STRAND)

        self._allocate_bake(scene)

        if not self._capture_current_state(scene, derive_velocity_from_prev=False):
            print("[hair_sim] start failed: initial capture returned no state")
            self._initialized = False
            return False
        self._store_prev_state_to_bake()

        n_frames = self._bake_frame_end - self._bake_frame_start + 1
        bake_mb  = (self._bake_positions.nbytes / (1024 * 1024)
                    if self._bake_positions is not None else 0)
        print(
            f"[hair_sim] start ok: target={obj.name!r}, n_total={n_total}, "
            f"frame={self._last_frame}, "
            f"bake=[{self._bake_frame_start}..{self._bake_frame_end}] "
            f"({n_frames} frames, ~{bake_mb:.0f} MB × 2)"
        )
        return True

    def teardown(self) -> None:
        """Free all per-session state. Called only by unregister()."""
        self._last_frame       = None
        self._prev_state       = None
        self._root_indices     = None
        self._bake_positions   = None
        self._bake_velocities  = None
        self._bake_mask        = None
        self._bake_frame_start = None
        self._bake_frame_end   = None
        self._initialized      = False
        self._step_error_active = False

    # ------------------------------------------------------------------ #
    # Per-frame entries from handler
    # ------------------------------------------------------------------ #

    def step(self, scene: bpy.types.Scene) -> bool:
        """SIMULATING-mode per-frame entry.

        1. Baked frame → restore from bake.
        2. Consecutive +1 → simulate, bake.
        3. Jump into unbaked area → re-baseline only.
        """
        if self._step_error_active or not self._initialized:
            return False
        if self._last_frame is None:
            return False

        M   = scene.frame_current
        idx = self._frame_to_bake_index(M)

        try:
            if idx is not None and self._bake_mask[idx]:
                self._restore_from_bake(M)
                return True

            if M == self._last_frame + 1:
                ok = self._run_one_simulation_step(scene)
                if ok:
                    self._store_prev_state_to_bake()
                    self._step_count += 1
                return True

            # Jump: re-baseline, no bake.
            self._capture_current_state(scene, derive_velocity_from_prev=False)
            return True
        except Exception as exc:
            self._step_error_active = True
            print(f"[hair_sim] step error (suppressing): {exc!r}")
            return False

    def playback(self, scene: bpy.types.Scene) -> bool:
        """PLAYBACK-mode: push baked state if available, else do nothing."""
        if not self._initialized:
            return False
        M   = scene.frame_current
        idx = self._frame_to_bake_index(M)
        if idx is None or not self._bake_mask[idx]:
            return False
        try:
            self._restore_from_bake(M)
            return True
        except Exception as exc:
            print(f"[hair_sim] playback error (suppressing): {exc!r}")
            return False

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    def status(self) -> dict:
        prev_summary = None
        if self._prev_state is not None:
            pts = self._prev_state.points_world
            vel = self._prev_state.velocities_world
            non_root = (np.arange(pts.shape[0]) % POINTS_PER_STRAND) != 0
            prev_summary = {
                "frame":            self._prev_state.frame,
                "root0_world_xyz":  [float(x) for x in pts[0]],
                "tip0_world_xyz":   [float(x) for x in pts[POINTS_PER_STRAND - 1]],
                "z_mean_non_root":  float(pts[non_root, 2].mean()),
                "vel_max_abs":      float(np.abs(vel).max()),
            }
        bake_summary = None
        if self._bake_mask is not None:
            bake_summary = {
                "frame_range":    [self._bake_frame_start, self._bake_frame_end],
                "n_baked":        int(self._bake_mask.sum()),
                "buffer_mb_each": round(
                    self._bake_positions.nbytes / (1024 * 1024), 2
                ) if self._bake_positions is not None else None,
            }
        return {
            "initialized":       self._initialized,
            "step_error_active": self._step_error_active,
            "target_object":     self._target_obj_name,
            "n_total":           self._n_total,
            "last_frame":        self._last_frame,
            "step_count":        self._step_count,
            "prev_state":        prev_summary,
            "bake":              bake_summary,
        }
