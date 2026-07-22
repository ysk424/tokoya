"""Create a non-destructive Tokoya hand-off for ZOZO Contact Solver.

The groomed Hair Curves become a solver-owned ROD mesh (one edge-only polyline
per strand) and the animated Body becomes a STATIC collider copy.  Tokoya's own
Curves, Body and scene stay untouched, mirroring the Yohsai "Prepare for ZOZO"
hand-off.

Evaluated world-space coordinates are used for both the rod strands and the body
so a Surface Deform or armature deformation is baked into the hand-off exactly as
the user sees it (see the coordinate convention in _mesh_ops.py).
"""
from __future__ import annotations

from dataclasses import dataclass
import re

import bpy
import numpy as np


ZOZO_MCP_PORT = 9633
ZOZO_CONTACT_GAP_M = 0.001
_HANDOFF_COLLECTION_ROLE = "zozo_handoff"
_HANDOFF_ROD_ROLE = "zozo_rod"
_HANDOFF_BODY_ROLE = "zozo_body"


class ZozoHandoffError(RuntimeError):
    """The current Tokoya state cannot safely be handed to ZOZO."""


@dataclass(frozen=True)
class ZozoPreparation:
    collection: bpy.types.Collection
    rod_object: bpy.types.Object
    body_object: bpy.types.Object
    strand_count: int
    point_count: int
    rod_group_name: str
    body_group_name: str
    project_name: str

    def mcp_configuration(self, scene: bpy.types.Scene) -> dict:
        fps = max(1, int(round(float(scene.render.fps) / float(scene.render.fps_base))))
        return {
            "port": ZOZO_MCP_PORT,
            "rod_object": self.rod_object.name,
            "body_object": self.body_object.name,
            "rod_group": self.rod_group_name,
            "body_group": self.body_group_name,
            "scene_parameters": {
                "step_size": 0.005,
                "frame_count": max(1, int(scene.frame_end) - int(scene.frame_start) + 1),
                "frame_rate": fps,
                "gravity": [0.0, 0.0, -9.81],
                "inactive_momentum_frames": 5,
                "project_name": self.project_name,
            },
            # Conservative contact material only.  ZOZO's rod-specific stiffness
            # and bending keys can be added here once confirmed against the
            # running solver; the config is written to disk so it can be edited.
            "rod_properties": {
                "contact_gap": ZOZO_CONTACT_GAP_M,
                "contact_offset": 0.0,
            },
            "body_properties": {
                "contact_gap": ZOZO_CONTACT_GAP_M,
                "contact_offset": 0.0,
            },
            "capture_timeout_seconds": 300.0,
        }


def _world_strand_points(
    context, curves_obj: bpy.types.Object
) -> tuple[np.ndarray, int, int]:
    """Return evaluated world positions plus (strand_count, points_per_strand).

    Uses the evaluated Curves so the Surface Deform / armature offset is baked in,
    matching what the user sees.  All Tokoya strands share the same point count
    (Max Length sets it), so the contiguous point layout is split uniformly.
    """
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = curves_obj.evaluated_get(depsgraph)
    data = evaluated.data
    n_curves = len(data.curves)
    n_points = len(data.points)
    if n_curves <= 0 or n_points <= 0:
        raise ZozoHandoffError("The Hair Curves object has no strands to hand off.")
    if n_points % n_curves:
        raise ZozoHandoffError("All strands must share the same point count for ZOZO.")
    points_per_strand = n_points // n_curves
    if points_per_strand < 2:
        raise ZozoHandoffError("Each strand needs at least two points to become a rod.")

    attribute = data.attributes.get("position")
    if attribute is None:
        raise ZozoHandoffError("The Hair Curves object has no position data.")
    flat = np.zeros(n_points * 3, dtype=np.float64)
    attribute.data.foreach_get("vector", flat)
    local = flat.reshape(n_points, 3)
    matrix = np.asarray(evaluated.matrix_world, dtype=np.float64)
    world = local @ matrix[:3, :3].T + matrix[:3, 3]
    if not np.all(np.isfinite(world)):
        raise ZozoHandoffError("The hair contains a non-finite point position.")
    return world, n_curves, points_per_strand


def _remove_object_and_owned_mesh(obj: bpy.types.Object) -> None:
    mesh = obj.data if obj.type == "MESH" else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _handoff_collection(
    context, source: bpy.types.Object
) -> bpy.types.Collection:
    """Reuse (and clear) this hair's ZOZO collection so re-preparing is idempotent."""
    matches = [
        collection
        for collection in bpy.data.collections
        if collection.get("tokoya_role") == _HANDOFF_COLLECTION_ROLE
        and collection.get("tokoya_source_hair") == source.name
    ]
    handoff = matches[0] if matches else bpy.data.collections.new(f"{source.name}_ZOZO")
    if not matches:
        context.scene.collection.children.link(handoff)
    handoff["tokoya_role"] = _HANDOFF_COLLECTION_ROLE
    handoff["tokoya_source_hair"] = source.name
    for collection in matches:
        for obj in list(collection.objects):
            if (
                obj.get("tokoya_source_hair") == source.name
                and obj.get("tokoya_role") in {_HANDOFF_ROD_ROLE, _HANDOFF_BODY_ROLE}
            ):
                _remove_object_and_owned_mesh(obj)
    return handoff


def _create_rod_object(
    handoff: bpy.types.Collection,
    source: bpy.types.Object,
    world: np.ndarray,
    strand_count: int,
    points_per_strand: int,
) -> bpy.types.Object:
    """Build one edge-only polyline per strand at identity transform (world == local)."""
    indices = np.arange(strand_count * points_per_strand).reshape(
        strand_count, points_per_strand
    )
    edges = np.column_stack([indices[:, :-1].ravel(), indices[:, 1:].ravel()])
    vertices = [tuple(point) for point in world]

    name = f"{source.name}_ZOZO_ROD"
    mesh = bpy.data.meshes.new(name)
    rod = bpy.data.objects.new(name, mesh)
    try:
        handoff.objects.link(rod)
        mesh.from_pydata(vertices, edges.tolist(), [])
        mesh.update()
        if len(mesh.vertices) != len(vertices) or len(mesh.edges) != len(edges):
            raise ZozoHandoffError("The ZOZO rod topology changed while creating the mesh.")
        rod["tokoya_role"] = _HANDOFF_ROD_ROLE
        rod["tokoya_source_hair"] = source.name
        rod["tokoya_zozo_strand_count"] = int(strand_count)
        rod["tokoya_zozo_points_per_strand"] = int(points_per_strand)
        rod["tokoya_zozo_contact_gap_m"] = ZOZO_CONTACT_GAP_M
        return rod
    except Exception:
        _remove_object_and_owned_mesh(rod)
        raise


def _create_body_object(
    handoff: bpy.types.Collection,
    source: bpy.types.Object,
    body: bpy.types.Object,
) -> bpy.types.Object:
    """Duplicate the Body with its modifiers so ZOZO can capture its deformation."""
    duplicate = body.copy()
    duplicate.data = body.data.copy()
    duplicate.name = f"{source.name}_ZOZO_BODY"
    duplicate.data.name = f"{duplicate.name}_MESH"
    # Object copies inherit custom properties.  A ZOZO solver UUID must stay
    # unique or this collider could steal the source Body's group.
    if "_solver_uuid" in duplicate:
        del duplicate["_solver_uuid"]
    handoff.objects.link(duplicate)
    duplicate["tokoya_role"] = _HANDOFF_BODY_ROLE
    duplicate["tokoya_source_hair"] = source.name
    duplicate["tokoya_source_body"] = body.name
    duplicate.display_type = "WIRE"
    duplicate.show_in_front = True
    duplicate.hide_render = True
    return duplicate


def _project_name(hair_name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", hair_name).strip("_")
    return f"tokoya_{value or 'hair'}"


def prepare_for_zozo(
    context,
    curves_obj: bpy.types.Object | None,
    body: bpy.types.Object | None,
) -> ZozoPreparation:
    """Create solver-owned rod/body copies and leave Tokoya untouched."""
    if curves_obj is None or curves_obj.type != "CURVES":
        raise ZozoHandoffError("Pick one Hair Curves object before Prepare for ZOZO.")
    if body is None or body.type != "MESH":
        raise ZozoHandoffError("Select a mesh Body before Prepare for ZOZO.")

    context.view_layer.update()
    world, strand_count, points_per_strand = _world_strand_points(context, curves_obj)

    handoff = _handoff_collection(context, curves_obj)
    rod = _create_rod_object(handoff, curves_obj, world, strand_count, points_per_strand)
    try:
        body_copy = _create_body_object(handoff, curves_obj, body)
    except Exception:
        _remove_object_and_owned_mesh(rod)
        raise

    for selected in context.selected_objects:
        selected.select_set(False)
    rod.select_set(True)
    context.view_layer.objects.active = rod
    context.view_layer.update()

    rod_group_name = f"Tokoya {curves_obj.name} Rod"
    body_group_name = f"Tokoya {curves_obj.name} Body"
    rod["tokoya_zozo_group"] = rod_group_name
    body_copy["tokoya_zozo_group"] = body_group_name
    return ZozoPreparation(
        collection=handoff,
        rod_object=rod,
        body_object=body_copy,
        strand_count=strand_count,
        point_count=strand_count * points_per_strand,
        rod_group_name=rod_group_name,
        body_group_name=body_group_name,
        project_name=_project_name(curves_obj.name),
    )
