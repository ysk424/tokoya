"""Plant straight hair from a grayscale texture painted on a head mesh."""
from __future__ import annotations

from array import array
import bisect
import math
import random

import bpy
from mathutils import Matrix, Vector


POINTS_PER_STRAND = 9
MIN_POINTS_PER_STRAND = 9
MAX_POINTS_PER_STRAND = 13
NATURAL_SPACING_RATIO = 1.22
COMMON_ROOT_SEGMENTS = 2
MIN_DARKNESS = 1.0 / 255.0

# Z-slice planting
Z_AREA_BINS = 512
MIN_ROW_STEP_RATIO = 0.05
MAX_Z_ROWS = 4096


def points_per_strand_for_length(max_length_cm: float) -> int:
    """Choose one uniform strand point count from the requested max length."""
    return max(
        MIN_POINTS_PER_STRAND,
        min(
            MAX_POINTS_PER_STRAND,
            MIN_POINTS_PER_STRAND + math.floor((max_length_cm - 20.0) / 10.0),
        ),
    )


def natural_distances(length_m: float, max_length_m: float, pps: int) -> list[float]:
    """Return monotonic distances from root for one strand.

    The first two segments use the max-length root zone when the strand is
    long enough. Shorter gray-mask or Mesh Shrink strands keep that common
    root zone, then distribute their remaining tail evenly.
    """
    if pps < 2:
        return [0.0]
    length_m = max(0.0, float(length_m))
    max_length_m = max(length_m, float(max_length_m), 1.0e-9)
    segments = [NATURAL_SPACING_RATIO ** i for i in range(pps - 1)]
    total = sum(segments)
    max_distances = [0.0]
    acc = 0.0
    for segment in segments:
        acc += segment
        max_distances.append(max_length_m * acc / total)

    root_index = min(COMMON_ROOT_SEGMENTS, pps - 1)
    root_zone = max_distances[root_index]
    if length_m >= max_length_m - 1.0e-9:
        return max_distances
    if length_m <= root_zone + 1.0e-9:
        scale = length_m / root_zone if root_zone > 1.0e-9 else 0.0
        return [min(length_m, distance * scale) for distance in max_distances]

    distances = [0.0] * pps
    for index in range(root_index + 1):
        distances[index] = max_distances[index]

    remaining_points = pps - root_index - 1
    if remaining_points > 0:
        step = (length_m - root_zone) / remaining_points
        for offset in range(1, remaining_points + 1):
            distances[root_index + offset] = root_zone + step * offset
    return distances


def create_head_mask(
    surface_obj: bpy.types.Object,
    image_size: int = 2048,
    offset_m: float = 0.001,
) -> bpy.types.Object:
    """Create a scale-1 paint shell from the surface's Head material region."""
    if surface_obj is None or surface_obj.type != "MESH":
        raise RuntimeError("Curves surface must be a mesh")
    if bpy.data.objects.get("Tokoya_HairMask") is not None:
        raise RuntimeError("Tokoya_HairMask already exists")

    material_index = next(
        (
            index
            for index, slot in enumerate(surface_obj.material_slots)
            if slot.material is not None
            and "skin_head" in slot.material.name.lower()
        ),
        None,
    )
    if material_index is None:
        raise RuntimeError("Could not find a material containing 'Skin_Head'")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_obj = surface_obj.evaluated_get(depsgraph)
    evaluated_mesh = evaluated_obj.to_mesh(
        preserve_all_data_layers=True, depsgraph=depsgraph
    )
    try:
        uv_source = (
            evaluated_mesh.uv_layers.get("Channel0")
            or evaluated_mesh.uv_layers.active
        )
        if uv_source is None:
            raise RuntimeError("Head surface has no UV map")

        polygons = [
            polygon
            for polygon in evaluated_mesh.polygons
            if polygon.material_index == material_index
        ]
        if not polygons:
            raise RuntimeError("Head material contains no polygons")

        used_vertices = sorted(
            {vertex_index for polygon in polygons for vertex_index in polygon.vertices}
        )
        remap = {
            source_index: target_index
            for target_index, source_index in enumerate(used_vertices)
        }
        world = evaluated_obj.matrix_world
        normal_matrix = world.to_3x3().inverted().transposed()
        vertices = []
        for source_index in used_vertices:
            source_vertex = evaluated_mesh.vertices[source_index]
            position = world @ source_vertex.co
            normal = (normal_matrix @ source_vertex.normal).normalized()
            vertices.append(tuple(position + normal * offset_m))
        faces = [
            [remap[vertex_index] for vertex_index in polygon.vertices]
            for polygon in polygons
        ]

        mesh = bpy.data.meshes.new("Tokoya_HairMask_Mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        uv_target = mesh.uv_layers.new(name=uv_source.name)
        uv_values = []
        for polygon in polygons:
            for loop_index in polygon.loop_indices:
                uv = uv_source.data[loop_index].uv
                uv_values.extend((uv.x, uv.y))
        uv_target.data.foreach_set("uv", uv_values)
    finally:
        evaluated_obj.to_mesh_clear()

    mask_obj = bpy.data.objects.new("Tokoya_HairMask", mesh)
    bpy.context.collection.objects.link(mask_obj)
    mask_obj.matrix_world = Matrix.Identity(4)
    mask_obj["tokoya_mask_semantics"] = "WHITE=0 cm, BLACK=max length"
    mask_obj["tokoya_surface_offset_m"] = offset_m

    image = bpy.data.images.new(
        "Tokoya_HairMask_White",
        width=image_size,
        height=image_size,
        alpha=False,
        float_buffer=False,
    )
    image.generated_type = "BLANK"
    image.generated_color = (1.0, 1.0, 1.0, 1.0)
    image.colorspace_settings.name = "Non-Color"

    material = bpy.data.materials.new("Tokoya_HairMask_Material")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Linear"
    texture.select = True
    nodes.active = texture
    shader.inputs["Roughness"].default_value = 0.8
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    mesh.materials.append(material)

    return mask_obj


def _find_single_curves() -> bpy.types.Object:
    objects = [obj for obj in bpy.data.objects if obj.type == "CURVES"]
    if len(objects) != 1:
        raise RuntimeError(f"Expected exactly 1 Curves object, found {len(objects)}")
    return objects[0]


def remove_all_hair(curves_obj: bpy.types.Object) -> int:
    """Clear strands by replacing only the Curves data block."""
    old = curves_obj.data
    removed = len(old.curves)
    new = bpy.data.hair_curves.new(old.name)
    new.surface = old.surface
    new.surface_uv_map = old.surface_uv_map
    for material in old.materials:
        new.materials.append(material)
    curves_obj.data = new
    if old.users == 0:
        bpy.data.hair_curves.remove(old)
    return removed


def _find_mask_image(mask_obj: bpy.types.Object) -> bpy.types.Image:
    for slot in mask_obj.material_slots:
        material = slot.material
        if material is None or not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image is not None:
                return node.image
    raise RuntimeError("Mask mesh has no Image Texture node")


def _apply_mesh_scale(mask_obj: bpy.types.Object) -> None:
    """Apply object scale to mesh data without changing its world appearance."""
    scale = mask_obj.scale
    if all(abs(value - 1.0) < 1.0e-6 for value in scale):
        return
    if mask_obj.data.users > 1:
        mask_obj.data = mask_obj.data.copy()
    mask_obj.data.transform(Matrix.Diagonal((scale.x, scale.y, scale.z, 1.0)))
    mask_obj.scale = (1.0, 1.0, 1.0)
    mask_obj.data.update()


def _prepare_empty_curves(curves_obj: bpy.types.Object) -> None:
    if len(curves_obj.data.curves) or len(curves_obj.data.points):
        raise RuntimeError("Curves object must be empty before Mask Plant")

    # Hair objects created on a CC character inherit the armature's 0.01 scale.
    # Generated coordinates are metres in world space, so use an identity object.
    curves_obj.parent = None
    curves_obj.matrix_world = Matrix.Identity(4)
    curves_obj.scale = (1.0, 1.0, 1.0)


def _read_pixels(image: bpy.types.Image) -> tuple[array, int, int]:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise RuntimeError("Mask image has no pixel data")
    pixels = array("f", [0.0]) * (width * height * 4)
    image.pixels.foreach_get(pixels)
    return pixels, width, height


def _darkness(pixels: array, width: int, height: int, uv: Vector) -> float:
    u = min(1.0, max(0.0, uv.x))
    v = min(1.0, max(0.0, uv.y))
    x = min(width - 1, max(0, round(u * (width - 1))))
    y = min(height - 1, max(0, round(v * (height - 1))))
    index = (y * width + x) * 4
    luminance = (pixels[index] + pixels[index + 1] + pixels[index + 2]) / 3.0
    return min(1.0, max(0.0, 1.0 - luminance))


def _painted_triangles(
    mesh: bpy.types.Mesh,
    world_verts: list[Vector],
    uv_layer,
    pixels: array,
    width: int,
    height: int,
) -> list[tuple]:
    """Return the loop triangles that carry at least some mask darkness.

    Each record is ``(vertex_indices, world_vertices, uvs, area)``. Vertex
    indices are kept so contour crossings can be identified by mesh edge.
    """
    mesh.calc_loop_triangles()
    records = []
    for triangle in mesh.loop_triangles:
        loop_indices = triangle.loops
        indices = tuple(triangle.vertices)
        vertices = [world_verts[index] for index in indices]
        uvs = [Vector(uv_layer.data[index].uv) for index in loop_indices]
        area = ((vertices[1] - vertices[0]).cross(vertices[2] - vertices[0])).length * 0.5
        if area <= 1.0e-14:
            continue
        centroid_uv = (uvs[0] + uvs[1] + uvs[2]) / 3.0
        max_darkness = max(
            _darkness(pixels, width, height, uvs[0]),
            _darkness(pixels, width, height, uvs[1]),
            _darkness(pixels, width, height, uvs[2]),
            _darkness(pixels, width, height, centroid_uv),
        )
        if max_darkness < MIN_DARKNESS:
            continue
        records.append((indices, vertices, uvs, area))
    return records


def _write_curves(
    curves_obj: bpy.types.Object,
    roots: list[Vector],
    normals: list[Vector],
    lengths: list[float],
    root_uvs: list[Vector],
    max_length_m: float,
    points_per_strand: int,
    int_attributes: dict[str, list[int]] | None = None,
) -> None:
    """Fill an empty Curves object with straight strands along the normals."""
    curves = curves_obj.data
    curves.add_curves([points_per_strand] * len(roots))
    position = curves.attributes["position"]
    if "surface_uv_coordinate" not in curves.attributes:
        curves.attributes.new(
            name="surface_uv_coordinate", type="FLOAT2", domain="CURVE"
        )
    surface_uv = curves.attributes["surface_uv_coordinate"]

    for curve_index, (root, normal, length, uv) in enumerate(
        zip(roots, normals, lengths, root_uvs)
    ):
        first = curve_index * points_per_strand
        distances = natural_distances(length, max_length_m, points_per_strand)
        for point_index, distance in enumerate(distances):
            position.data[first + point_index].vector = root + normal * distance
        surface_uv.data[curve_index].vector = uv

    for name, values in (int_attributes or {}).items():
        if name not in curves.attributes:
            curves.attributes.new(name=name, type="INT", domain="CURVE")
        curves.attributes[name].data.foreach_set("value", values)

    curves.update_tag()
    bpy.context.view_layer.update()


def plant_mask_hair(
    mask_obj: bpy.types.Object,
    strand_count: int,
    max_length_cm: float,
    seed: int = 20260620,
    curves_obj: bpy.types.Object | None = None,
) -> dict:
    """Fill the non-white mask region with fixed-count, variable-length hair.

    White produces zero length, black produces *max_length_cm*, and gray is
    linearly interpolated. Root positions are uniform by painted surface area;
    grayscale controls length only.
    """
    if mask_obj.type != "MESH":
        raise RuntimeError("Ref Object must be the painted MESH")
    if strand_count < 1:
        raise ValueError("Strand count must be at least 1")
    if max_length_cm <= 0.0:
        raise ValueError("Maximum length must be positive")

    curves_obj = curves_obj if curves_obj is not None else _find_single_curves()
    if curves_obj.type != "CURVES":
        raise RuntimeError("Hair object must be Curves")
    _prepare_empty_curves(curves_obj)
    _apply_mesh_scale(mask_obj)

    mesh = mask_obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("Mask mesh has no active UV map")
    image = _find_mask_image(mask_obj)
    pixels, width, height = _read_pixels(image)

    world = mask_obj.matrix_world
    world_verts = [world @ vertex.co for vertex in mesh.vertices]
    records = _painted_triangles(mesh, world_verts, uv_layer, pixels, width, height)

    triangles = []
    cumulative_areas = []
    total_area = 0.0
    for _indices, vertices, uvs, area in records:
        total_area += area
        triangles.append((vertices, uvs))
        cumulative_areas.append(total_area)

    if not triangles:
        raise RuntimeError("No painted (non-white) mask region found")

    rng = random.Random(seed)
    roots = []
    normals = []
    lengths = []
    root_uvs = []
    max_attempts = strand_count * 100
    attempts = 0
    max_length_m = max_length_cm / 100.0

    while len(roots) < strand_count and attempts < max_attempts:
        attempts += 1
        triangle_index = bisect.bisect_left(
            cumulative_areas, rng.random() * total_area
        )
        vertices, uvs = triangles[min(triangle_index, len(triangles) - 1)]

        a = rng.random()
        b = rng.random()
        if a + b > 1.0:
            a = 1.0 - a
            b = 1.0 - b
        c = 1.0 - a - b

        uv = uvs[0] * c + uvs[1] * a + uvs[2] * b
        darkness = _darkness(pixels, width, height, uv)
        if darkness < MIN_DARKNESS:
            continue

        root = vertices[0] * c + vertices[1] * a + vertices[2] * b
        normal = (vertices[1] - vertices[0]).cross(vertices[2] - vertices[0])
        if normal.length_squared == 0.0:
            continue

        roots.append(root)
        normals.append(normal.normalized())
        lengths.append(max_length_m * darkness)
        root_uvs.append(uv)

    if len(roots) != strand_count:
        raise RuntimeError(
            f"Could only place {len(roots)} of {strand_count} strands"
        )

    points_per_strand = points_per_strand_for_length(max_length_cm)
    _write_curves(
        curves_obj,
        roots,
        normals,
        lengths,
        root_uvs,
        max_length_m,
        points_per_strand,
    )

    lengths_cm = [length * 100.0 for length in lengths]
    return {
        "n_added": strand_count,
        "total_points": strand_count * points_per_strand,
        "points_per_strand": points_per_strand,
        "max_length_cm": max(lengths_cm),
        "mean_length_cm": sum(lengths_cm) / len(lengths_cm),
        "mask_image": image.name,
    }


# ---------------------------------------------------------------------------
# Z-slice planting
#
# Roots are placed on constant-world-Z contour lines of the mask surface, so
# every strand of one row shares the same Z. Row Z levels are not uniform: the
# painted area between two rows is kept equal to (contour length * spacing), so
# the surface distance between rows matches the distance along a row. That
# keeps the lattice square in both directions while the rows stay flat, which
# is what the later XPBD pass expects.
# ---------------------------------------------------------------------------


def _area_below_plane(z_sorted: tuple[float, float, float], area: float, z: float) -> float:
    """Area of one triangle that lies below the horizontal plane at *z*."""
    z0, z1, z2 = z_sorted
    if z <= z0:
        return 0.0
    if z >= z2:
        return area
    if z <= z1:
        return area * (z - z0) ** 2 / ((z1 - z0) * (z2 - z0))
    return area * (1.0 - (z2 - z) ** 2 / ((z2 - z1) * (z2 - z0)))


def _build_z_profile(records: list[tuple]) -> tuple[float, float, list[float]]:
    """Return ``(z_min, bin_step, cumulative_area)`` over the painted region."""
    z_min = min(min(vertex.z for vertex in vertices) for _i, vertices, _uv, _a in records)
    z_max = max(max(vertex.z for vertex in vertices) for _i, vertices, _uv, _a in records)
    span = z_max - z_min
    if span <= 1.0e-9:
        raise RuntimeError("Painted mask region is flat in Z")

    step = span / Z_AREA_BINS
    bin_area = [0.0] * Z_AREA_BINS
    for _indices, vertices, _uvs, area in records:
        z_sorted = tuple(sorted(vertex.z for vertex in vertices))
        low = min(Z_AREA_BINS - 1, max(0, int((z_sorted[0] - z_min) / step)))
        high = min(Z_AREA_BINS - 1, max(0, int((z_sorted[2] - z_min) / step)))
        if low == high:
            bin_area[low] += area
            continue
        previous = 0.0
        for index in range(low, high + 1):
            if index == high:
                current = area
            else:
                current = _area_below_plane(z_sorted, area, z_min + (index + 1) * step)
            bin_area[index] += current - previous
            previous = current

    cumulative = [0.0] * (Z_AREA_BINS + 1)
    total = 0.0
    for index, value in enumerate(bin_area):
        total += value
        cumulative[index + 1] = total
    return z_min, step, cumulative


def _area_below_z(z_min: float, step: float, cumulative: list[float], z: float) -> float:
    bins = len(cumulative) - 1
    if z <= z_min:
        return 0.0
    if z >= z_min + step * bins:
        return cumulative[-1]
    position = (z - z_min) / step
    index = int(position)
    fraction = position - index
    return cumulative[index] + (cumulative[index + 1] - cumulative[index]) * fraction


def _z_for_area(z_min: float, step: float, cumulative: list[float], target: float) -> float:
    bins = len(cumulative) - 1
    if target <= 0.0:
        return z_min
    if target >= cumulative[-1]:
        return z_min + step * bins
    index = max(1, bisect.bisect_left(cumulative, target))
    low = cumulative[index - 1]
    high = cumulative[index]
    fraction = 0.0 if high <= low else (target - low) / (high - low)
    return z_min + step * (index - 1 + fraction)


def _build_z_buckets(
    records: list[tuple], z_min: float, step: float
) -> list[list[int]]:
    """Bucket triangle indices by the Z bins they span, for fast slicing."""
    buckets = [[] for _ in range(Z_AREA_BINS)]
    for record_index, (_indices, vertices, _uvs, _area) in enumerate(records):
        z_values = [vertex.z for vertex in vertices]
        low = min(Z_AREA_BINS - 1, max(0, int((min(z_values) - z_min) / step)))
        high = min(Z_AREA_BINS - 1, max(0, int((max(z_values) - z_min) / step)))
        for index in range(low, high + 1):
            buckets[index].append(record_index)
    return buckets


def _contour_polylines(
    records: list[tuple],
    buckets: list[list[int]],
    z_min: float,
    step: float,
    z: float,
) -> list[tuple[list[tuple], float]]:
    """Slice the painted mask with the plane at *z* into ordered polylines.

    Every crossing is identified by the mesh edge it sits on, so triangles that
    share an edge produce exactly the same node and the pieces chain without
    any positional tolerance. Each piece is
    ``(start, end, uv_start, uv_end, normal, length)``.
    """
    bucket_index = min(Z_AREA_BINS - 1, max(0, int((z - z_min) / step)))
    node_positions: dict[tuple[int, int], Vector] = {}
    adjacency: dict[tuple[int, int], list[tuple]] = {}

    for record_index in buckets[bucket_index]:
        indices, vertices, uvs, _area = records[record_index]
        z_values = (vertices[0].z, vertices[1].z, vertices[2].z)
        above = (z_values[0] >= z, z_values[1] >= z, z_values[2] >= z)
        if above[0] == above[1] == above[2]:
            continue

        crossings = []
        for i in range(3):
            j = (i + 1) % 3
            if above[i] == above[j]:
                continue
            first, second = (i, j) if indices[i] < indices[j] else (j, i)
            key = (indices[first], indices[second])
            if key not in node_positions:
                denominator = z_values[second] - z_values[first]
                shared = (
                    0.5
                    if abs(denominator) < 1.0e-12
                    else (z - z_values[first]) / denominator
                )
                shared = min(1.0, max(0.0, shared))
                node_positions[key] = vertices[first].lerp(vertices[second], shared)
            denominator = z_values[j] - z_values[i]
            factor = (
                0.5 if abs(denominator) < 1.0e-12 else (z - z_values[i]) / denominator
            )
            factor = min(1.0, max(0.0, factor))
            crossings.append((key, uvs[i].lerp(uvs[j], factor)))

        if len(crossings) != 2 or crossings[0][0] == crossings[1][0]:
            continue
        normal = (vertices[1] - vertices[0]).cross(vertices[2] - vertices[0])
        if normal.length_squared == 0.0:
            continue
        normal = normal.normalized()
        (key_a, uv_a), (key_b, uv_b) = crossings
        adjacency.setdefault(key_a, []).append((key_b, uv_a, uv_b, normal))
        adjacency.setdefault(key_b, []).append((key_a, uv_b, uv_a, normal))

    used: set[tuple] = set()

    def walk(start):
        pieces = []
        length = 0.0
        current = start
        while True:
            following = None
            for other, uv_self, uv_other, normal in adjacency.get(current, ()):
                pair = (current, other) if current < other else (other, current)
                if pair in used:
                    continue
                following = (other, uv_self, uv_other, normal, pair)
                break
            if following is None:
                break
            other, uv_self, uv_other, normal, pair = following
            used.add(pair)
            start_point = node_positions[current]
            end_point = node_positions[other]
            piece_length = (end_point - start_point).length
            if piece_length > 0.0:
                pieces.append(
                    (start_point, end_point, uv_self, uv_other, normal, piece_length)
                )
                length += piece_length
            current = other
        return pieces, length

    polylines = []
    # Open contours must start at a loose end, otherwise the walk would split
    # them in two. Whatever is left after that is a closed loop.
    open_ends = [key for key, links in adjacency.items() if len(links) == 1]
    for start in open_ends + list(adjacency.keys()):
        pieces, length = walk(start)
        if pieces:
            polylines.append((pieces, length))
    return polylines


def _place_along_polyline(
    pieces: list[tuple], length: float, spacing: float, z: float
) -> list[tuple[Vector, Vector, Vector]]:
    """Return ``(position, uv, normal)`` evenly spaced along one contour.

    Positions are snapped to the slicing plane *z*. Interpolating along an edge
    only lands within float precision of that plane, and the whole point of
    this mode is that one row compares bit-equal in Z.
    """
    count = int(round(length / spacing)) if spacing > 0.0 else 0
    if count < 1:
        return []
    closed = (pieces[0][0] - pieces[-1][1]).length_squared < 1.0e-18
    actual = length / count
    offset = 0.0 if closed else actual * 0.5

    placements = []
    piece_index = 0
    travelled = 0.0
    for order in range(count):
        target = offset + actual * order
        while (
            piece_index < len(pieces) - 1
            and travelled + pieces[piece_index][5] < target
        ):
            travelled += pieces[piece_index][5]
            piece_index += 1
        start_point, end_point, uv_start, uv_end, normal, piece_length = pieces[
            piece_index
        ]
        factor = 0.0 if piece_length <= 0.0 else (target - travelled) / piece_length
        factor = min(1.0, max(0.0, factor))
        position = start_point.lerp(end_point, factor)
        position.z = z
        placements.append((position, uv_start.lerp(uv_end, factor), normal))
    return placements


def plant_z_slice_hair(
    mask_obj: bpy.types.Object,
    strand_count: int,
    max_length_cm: float,
    curves_obj: bpy.types.Object | None = None,
) -> dict:
    """Plant mask hair in flat Z rows instead of a random area scatter.

    Root spacing along a row and between rows both follow the painted surface
    area, so *strand_count* is a target rather than an exact result. Grayscale
    still controls length only.
    """
    if mask_obj.type != "MESH":
        raise RuntimeError("Ref Object must be the painted MESH")
    if strand_count < 1:
        raise ValueError("Strand count must be at least 1")
    if max_length_cm <= 0.0:
        raise ValueError("Maximum length must be positive")

    curves_obj = curves_obj if curves_obj is not None else _find_single_curves()
    if curves_obj.type != "CURVES":
        raise RuntimeError("Hair object must be Curves")
    _prepare_empty_curves(curves_obj)
    _apply_mesh_scale(mask_obj)

    mesh = mask_obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("Mask mesh has no active UV map")
    image = _find_mask_image(mask_obj)
    pixels, width, height = _read_pixels(image)

    world = mask_obj.matrix_world
    world_verts = [world @ vertex.co for vertex in mesh.vertices]
    records = _painted_triangles(mesh, world_verts, uv_layer, pixels, width, height)
    if not records:
        raise RuntimeError("No painted (non-white) mask region found")

    total_area = sum(area for _i, _v, _uv, area in records)
    spacing = math.sqrt(total_area / strand_count)
    max_length_m = max_length_cm / 100.0

    z_min, bin_step, cumulative = _build_z_profile(records)
    z_max = z_min + bin_step * Z_AREA_BINS
    buckets = _build_z_buckets(records, z_min, bin_step)

    roots: list[Vector] = []
    normals: list[Vector] = []
    lengths: list[float] = []
    root_uvs: list[Vector] = []
    row_ids: list[int] = []
    strip_ids: list[int] = []
    order_ids: list[int] = []

    minimum_step = spacing * MIN_ROW_STEP_RATIO
    z = z_min + (z_max - z_min) * 1.0e-4
    row = 0
    strip = 0
    iterations = 0

    while z < z_max and iterations < MAX_Z_ROWS:
        iterations += 1
        polylines = _contour_polylines(records, buckets, z_min, bin_step, z)
        row_length = sum(length for _pieces, length in polylines)
        if row_length <= 1.0e-9:
            z += max(minimum_step, bin_step)
            continue

        placed = False
        for pieces, length in polylines:
            order = 0
            for position, uv, normal in _place_along_polyline(
                pieces, length, spacing, z
            ):
                darkness = _darkness(pixels, width, height, uv)
                if darkness < MIN_DARKNESS:
                    continue
                roots.append(position)
                normals.append(normal)
                lengths.append(max_length_m * darkness)
                root_uvs.append(uv)
                row_ids.append(row)
                strip_ids.append(strip)
                order_ids.append(order)
                order += 1
                placed = True
            if order:
                strip += 1
        if placed:
            row += 1

        target = _area_below_z(z_min, bin_step, cumulative, z) + row_length * spacing
        next_z = _z_for_area(z_min, bin_step, cumulative, target)
        z = max(next_z, z + minimum_step)

    if not roots:
        raise RuntimeError("Z-slice planting produced no strands")

    points_per_strand = points_per_strand_for_length(max_length_cm)
    _write_curves(
        curves_obj,
        roots,
        normals,
        lengths,
        root_uvs,
        max_length_m,
        points_per_strand,
        int_attributes={
            "tokoya_z_row": row_ids,
            "tokoya_z_strip": strip_ids,
            "tokoya_z_order": order_ids,
        },
    )

    curves_obj["tokoya_plant_mode"] = "Z_SLICE"
    curves_obj["tokoya_z_rows"] = row
    curves_obj["tokoya_z_spacing_m"] = spacing

    lengths_cm = [length * 100.0 for length in lengths]
    return {
        "n_added": len(roots),
        "requested": strand_count,
        "total_points": len(roots) * points_per_strand,
        "points_per_strand": points_per_strand,
        "rows": row,
        "spacing_mm": spacing * 1000.0,
        "max_length_cm": max(lengths_cm),
        "mean_length_cm": sum(lengths_cm) / len(lengths_cm),
        "mask_image": image.name,
    }
