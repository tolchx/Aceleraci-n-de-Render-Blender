# SPDX-License-Identifier: GPL-3.0-or-later
"""Non-destructive render-time modifier optimizations for FLIP cache objects."""

import bpy


_SAVED_STATE = {}


def _iter_cache_objects(scene):
    ff = getattr(scene, "flip_fluid", None)
    if ff is not None and hasattr(ff, "get_domain_properties"):
        dprops = ff.get_domain_properties()
        if dprops is not None:
            mc = dprops.mesh_cache
            for attr in ("surface", "particles", "foam", "bubble", "spray", "dust", "obstacle"):
                c = getattr(mc, attr, None)
                if c is not None:
                    obj = c.get_cache_object()
                    if obj is not None:
                        yield obj
            return

    for obj in scene.objects:
        if obj.type == "MESH" and (
            obj.name.startswith("fluid_surface")
            or obj.name.startswith("fluid_particles")
            or obj.name.startswith("whitewater_")
        ):
            yield obj


def apply_render_optimizations(scene, use_manifold_boolean=False, skip_noop_smooth=True):
    """Apply reversible modifier optimizations before rendering."""
    global _SAVED_STATE
    _SAVED_STATE.clear()

    for obj in _iter_cache_objects(scene):
        obj_saved = {}
        for mod in obj.modifiers:
            if use_manifold_boolean and mod.type == "BOOLEAN":
                enum_ids = {e.identifier for e in mod.bl_rna.properties["solver"].enum_items}
                if "MANIFOLD" in enum_ids and mod.solver != "MANIFOLD":
                    obj_saved[(mod.name, "solver")] = mod.solver
                    mod.solver = "MANIFOLD"
            elif skip_noop_smooth and mod.type == "SMOOTH" and mod.iterations == 0:
                if mod.show_render or mod.show_viewport:
                    obj_saved[(mod.name, "show_render")] = mod.show_render
                    obj_saved[(mod.name, "show_viewport")] = mod.show_viewport
                    mod.show_render = False
                    mod.show_viewport = False
        if obj_saved:
            _SAVED_STATE[obj.name] = obj_saved


def restore_render_optimizations(scene):
    """Restore modifier settings modified by apply_render_optimizations."""
    global _SAVED_STATE
    if not _SAVED_STATE:
        return

    for obj_name, saved in _SAVED_STATE.items():
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            continue
        for (mod_name, prop_name), orig_val in saved.items():
            mod = obj.modifiers.get(mod_name)
            if mod is not None and hasattr(mod, prop_name):
                setattr(mod, prop_name, orig_val)
    _SAVED_STATE.clear()
