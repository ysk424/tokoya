"""Tokoya — geometric hair operations.

All functions operate on original (local-space) Curves positions.
Mesh intersection tests use world-space evaluated positions for accuracy.

Operations
----------
extend_length   : scale all strands to a target arc-length (bigger urchin).
mesh_shrink     : proportionally shrink strands to their first mesh-exit intersection.
mesh_extend     : proportionally extend strands to reach the mesh from inside.
urchin_reset    : redistribute all strand points along root-normal direction (length preserved).

Coordinate convention
---------------------
- "local"  = Curves object's local space (stored in position attribute).
- "world"  = Blender world space (after matrix_world of Curves object).
- Mesh intersection always happens in world space using the ref-mesh's evaluated geometry.
"""
from __future__ import annotations

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

_PPC = 8  # must match _spiral_plant.PPC


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _get_n_curves(curves_obj: bpy.types.Object) -> int:
    attr = curves_obj.data.attributes.get("position")
    if attr is None:
        return 0
    return len(attr.data) // _PPC


def _read_local(curves_obj: bpy.types.Object) -> np.ndarray:
    """Return (n_total, 3) float32 in local space."""
    attr = curves_obj.data.attributes.get("position")
    n    = len(attr.data)
    flat = np.zeros(n * 3, dtype=np.float32)
    attr.data.foreach_get("vector", flat)
    return flat.reshape(n, 3)


def _write_local(curves_obj: bpy.types.Object, local_pts: np.ndarray) -> None:
    """Write (n_total, 3) float32 back to local position attribute."""
    attr = curves_obj.data.attributes.get("position")
    attr.data.foreach_set("vector", local_pts.ravel().astype(np.float32))
    curves_obj.data.update_tag()


def _local_to_world(curves_obj: bpy.types.Object, local_pts: np.ndarray) -> np.ndarray:
    """Convert (n, 3) local → world using curves_obj.matrix_world."""
    mw  = np.array(curves_obj.matrix_world, dtype=np.float32)
    n   = len(local_pts)
    lh  = np.column_stack([local_pts, np.ones(n, dtype=np.float32)])
    return (lh @ mw.T)[:, :3].astype(np.float32, copy=True)


def _world_to_local(curves_obj: bpy.types.Object, world_pts: np.ndarray) -> np.ndarray:
    """Convert (n, 3) world → local."""
    mw_inv = np.array(curves_obj.matrix_world.inverted(), dtype=np.float32)
    n      = len(world_pts)
    wh     = np.column_stack([world_pts, np.ones(n, dtype=np.float32)])
    return (wh @ mw_inv.T)[:, :3].astype(np.float32, copy=True)


def _build_bvh(ref_mesh_obj: bpy.types.Object) -> BVHTree:
    """Build a world-space BVHTree from the evaluated ref mesh."""
    deps     = bpy.context.evaluated_depsgraph_get()
    eval_obj = ref_mesh_obj.evaluated_get(deps)
    mesh     = eval_obj.to_mesh()
    mat      = eval_obj.matrix_world
    verts_w  = [mat @ v.co for v in mesh.vertices]
    polys    = [tuple(p.vertices) for p in mesh.polygons]
    bvh      = BVHTree.FromPolygons(verts_w, polys)
    eval_obj.to_mesh_clear()
    return bvh


def _arc_length(pts_3d: np.ndarray) -> float:
    """Sum of segment lengths for a single strand (PPC points)."""
    return float(np.sum(np.linalg.norm(np.diff(pts_3d, axis=0), axis=1)))


# ------------------------------------------------------------------ #
# Public operations
# ------------------------------------------------------------------ #

def extend_length(curves_obj: bpy.types.Object, target_m: float) -> int:
    """Scale every strand from root so tip is target_m metres away.

    Works in local space (no mesh reference needed).
    Returns number of strands modified.
    """
    local = _read_local(curves_obj)
    n_c   = len(local) // _PPC
    mod   = 0
    for ci in range(n_c):
        b    = ci * _PPC
        root = local[b]
        cur  = _arc_length(local[b:b + _PPC])
        if cur < 1e-6:
            continue
        scale = target_m / cur
        for j in range(1, _PPC):
            local[b + j] = root + (local[b + j] - root) * scale
        mod += 1
    _write_local(curves_obj, local)
    return mod


def mesh_shrink(curves_obj: bpy.types.Object, ref_mesh_obj: bpy.types.Object) -> int:
    """Shrink each strand so its tip meets its first exit intersection with ref_mesh.

    Algorithm
    ---------
    For each strand, walk segments from root toward tip in WORLD space.
    At the first segment that ray-casts a hit on the mesh, compute:
        scale = arc-length-to-hit / total-arc-length
    Apply this scale (root-anchored) to the LOCAL positions.

    Strands that never exit the mesh are left unchanged.
    Returns number of strands shrunk.
    """
    bvh   = _build_bvh(ref_mesh_obj)
    local = _read_local(curves_obj)
    world = _local_to_world(curves_obj, local)
    n_c   = len(local) // _PPC
    shrunk = 0

    for ci in range(n_c):
        b      = ci * _PPC
        # Cumulative arc-lengths: arcs[j] = distance from root to point j
        arcs   = np.zeros(_PPC, dtype=np.float64)
        for j in range(1, _PPC):
            arcs[j] = arcs[j - 1] + float(np.linalg.norm(world[b + j] - world[b + j - 1]))
        total  = arcs[-1]
        if total < 1e-6:
            continue

        hit_arc = None
        for seg in range(_PPC - 1):
            p0 = Vector(world[b + seg].tolist())
            p1 = Vector(world[b + seg + 1].tolist())
            d  = p1 - p0
            seg_len = d.length
            if seg_len < 1e-8:
                continue
            loc, _, _, dist = bvh.ray_cast(p0, d.normalized(), seg_len)
            if loc is not None:
                hit_arc = arcs[seg] + dist
                break

        if hit_arc is None or hit_arc >= total:
            continue  # no exit intersection or tip already inside mesh

        scale = hit_arc / total
        root  = local[b]
        for j in range(1, _PPC):
            local[b + j] = root + (local[b + j] - root) * scale
        shrunk += 1

    _write_local(curves_obj, local)
    return shrunk


def mesh_extend(curves_obj: bpy.types.Object, ref_mesh_obj: bpy.types.Object) -> int:
    """Extend each strand's tip to reach the mesh from inside.

    For strands whose tip is INSIDE the mesh (i.e. the tip-direction ray
    hits the mesh ahead), scale the strand outward until the tip lands on
    the mesh surface.

    Returns number of strands extended.
    """
    bvh   = _build_bvh(ref_mesh_obj)
    local = _read_local(curves_obj)
    world = _local_to_world(curves_obj, local)
    n_c   = len(local) // _PPC
    ext   = 0

    for ci in range(n_c):
        b      = ci * _PPC
        arcs   = np.zeros(_PPC, dtype=np.float64)
        for j in range(1, _PPC):
            arcs[j] = arcs[j - 1] + float(np.linalg.norm(world[b + j] - world[b + j - 1]))
        total  = arcs[-1]
        if total < 1e-6:
            continue

        # Direction at tip: last segment direction
        tip_vec = Vector(world[b + _PPC - 1].tolist()) - Vector(world[b + _PPC - 2].tolist())
        tip_len = tip_vec.length
        if tip_len < 1e-8:
            continue
        tip_dir = tip_vec.normalized()

        tip_pt  = Vector(world[b + _PPC - 1].tolist())
        loc, _, _, dist = bvh.ray_cast(tip_pt, tip_dir, 2.0)  # 2 m search radius
        if loc is None:
            continue  # no mesh ahead of tip

        new_total = total + dist
        scale     = new_total / total
        root      = local[b]
        for j in range(1, _PPC):
            local[b + j] = root + (local[b + j] - root) * scale
        ext += 1

    _write_local(curves_obj, local)
    return ext


def urchin_reset(curves_obj: bpy.types.Object) -> int:
    """Reset every strand to a straight line along root-normal direction.

    The root-normal is estimated from the follicle segment (point[1] - point[0]).
    The current arc-length is preserved: points are redistributed at equal spacing.

    Returns number of strands reset.
    """
    local = _read_local(curves_obj)
    n_c   = len(local) // _PPC

    for ci in range(n_c):
        b         = ci * _PPC
        root      = local[b].copy()
        follicle  = local[b + 1]
        direction = follicle - root
        d_len     = float(np.linalg.norm(direction))
        if d_len < 1e-6:
            continue
        direction /= d_len  # unit vector from root toward follicle

        arc_len = _arc_length(local[b:b + _PPC])
        seg     = arc_len / (_PPC - 1)
        for j in range(1, _PPC):
            local[b + j] = root + direction * (seg * j)

    _write_local(curves_obj, local)
    return n_c
