# SPDX-License-Identifier: GPL-3.0-or-later
"""Standalone FLIP Fluids cache loader when flip_fluids_addon is not enabled."""

import math
import os
import time
import bpy
import mathutils
import numpy as np

from . import fast_io
from . import mesh_builder


IS_RENDERING = False
_LOADED_FRAME_CACHE = {}
_DOMAIN_ATTR_CACHE = {}
LAST_STATS = {
    "frame": -1,
    "load_ms": 0.0,
    "surface_verts": 0,
    "surface_tris": 0,
    "mode": "Idle",
}


def _get_sys_flip_dict(id_data):
    if id_data is None or not hasattr(id_data, "bl_system_properties_get"):
        return None
    sp = id_data.bl_system_properties_get()
    if sp is None:
        return None
    ff = sp.get("flip_fluid")
    return ff if ff is not None else None


def find_domain_object(scene):
    for obj in scene.objects:
        ff = _get_sys_flip_dict(obj)
        if ff is not None and ff.get("is_active", 0) and ff.get("object_type", 0) == 1:
            return obj
    # Fallback by common name if object_type enum was default/unset
    for obj in scene.objects:
        ff = _get_sys_flip_dict(obj)
        if ff is not None and "domain" in ff:
            dom = ff.get("domain")
            if dom and "cache" in dom:
                return obj
    return None


def _resolve_cache_object(scene, mc_dict, name_prefix):
    if mc_dict is not None:
        co = mc_dict.get("cache_object")
        if isinstance(co, bpy.types.Object) and co.name in scene.collection.all_objects:
            return co
        if isinstance(co, str):
            obj = scene.collection.all_objects.get(co)
            if obj is not None:
                return obj
    for obj in scene.collection.all_objects:
        if obj.type == "MESH" and obj.name.startswith(name_prefix):
            return obj
    return None


def _get_bakefiles_dir(dom_dict):
    cache_dict = dom_dict.get("cache", {})
    raw_dir = cache_dict.get("cache_directory", "")
    if not raw_dir:
        return None
    abspath = os.path.normpath(bpy.path.abspath(raw_dir))
    return os.path.join(abspath, "bakefiles")


def _get_playback_offset(scene):
    ff_scene = _get_sys_flip_dict(scene)
    if ff_scene is not None:
        helper = ff_scene.get("helper")
        if helper is not None:
            return int(helper.get("playback_frame_offset", 0))
    return 0


def get_current_simulation_frame(scene, dom_dict):
    r = dom_dict.get("render", {})
    mode = r.get("simulation_playback_mode", 0)
    if mode == 1:
        frame = math.floor(float(r.get("override_frame", scene.frame_current)))
    elif mode == 2:
        frame = int(r.get("hold_frame_number", scene.frame_current))
    else:
        frame = int(scene.frame_current)
    return frame - _get_playback_offset(scene)


def _domain_world_aabb(domain_object):
    mw = np.array(domain_object.matrix_world, dtype=np.float64)
    nv = len(domain_object.data.vertices)
    if nv == 0:
        t = domain_object.matrix_world.translation
        return float(t.x), float(t.y), float(t.z), 0.0, 0.0, 0.0
    co = np.empty(nv * 3, dtype=np.float32)
    domain_object.data.vertices.foreach_get("co", co)
    pts = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    mn = pts.min(axis=0)
    mx = pts.max(axis=0)
    return (
        float(mn[0]),
        float(mn[1]),
        float(mn[2]),
        float(mx[0] - mn[0]),
        float(mx[1] - mn[1]),
        float(mx[2] - mn[2]),
    )


def _compute_viewport_grid_dimensions(domain_object, resolution):
    if resolution <= 0:
        return 1, 1, 1, 1.0
    xmin, ymin, zmin, xdim, ydim, zdim = _domain_world_aabb(domain_object)
    max_dim = max(xdim, ydim, zdim)
    if max_dim <= 0.0:
        return 1, 1, 1, 1.0
    dx = max_dim / float(resolution)
    isize = math.ceil(round(xdim / dx, 5))
    jsize = math.ceil(round(ydim / dx, 5))
    ksize = math.ceil(round(zdim / dx, 5))
    return isize, jsize, ksize, dx


def _apply_transforms(cache_object, domain_object, bounds, nv):
    xmin, ymin, zmin, _, _, _ = _domain_world_aabb(domain_object)
    resolution = max(int(bounds["isize"]), int(bounds["jsize"]), int(bounds["ksize"]))
    isize, jsize, ksize, dx = _compute_viewport_grid_dimensions(domain_object, resolution)

    scalex = (isize * dx) / float(bounds["width"])
    scaley = (jsize * dx) / float(bounds["height"])
    scalez = (ksize * dx) / float(bounds["depth"])
    scale = min(scalex, scaley, scalez)

    cache_object.matrix_world = mathutils.Matrix.Identity(4)
    cache_object.matrix_parent_inverse = domain_object.matrix_world.inverted()
    if nv > 0:
        cache_object.scale = (scale, scale, scale)
    cache_object.location = mathutils.Vector((xmin, ymin, zmin))


def _is_mesh_smooth(mesh_data, default=True):
    if len(mesh_data.polygons) == 0:
        return default
    return bool(mesh_data.polygons[0].use_smooth)


def _update_domain_metadata_attrs(domain_object, bakefiles_dir, frameno):
    meta_path = os.path.join(bakefiles_dir, f"metadata{frameno:06d}.json")
    meta = fast_io.read_json_file(meta_path) or {}
    time_scale = float(meta.get("time_scale", 1.0))
    world_scale = float(meta.get("world_scale", 1.0))

    mesh = domain_object.data
    nv = len(mesh.vertices)
    key = (domain_object.name, nv)
    has_attrs = (
        mesh.attributes.get("flip_time_scale") is not None
        and mesh.attributes.get("flip_world_scale") is not None
    )
    if _DOMAIN_ATTR_CACHE.get(key) == (time_scale, world_scale) and has_attrs:
        return

    if nv > 0:
        mesh_builder.set_point_attribute(
            mesh, "flip_time_scale", "FLOAT", np.full(nv, time_scale, dtype=np.float32)
        )
        mesh_builder.set_point_attribute(
            mesh, "flip_world_scale", "FLOAT", np.full(nv, world_scale, dtype=np.float32)
        )
    _DOMAIN_ATTR_CACHE[key] = (time_scale, world_scale)


def _load_surface(scene, domain_object, dom_dict, bakefiles_dir, frameno, force_load):
    surf_props = dom_dict.get("surface", {})
    if not surf_props.get("enable_surface_mesh_generation", 1):
        return

    mc_dict = dom_dict.get("mesh_cache", {}).get("surface")
    cache_object = _resolve_cache_object(scene, mc_dict, "fluid_surface")
    if cache_object is None or cache_object.mode == "EDIT":
        return

    r = dom_dict.get("render", {})
    mode = r.get("render_display", 0) if IS_RENDERING else r.get("viewport_display", 1)
    if mode == 2:
        prefix = "none"
    elif mode == 1:
        prefix = "preview"
    else:
        prefix = ""

    cache_key = ("surface", cache_object.name)
    state = (frameno, prefix, IS_RENDERING)
    if not force_load and _LOADED_FRAME_CACHE.get(cache_key) == state:
        return

    bounds_path = os.path.join(bakefiles_dir, f"bounds{frameno:06d}.bbox")
    bounds = fast_io.read_json_file(bounds_path)
    if bounds is None:
        bounds = {"x": 0.0, "y": 0.0, "z": 0.0, "width": 1.0, "height": 1.0, "depth": 1.0, "isize": 0, "jsize": 0, "ksize": 0}

    mesh_path = os.path.join(bakefiles_dir, f"{prefix}{frameno:06d}.bobj")
    if prefix == "none" or not os.path.isfile(mesh_path):
        pos, idx = fast_io._EMPTY_F32, fast_io._EMPTY_I32
    else:
        pos, idx = fast_io.read_bobj(mesh_path)

    nv = pos.size // 3
    if nv > 0:
        pos.reshape(-1, 3)[:] -= np.array([bounds["x"], bounds["y"], bounds["z"]], dtype=np.float32)

    is_smooth = _is_mesh_smooth(cache_object.data, True)
    octane_type = cache_object.octane.object_mesh_type if hasattr(scene, "octane") else None

    mesh_builder.swap_mesh_geometry(
        cache_object,
        pos,
        idx,
        mesh_name=cache_object.name,
        smooth_mesh=is_smooth,
        octane_mesh_type=octane_type,
    )
    _apply_transforms(cache_object, domain_object, bounds, nv)

    if mode == 0:
        if surf_props.get("enable_velocity_vector_attribute", 0):
            vpath = os.path.join(bakefiles_dir, f"velocity{frameno:06d}.bobj")
            vdata, _ = fast_io.read_bobj(vpath)
            mesh_builder.set_point_attribute(cache_object.data, "flip_velocity", "FLOAT_VECTOR", vdata)
        if surf_props.get("enable_speed_attribute", 0):
            spath = os.path.join(bakefiles_dir, f"speed{frameno:06d}.data")
            mesh_builder.set_point_attribute(cache_object.data, "flip_speed", "FLOAT", fast_io.read_floats(spath))
        if surf_props.get("enable_vorticity_vector_attribute", 0):
            vpath = os.path.join(bakefiles_dir, f"vorticity{frameno:06d}.bobj")
            vdata, _ = fast_io.read_bobj(vpath)
            mesh_builder.set_point_attribute(cache_object.data, "flip_vorticity", "FLOAT_VECTOR", vdata)
        if surf_props.get("enable_age_attribute", 0):
            apath = os.path.join(bakefiles_dir, f"age{frameno:06d}.data")
            mesh_builder.set_point_attribute(cache_object.data, "flip_age", "FLOAT", fast_io.read_floats(apath))
        if surf_props.get("enable_color_attribute", 0):
            cpath = os.path.join(bakefiles_dir, f"color{frameno:06d}.bobj")
            cdata, _ = fast_io.read_bobj(cpath)
            mesh_builder.set_point_attribute(cache_object.data, "flip_color", "FLOAT_VECTOR", cdata)
        if surf_props.get("enable_source_id_attribute", 0):
            ipath = os.path.join(bakefiles_dir, f"sourceid{frameno:06d}.data")
            mesh_builder.set_point_attribute(cache_object.data, "flip_source_id", "INT", fast_io.read_ints(ipath))
        if surf_props.get("enable_viscosity_attribute", 0):
            vpath = os.path.join(bakefiles_dir, f"viscosity{frameno:06d}.data")
            mesh_builder.set_point_attribute(cache_object.data, "flip_viscosity", "FLOAT", fast_io.read_floats(vpath))
        if surf_props.get("enable_whitewater_proximity_attribute", 0):
            wpath = os.path.join(bakefiles_dir, f"whitewaterproximity{frameno:06d}.bobj")
            wdata, _ = fast_io.read_bobj(wpath)
            if wdata.size > 0:
                mesh_builder.set_point_attribute(cache_object.data, "flip_foam_proximity", "FLOAT", wdata[0::3])
                mesh_builder.set_point_attribute(cache_object.data, "flip_bubble_proximity", "FLOAT", wdata[1::3])
                mesh_builder.set_point_attribute(cache_object.data, "flip_spray_proximity", "FLOAT", wdata[2::3])

    _update_domain_metadata_attrs(domain_object, bakefiles_dir, frameno)
    _LOADED_FRAME_CACHE[cache_key] = state
    LAST_STATS["surface_verts"] = nv
    LAST_STATS["surface_tris"] = idx.size // 3


def _load_whitewater(scene, domain_object, dom_dict, bakefiles_dir, frameno, force_load):
    ww_props = dom_dict.get("whitewater", {})
    if not ww_props.get("enable_whitewater_simulation", 0):
        return

    r = dom_dict.get("render", {})
    mode = r.get("whitewater_render_display", 0) if IS_RENDERING else r.get("whitewater_viewport_display", 0)
    bounds = fast_io.read_json_file(os.path.join(bakefiles_dir, f"bounds{frameno:06d}.bbox"))
    if bounds is None:
        bounds = {"x": 0.0, "y": 0.0, "z": 0.0, "width": 1.0, "height": 1.0, "depth": 1.0, "isize": 0, "jsize": 0, "ksize": 0}

    mc_root = dom_dict.get("mesh_cache", {})
    types_cfg = [
        ("foam", "whitewater_foam", "render_foam_pct", "viewport_foam_pct"),
        ("bubble", "whitewater_bubble", "render_bubble_pct", "viewport_bubble_pct"),
        ("spray", "whitewater_spray", "render_spray_pct", "viewport_spray_pct"),
        ("dust", "whitewater_dust", "render_dust_pct", "viewport_dust_pct"),
    ]

    for key_name, obj_prefix, r_pct_key, v_pct_key in types_cfg:
        cache_object = _resolve_cache_object(scene, mc_root.get(key_name), obj_prefix)
        if cache_object is None or cache_object.mode == "EDIT":
            continue

        pct = 0 if mode == 2 else int(r.get(r_pct_key if IS_RENDERING else v_pct_key, 100 if IS_RENDERING else 5))
        cache_key = (key_name, cache_object.name)
        state = (frameno, mode, pct, IS_RENDERING)
        if not force_load and _LOADED_FRAME_CACHE.get(cache_key) == state:
            continue

        wwp_path = os.path.join(bakefiles_dir, f"{key_name}{frameno:06d}.wwp")
        pos, idx = fast_io.read_wwp(wwp_path, pct) if (pct > 0 and os.path.isfile(wwp_path)) else (fast_io._EMPTY_F32, fast_io._EMPTY_I32)

        nv = pos.size // 3
        if nv > 0:
            pos.reshape(-1, 3)[:] -= np.array([bounds["x"], bounds["y"], bounds["z"]], dtype=np.float32)

        octane_type = cache_object.octane.object_mesh_type if hasattr(scene, "octane") else None
        mesh_builder.swap_mesh_geometry(
            cache_object,
            pos,
            idx,
            mesh_name=cache_object.name,
            smooth_mesh=False,
            octane_mesh_type=octane_type,
        )
        _apply_transforms(cache_object, domain_object, bounds, nv)

        if mode != 2 and nv > 0:
            if ww_props.get("enable_velocity_vector_attribute", 0):
                vpath = os.path.join(bakefiles_dir, f"velocity{key_name}{frameno:06d}.wwp")
                vdata, _ = fast_io.read_wwp(vpath, pct)
                mesh_builder.set_point_attribute(cache_object.data, "flip_velocity", "FLOAT_VECTOR", vdata)
            if ww_props.get("enable_id_attribute", 0):
                ipath = os.path.join(bakefiles_dir, f"id{key_name}{frameno:06d}.wwi")
                idata, _ = fast_io.read_wwi(ipath, pct)
                mesh_builder.set_point_attribute(cache_object.data, "flip_id", "INT", idata)
            if ww_props.get("enable_lifetime_attribute", 0):
                lpath = os.path.join(bakefiles_dir, f"lifetime{key_name}{frameno:06d}.wwf")
                ldata, _ = fast_io.read_wwf(lpath, pct)
                mesh_builder.set_point_attribute(cache_object.data, "flip_lifetime", "FLOAT", ldata)

        _LOADED_FRAME_CACHE[cache_key] = state


def load_frame(scene, frameno=None, force_load=False):
    domain_object = find_domain_object(scene)
    if domain_object is None:
        return False

    ff = _get_sys_flip_dict(domain_object)
    dom_dict = ff.get("domain") if ff else None
    if dom_dict is None:
        return False

    bakefiles_dir = _get_bakefiles_dir(dom_dict)
    if not bakefiles_dir or not os.path.isdir(bakefiles_dir):
        return False

    if frameno is None:
        frameno = get_current_simulation_frame(scene, dom_dict)

    t0 = time.perf_counter()
    _load_surface(scene, domain_object, dom_dict, bakefiles_dir, frameno, force_load or IS_RENDERING)
    _load_whitewater(scene, domain_object, dom_dict, bakefiles_dir, frameno, force_load or IS_RENDERING)
    dt_ms = (time.perf_counter() - t0) * 1000.0

    LAST_STATS["frame"] = frameno
    LAST_STATS["load_ms"] = dt_ms
    LAST_STATS["mode"] = "Standalone"
    return True
