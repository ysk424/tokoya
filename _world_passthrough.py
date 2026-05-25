"""Hair Simulation — VBD-direction Phase 0: world-coord passthrough probe.

This is an **architecture verification** module — it carries no physics
yet. The point is to nail down the data path that any future VBD
solver will plug into:

    Blender (Curves) → world coords → DUMMY simulation → world coords → Blender (Curves)

The DUMMY step is `_dummy_identity_simulation`, which returns its input
unchanged. When a VBD solver lands, the DUMMY is the only thing that
gets replaced.

**Surface Deform Geometry Nodes modifier policy**

The target Curves object `カーブ.001` carries a Geometry Nodes
modifier named "サーフェス変形" (Surface Deform GN) which produces a
~1-2 cm offset between `original` Curves position and `evaluated`
Curves position so that the hair tracks the body's evaluated surface.

Because the VBD pipeline operates in **world coordinates**, and writes
back to the **original** Curves position attribute, the GN modifier
would re-apply that offset on top of every writeback — pushing the
hair away from where the simulation actually put it. So during
passthrough/sim operation we mute the GN modifier
(`mod.show_viewport = False`). The viewport then shows
`evaluated == original`, i.e., exactly what we wrote.

The original `show_viewport` value is saved at `start()` time and
restored at `stop()` time. `unregister()` of the extension also
restores it as a safety net.

**The world coordinate round-trip itself**

Blender's `position` attribute stores Curves point positions in the
**object's local space**. To talk to the rest of the world in world
coordinates we apply `obj.matrix_world` on read and
`obj.matrix_world.inverted()` on write. In the YOKO_EXT_TEST.blend
scene the Curves object happens to have an essentially-identity
matrix_world (off-diagonals ~1e-10), but we never depend on that —
the multiplications are always performed so the pipeline is correct
under any object transform.

**Phase 1 invariants preserved**

Exactly one persistent `frame_change_post` handler, gated by
`WindowManager.hair_sim_running`. step() is called at most once per
frame change. Start / Stop / Reset semantics carry over from
Phase 6/7W lineage:

  * Start fails → `hair_sim_running` stays False, modifier untouched.
  * Stop preserves Curves state (whatever was last written), restores
    the modifier, and flips `hair_sim_running=False`.
  * Reset is a no-op for the identity passthrough — the next step()
    will read fresh from Blender anyway. Modifier state untouched
    (Reset is *not* the same as Stop, by design).
"""
from __future__ import annotations

import array
import time

import bpy
import numpy as np


TARGET_NAME    = "カーブ.001"
MODIFIER_NAME  = "サーフェス変形"


# --------------------------------------------------------------------------- #
# Dummy simulation — to be replaced by VBD later.
# --------------------------------------------------------------------------- #

def _dummy_identity_simulation(world_np: np.ndarray) -> np.ndarray:
    """The "simulation": return input unchanged.

    Inputs and outputs are both `(N, 3) float32` arrays in **world
    coordinates**. A real VBD solver will replace this function while
    keeping the same signature.
    """
    return world_np


# --------------------------------------------------------------------------- #
# Passthrough solver
# --------------------------------------------------------------------------- #

class WorldPassthrough:
    """Stateful manager of the world-coord round-trip. One instance is
    created on Start, lives for the running session, and is torn down
    on Stop / Reset → Start cycles."""

    def __init__(self) -> None:
        self._initialized                  = False
        self._step_error_active            = False
        self._target_obj_name              = None

        # Modifier mute bookkeeping.
        self._modifier_name                = None
        self._modifier_show_viewport_saved = None  # None | bool

        # Curves shape constants captured at Start.
        self._n_total                      = 0

        # Per-call telemetry.
        self._step_count                   = 0
        self._last_read_ms                 = 0.0
        self._last_dummy_ms                = 0.0
        self._last_write_ms                = 0.0

    # ---- lifecycle ----

    def start(self, obj) -> bool:
        """Acquire the target Curves, mute the Surface Deform GN
        modifier, and remember the modifier's prior `show_viewport`
        value so Stop can put it back. Returns False on any geometry
        sanity failure; caller must keep `hair_sim_running=False`."""
        self._step_error_active = False
        self._initialized       = False

        if obj is None or obj.type != "CURVES":
            print(f"[hair_sim/passthrough] start failed: target must be CURVES (got {obj})")
            return False
        attr = obj.data.attributes.get("position")
        if attr is None:
            print("[hair_sim/passthrough] start failed: no 'position' attribute on target")
            return False
        n_total = len(attr.data)
        if n_total == 0:
            print(f"[hair_sim/passthrough] start failed: empty Curves (n_total={n_total})")
            return False

        # Mute the Geometry Nodes modifier (if present). Modifier
        # may legitimately be absent (e.g., a different test scene) —
        # treat that as "nothing to mute".
        mod_name                 = None
        mod_show_viewport_saved  = None
        mod = obj.modifiers.get(MODIFIER_NAME)
        if mod is not None:
            mod_show_viewport_saved = bool(mod.show_viewport)
            mod.show_viewport       = False
            mod_name                = MODIFIER_NAME

        self._target_obj_name              = obj.name
        self._n_total                      = n_total
        self._modifier_name                = mod_name
        self._modifier_show_viewport_saved = mod_show_viewport_saved
        self._step_count                   = 0
        self._last_read_ms                 = 0.0
        self._last_dummy_ms                = 0.0
        self._last_write_ms                = 0.0
        self._initialized                  = True

        print(
            "[hair_sim/passthrough] start ok: "
            f"target={obj.name!r}, n_total={n_total}, "
            f"modifier_muted={mod_name is not None}, "
            f"prior_show_viewport={mod_show_viewport_saved}"
        )
        return True

    def stop(self) -> None:
        """Restore the GN modifier's prior `show_viewport` so the
        viewport returns to its pre-Start appearance. State is not
        otherwise destroyed (Reset-after-Stop still works)."""
        if self._modifier_name is not None and self._modifier_show_viewport_saved is not None:
            obj = bpy.data.objects.get(self._target_obj_name)
            if obj is not None:
                mod = obj.modifiers.get(self._modifier_name)
                if mod is not None:
                    mod.show_viewport = self._modifier_show_viewport_saved
        # Clear the saved value so subsequent Stop calls are no-ops
        # (preventing accidental re-mute on a second Stop).
        self._modifier_name                = None
        self._modifier_show_viewport_saved = None

    def reset(self) -> bool:
        """Reset is a no-op for the identity passthrough: there is no
        accumulated sim state to wind back. The next step() will read
        fresh values from Blender's current Curves attribute.

        Modifier state is intentionally NOT touched here. Reset is
        not Stop — the user may want to keep the sim active and just
        re-anchor history (which, for identity, is trivially "now")."""
        self._step_count        = 0
        self._step_error_active = False
        return True

    # ---- per-frame ----

    def step(self) -> bool:
        """Read all Curves positions → convert to world → pass through
        dummy → convert back to local → write back to Curves. Exactly
        one foreach_get / one foreach_set per call. Returns True if
        the writeback completed, False on any error."""
        if self._step_error_active or not self._initialized:
            return False

        obj = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            self._step_error_active = True
            print("[hair_sim/passthrough] step error: target object disappeared")
            return False
        attr = obj.data.attributes.get("position")
        if attr is None or len(attr.data) != self._n_total:
            self._step_error_active = True
            print("[hair_sim/passthrough] step error: attribute geometry mismatch")
            return False

        n = self._n_total
        try:
            # 1. Read local-space positions out of Blender.
            t_r0 = time.perf_counter()
            buf = array.array('f', [0.0] * (n * 3))
            attr.data.foreach_get("vector", buf)
            local_np = np.frombuffer(buf, dtype=np.float32).reshape(n, 3)
            t_r1 = time.perf_counter()

            # 2. Convert to world coords via obj.matrix_world.
            mw = np.array(obj.matrix_world, dtype=np.float32)              # (4,4)
            local_h = np.column_stack([local_np, np.ones(n, dtype=np.float32)])
            world_h = local_h @ mw.T
            world_np = world_h[:, :3].astype(np.float32, copy=True)        # (N, 3)

            # 3. Dummy "simulation" — identity. Output is world coords.
            t_d0 = time.perf_counter()
            result_world_np = _dummy_identity_simulation(world_np)
            t_d1 = time.perf_counter()

            # 4. Convert back to local via matrix_world.inverted().
            mw_inv = np.array(obj.matrix_world.inverted(), dtype=np.float32)
            result_h = np.column_stack([
                result_world_np, np.ones(n, dtype=np.float32)
            ])
            result_local_h  = result_h @ mw_inv.T
            result_local_np = result_local_h[:, :3].astype(np.float32, copy=True)

            # 5. Write back to ORIGINAL Curves and tag depsgraph.
            t_w0 = time.perf_counter()
            attr.data.foreach_set(
                "vector",
                array.array('f', result_local_np.flatten().tolist())
            )
            obj.data.update_tag()
            t_w1 = time.perf_counter()
        except Exception as exc:
            self._step_error_active = True
            print(f"[hair_sim/passthrough] step error (suppressing): {exc!r}")
            return False

        self._step_count    += 1
        self._last_read_ms   = (t_r1 - t_r0) * 1000.0
        self._last_dummy_ms  = (t_d1 - t_d0) * 1000.0
        self._last_write_ms  = (t_w1 - t_w0) * 1000.0
        return True

    # ---- introspection ----

    def status(self) -> dict:
        return {
            "initialized":                      self._initialized,
            "step_error_active":                self._step_error_active,
            "target_object":                    self._target_obj_name,
            "modifier_name":                    self._modifier_name,
            "modifier_show_viewport_saved":     self._modifier_show_viewport_saved,
            "n_total":                          self._n_total,
            "step_count":                       self._step_count,
            "last_read_ms":                     self._last_read_ms,
            "last_dummy_ms":                    self._last_dummy_ms,
            "last_write_ms":                    self._last_write_ms,
        }
