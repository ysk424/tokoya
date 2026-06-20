import time

import bpy
import numpy as np
import warp as wp


@wp.kernel
def nearest_kernel(
    mesh: wp.uint64,
    positions: wp.array(dtype=wp.vec3),
    distances: wp.array(dtype=wp.float32),
):
    i = wp.tid()
    point = positions[i]
    query = wp.mesh_query_point_no_sign(mesh, point, 0.003)
    if query.result:
        closest = wp.mesh_eval_position(
            mesh, query.face, query.u, query.v
        )
        distances[i] = wp.length(point - closest)
    else:
        distances[i] = -1.0


def build_body_arrays(body_name):
    body = bpy.data.objects[body_name]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        vertex_count = len(mesh.vertices)
        triangle_count = len(mesh.loop_triangles)
        vertices = np.empty(vertex_count * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", vertices)
        vertices = vertices.reshape(-1, 3)
        matrix = np.array(evaluated.matrix_world, dtype=np.float32)
        homogeneous = np.column_stack(
            (vertices, np.ones(vertex_count, dtype=np.float32))
        )
        vertices = (homogeneous @ matrix.T)[:, :3].astype(
            np.float32, copy=False
        )
        indices = np.empty(triangle_count * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", indices)
        return vertices, indices
    finally:
        evaluated.to_mesh_clear()


def run(positions, body_name="CC_Base_Body", repeats=20):
    device = "cuda:0"
    vertices, indices = build_body_arrays(body_name)
    start = time.perf_counter()
    warp_vertices = wp.array(vertices, dtype=wp.vec3, device=device)
    warp_indices = wp.array(indices, dtype=wp.int32, device=device)
    mesh = wp.Mesh(points=warp_vertices, indices=warp_indices)
    wp.synchronize()
    build_seconds = time.perf_counter() - start

    warp_positions = wp.array(
        np.ascontiguousarray(positions, dtype=np.float32),
        dtype=wp.vec3,
        device=device,
    )
    distances = wp.empty(
        len(positions), dtype=wp.float32, device=device
    )
    wp.launch(
        nearest_kernel,
        dim=len(positions),
        inputs=[mesh.id, warp_positions, distances],
        device=device,
    )
    wp.synchronize()

    start = time.perf_counter()
    for _ in range(repeats):
        wp.launch(
            nearest_kernel,
            dim=len(positions),
            inputs=[mesh.id, warp_positions, distances],
            device=device,
        )
    wp.synchronize()
    query_seconds = (time.perf_counter() - start) / repeats
    output = distances.numpy()
    hits = output >= 0.0
    return {
        "vertices": len(vertices),
        "triangles": len(indices) // 3,
        "build_seconds": build_seconds,
        "query_seconds": query_seconds,
        "hits": int(hits.sum()),
        "minimum": float(output[hits].min()) if hits.any() else None,
    }
