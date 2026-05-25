"""Hair Simulation — Phase 7W-B: bundled NVIDIA Warp kernels.

Plain .py module so that Warp's `@wp.kernel` decorator can inspect the
kernel function source via `inspect.getsourcelines()`. Phase 7W-A
showed that MCP-injected `exec()` code cannot host `@wp.kernel`
definitions (Warp rejects with
`RuntimeError: Directly evaluating Warp code defined as a string using
exec() is not supported`). Kernel sources must live in real .py files,
which is what this module is for.

`warp` is imported at module load time, so importing this module on a
host that does not have `warp-lang` installed into Blender's bundled
Python will fail. That is intentional for Phase 7W-B: the Phase 7W-B
spec authorises bundling but explicitly forbids the SolverInterface
wiring, so nothing else in the extension touches this module yet.
A future phase that wires Warp into SolverInterface will need to gate
on availability before importing.

No `__init__.py` / `SolverInterface` integration in Phase 7W-B. The
extension's existing Start / Stop / Reset / frame_change_post path
continues to use the C++ NativeHairSolver from Phase 6C — Warp is not
yet driving any visible behaviour.
"""
from __future__ import annotations

import warp as wp


@wp.kernel
def add_one_kernel(a: wp.array(dtype=wp.float32)):
    """Trivial Warp kernel: add 1.0 to each float32 element.

    Used as the smallest-possible compile + launch + readback probe.
    """
    tid = wp.tid()
    a[tid] = a[tid] + 1.0


@wp.kernel
def passthrough_vec3(
    in_arr: wp.array(dtype=wp.vec3),
    out_arr: wp.array(dtype=wp.vec3),
):
    """Copy each vec3 input element to the matching output slot.

    Used to confirm that a Curves-derived anchor array survives a
    round-trip through a Warp GPU kernel bit-for-bit (Phase 7W-A
    established the baseline; Phase 7W-B confirms the same result
    when the kernel is bundled inside the extension).
    """
    tid = wp.tid()
    out_arr[tid] = in_arr[tid]
