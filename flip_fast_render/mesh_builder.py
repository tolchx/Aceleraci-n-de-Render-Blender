# SPDX-License-Identifier: GPL-3.0-or-later
"""Fast Blender Mesh geometry builder using foreach_set and reusable buffers."""

import bpy
import numpy as np


_ARANGE_CACHE = np.empty(0, dtype=np.int32)
_THREE_CACHE = np.empty(0, dtype=np.int32)


def _get_poly_buffers(num_tris):
    global _ARANGE_CACHE, _THREE_CACHE
    if _ARANGE_CACHE.size < num_tris:
        _ARANGE_CACHE = np.arange(0, num_tris * 3, 3, dtype=np.int32)
        _THREE_CACHE = np.full(num_tris, 3, dtype=np.int32)
    return _ARANGE_CACHE[:num_tris], _THREE_CACHE[:num_tris]


def set_mesh_smoothness(mesh_data, is_smooth):
    num_polys = len(mesh_data.polygons)
    if num_polys == 0:
        return

    if is_smooth:
        sharp_attr = mesh_data.attributes.get("sharp_face")
        if sharp_attr is not None:
            mesh_data.attributes.remove(sharp_attr)
        return

    mesh_data.polygons.foreach_set("use_smooth", np.zeros(num_polys, dtype=bool))


def swap_mesh_geometry(
    bl_object,
    vertices=(),
    triangles=(),
    mesh_name="Untitled",
    smooth_mesh=False,
    octane_mesh_type="Global",
):
    """Replace object mesh geometry via foreach_set while preserving metadata layers."""
    vg_layer_names = [vg.name for vg in bl_object.vertex_groups]
    active_vertex_layer_index = bl_object.vertex_groups.active_index

    mesh_data = bl_object.data
    uv_layers = mesh_data.uv_layers
    uv_meta = [(uv.name, uv.active, uv.active_render) for uv in uv_layers]

    color_attrs = mesh_data.color_attributes
    ca_meta = [(ca.name, ca.data_type, ca.domain) for ca in color_attrs]

    pos = (
        vertices
        if isinstance(vertices, np.ndarray) and vertices.dtype == np.float32
        else np.asarray(vertices, dtype=np.float32)
    ).ravel()

    idx = (
        triangles
        if isinstance(triangles, np.ndarray) and triangles.dtype == np.int32
        else np.asarray(triangles, dtype=np.int32)
    ).ravel()

    mesh_data.clear_geometry()

    nv = pos.size // 3
    if nv > 0:
        mesh_data.vertices.add(nv)
        mesh_data.vertices.foreach_set("co", pos)

        nt = idx.size // 3
        if nt > 0:
            mesh_data.loops.add(nt * 3)
            mesh_data.loops.foreach_set("vertex_index", idx)

            mesh_data.polygons.add(nt)
            loop_start, loop_total = _get_poly_buffers(nt)
            mesh_data.polygons.foreach_set("loop_start", loop_start)
            mesh_data.polygons.foreach_set("loop_total", loop_total)
            mesh_data.update(calc_edges=True)
            set_mesh_smoothness(mesh_data, smooth_mesh)
        else:
            mesh_data.update()

    if hasattr(bpy.context.scene, "octane") and octane_mesh_type is not None:
        bl_object.octane.object_mesh_type = octane_mesh_type

    for name in vg_layer_names:
        bl_object.vertex_groups.new(name=name)
    if vg_layer_names and active_vertex_layer_index >= 0:
        bl_object.vertex_groups.active_index = active_vertex_layer_index

    for name, is_active, is_active_render in uv_meta:
        uv_layer = mesh_data.uv_layers.new(name=name)
        uv_layer.active = is_active
        uv_layer.active_render = is_active_render

    for name, data_type, domain in ca_meta:
        mesh_data.color_attributes.new(name=name, type=data_type, domain=domain)


def set_point_attribute(mesh_data, name, data_type, values):
    """Write a POINT-domain mesh attribute cleanly from a NumPy array or sequence."""
    if values is None or len(values) == 0:
        return
    existing = mesh_data.attributes.get(name)
    if existing is not None:
        mesh_data.attributes.remove(existing)
    attr = mesh_data.attributes.new(name, data_type, "POINT")
    field = "vector" if data_type == "FLOAT_VECTOR" else "value"
    attr.data.foreach_set(field, values)
