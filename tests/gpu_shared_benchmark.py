import importlib.util
import pathlib
import sys
import time

import bpy
import numpy as np
import warp as wp


ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "tokoya_benchmark",
    ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules["tokoya_benchmark"] = addon
spec.loader.exec_module(addon)

from tokoya_benchmark import _sim_taichi
from tokoya_benchmark import _world_passthrough as wp_config
from tokoya_benchmark._collision_warp import WarpBodyCollider
from tokoya_benchmark._sim_warp import WarpXPBDSolver


@wp.kernel
def count_crossings(
    mesh: wp.uint64,
    positions: wp.array(dtype=wp.vec3),
    points_per_strand: int,
    crossings: wp.array(dtype=wp.int32),
):
    segment_id = wp.tid()
    segments_per_strand = points_per_strand - 1
    strand = segment_id // segments_per_strand
    segment = segment_id % segments_per_strand
    i = strand * points_per_strand + segment
    p0 = positions[i]
    p1 = positions[i + 1]
    delta = p1 - p0
    distance = wp.length(delta)
    if distance > 1.0e-9:
        ray = wp.mesh_query_ray(mesh, p0, delta / distance, distance)
        if ray.result and ray.t > 1.0e-6 and ray.t < distance - 1.0e-6:
            wp.atomic_add(crossings, 0, 1)


curves_objects = [obj for obj in bpy.data.objects if obj.type == "CURVES"]
assert len(curves_objects) == 1, len(curves_objects)
curves = curves_objects[0]
body_name = "CC_Base_Body"
assert bpy.data.objects.get(body_name) is not None

n_total = len(curves.data.attributes["position"].data)
pps = wp_config.POINTS_PER_STRAND
assert n_total % pps == 0
n_strands = n_total // pps
depsgraph = bpy.context.evaluated_depsgraph_get()
evaluated = curves.evaluated_get(depsgraph)
positions = wp_config._read_world(
    evaluated.data, n_total, evaluated.matrix_world
)
roots = positions[np.arange(n_strands) * pps]
point1s = positions[np.arange(n_strands) * pps + 1]
zeros = np.zeros_like(positions)


def make_collider():
    return WarpBodyCollider(
        body_name=body_name,
        n_total=n_total,
        points_per_strand=pps,
        margin=wp_config.COLLISION_MARGIN,
        search_distance=wp_config.COLLISION_SEARCH,
    )


def run(solver, collider):
    solver.set_positions_velocities(positions, zeros)
    start = time.perf_counter()
    output = solver.run_frame(
        dt=1.0 / 24.0,
        n_substeps=wp_config.SUBSTEPS,
        n_iter=wp_config.ITERATIONS,
        gravity=wp_config.GRAVITY,
        new_root_world=roots,
        new_point1_world=point1s,
        seg_ke=1.0e9,
        root_bend_ke=wp_config.ROOT_BENDING_KE,
        bend_ke=wp_config.BENDING_KE,
        damping=0.08,
        bending_enabled=False,
        body_collision_fn=collider,
        post_collision_iterations=wp_config.POST_COLLISION_ITERATIONS,
    )
    elapsed = time.perf_counter() - start
    assert np.isfinite(output).all()
    return elapsed, output


def crossing_count(collider, output):
    device_positions = wp.array(
        np.ascontiguousarray(output, dtype=np.float32),
        dtype=wp.vec3,
        device="cuda:0",
    )
    crossings = wp.zeros(1, dtype=wp.int32, device="cuda:0")
    wp.launch(
        count_crossings,
        dim=n_strands * (pps - 1),
        inputs=[collider.mesh.id, device_positions, pps, crossings],
        device="cuda:0",
    )
    wp.synchronize()
    return int(crossings.numpy()[0])


taichi_class = _sim_taichi.get_solver_class("CUDA")
old_solver = taichi_class(
    n_total=n_total,
    n_strands=n_strands,
    pps=pps,
    init_pos=positions,
    particle_mass=0.1,
    bending_enabled=False,
)
new_solver = WarpXPBDSolver(
    n_total=n_total,
    n_strands=n_strands,
    pps=pps,
    init_pos=positions,
    particle_mass=0.1,
    bending_enabled=False,
)

# Warm both kernel sets before measuring steady state.
run(old_solver, make_collider())
run(new_solver, make_collider())
old_seconds, old_output = run(old_solver, make_collider())
new_collider = make_collider()
new_seconds, new_output = run(new_solver, new_collider)

delta = np.linalg.norm(new_output - old_output, axis=1)
print(
    "TOKOYA_GPU_SHARED_BENCHMARK",
    {
        "points": n_total,
        "strands": n_strands,
        "old_seconds": old_seconds,
        "new_seconds": new_seconds,
        "speedup": old_seconds / new_seconds,
        "mean_position_delta_m": float(delta.mean()),
        "max_position_delta_m": float(delta.max()),
        "old_segment_crossings": crossing_count(new_collider, old_output),
        "new_segment_crossings": crossing_count(new_collider, new_output),
    },
)
