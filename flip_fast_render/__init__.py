# SPDX-License-Identifier: GPL-3.0-or-later
"""FLIP Fast Render — High-speed NumPy + foreach_set cache loader for FLIP Fluids."""

import bpy
from bpy.props import BoolProperty

from . import bridge
from . import scene_optimizer
from . import standalone
from . import ui


bl_info = {
    "name": "FLIP Fast Render",
    "description": "High-speed NumPy + foreach_set cache loader and render accelerator for FLIP Fluids",
    "author": "YPF Render Pipeline",
    "version": (1, 0, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > FLIP Fast",
    "category": "Render",
}


class FLIPFastPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    use_manifold_boolean: BoolProperty(
        name="Fast Boolean Solver (MANIFOLD - Unsafe on Non-Manifold)",
        description="Switch Boolean modifiers to MANIFOLD during render (faster, but skips cutting if a FLIP frame has non-manifold edges)",
        default=False,
    )
    skip_noop_smooth: BoolProperty(
        name="Skip 0-Iteration FF_Smooth",
        description="Bypass FF_Smooth modifiers whose iteration count is 0 during render",
        default=True,
    )
    skip_static_t71908: BoolProperty(
        name="Skip T71908 Workaround When Unanimated",
        description="Skip expensive depsgraph/socket copy workaround when domain and cache objects have no animation/drivers",
        default=True,
    )
    skip_redundant_domain_attrs: BoolProperty(
        name="Cache Domain Metadata Attributes",
        description="Avoid recreating flip_time_scale / flip_world_scale attributes on the domain when unchanged",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "use_manifold_boolean")
        layout.prop(self, "skip_noop_smooth")
        layout.prop(self, "skip_static_t71908")
        layout.prop(self, "skip_redundant_domain_attrs")


def _get_prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


def _ensure_bridge_or_standalone():
    prefs = _get_prefs()
    skip_t7 = prefs.skip_static_t71908 if prefs else True
    skip_dom = prefs.skip_redundant_domain_attrs if prefs else True
    return bridge.install_bridge(
        skip_static_t71908=skip_t7,
        skip_redundant_domain_attrs=skip_dom,
    )


@bpy.app.handlers.persistent
def _on_load_post(_dummy):
    _ensure_bridge_or_standalone()


@bpy.app.handlers.persistent
def _on_render_init(scene):
    _ensure_bridge_or_standalone()
    standalone.IS_RENDERING = True
    prefs = _get_prefs()
    scene_optimizer.apply_render_optimizations(
        scene,
        use_manifold_boolean=prefs.use_manifold_boolean if prefs else False,
        skip_noop_smooth=prefs.skip_noop_smooth if prefs else True,
    )


@bpy.app.handlers.persistent
def _on_render_pre(scene):
    if not bridge.is_bridge_installed():
        standalone.load_frame(scene)


@bpy.app.handlers.persistent
def _on_render_complete(scene):
    standalone.IS_RENDERING = False
    scene_optimizer.restore_render_optimizations(scene)
    if not bridge.is_bridge_installed():
        standalone.load_frame(scene, force_load=True)


@bpy.app.handlers.persistent
def _on_render_cancel(scene):
    _on_render_complete(scene)


@bpy.app.handlers.persistent
def _on_frame_change_post(scene, depsgraph=None):
    if _ensure_bridge_or_standalone():
        return
    standalone.load_frame(scene)


def register():
    bpy.utils.register_class(FLIPFastPreferences)
    ui.register()

    bpy.app.handlers.load_post.append(_on_load_post)
    bpy.app.handlers.render_init.append(_on_render_init)
    bpy.app.handlers.render_pre.append(_on_render_pre)
    bpy.app.handlers.render_complete.append(_on_render_complete)
    bpy.app.handlers.render_cancel.append(_on_render_cancel)
    bpy.app.handlers.frame_change_post.append(_on_frame_change_post)

    _ensure_bridge_or_standalone()


def unregister():
    for handler_list, fn in (
        (bpy.app.handlers.load_post, _on_load_post),
        (bpy.app.handlers.render_init, _on_render_init),
        (bpy.app.handlers.render_pre, _on_render_pre),
        (bpy.app.handlers.render_complete, _on_render_complete),
        (bpy.app.handlers.render_cancel, _on_render_cancel),
        (bpy.app.handlers.frame_change_post, _on_frame_change_post),
    ):
        if fn in handler_list:
            handler_list.remove(fn)

    bridge.uninstall_bridge()
    ui.unregister()
    bpy.utils.unregister_class(FLIPFastPreferences)
