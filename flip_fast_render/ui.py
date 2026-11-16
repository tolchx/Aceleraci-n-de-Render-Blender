# SPDX-License-Identifier: GPL-3.0-or-later
"""N-Panel UI and utility operators for FLIP Fast Render."""

import time
import bpy

from . import bridge
from . import standalone


class FLIPFAST_OT_benchmark_frame(bpy.types.Operator):
    bl_idname = "flip_fast_render.benchmark_frame"
    bl_label = "Benchmark Current Frame Load"
    bl_description = "Measure cache load + evaluated mesh build time for the current frame"

    def execute(self, context):
        scene = context.scene
        t0 = time.perf_counter()
        if bridge.is_bridge_installed():
            ff = getattr(scene, "flip_fluid", None)
            if ff is not None and ff.get_domain_properties() is not None:
                from . import scene_optimizer
                prefs = context.preferences.addons[__package__].preferences
                scene_optimizer.apply_render_optimizations(
                    scene,
                    use_manifold_boolean=prefs.use_manifold_boolean,
                    skip_noop_smooth=prefs.skip_noop_smooth,
                )
                dprops = ff.get_domain_properties()
                dprops.mesh_cache.surface.load_frame(scene.frame_current, force_load=True)
                mode = "Bridge"
            else:
                mode = "Bridge (no domain)"
        else:
            standalone.load_frame(scene, scene.frame_current, force_load=True)
            mode = "Standalone"

        t1 = time.perf_counter()
        deps = context.evaluated_depsgraph_get()
        t2 = time.perf_counter()

        surf_obj = None
        for o in scene.objects:
            if o.type == "MESH" and o.name.startswith("fluid_surface"):
                surf_obj = o
                break

        ev_info = ""
        if surf_obj is not None:
            ev = surf_obj.evaluated_get(deps)
            me = ev.to_mesh()
            ev_info = f" | eval verts={len(me.vertices)} polys={len(me.polygons)}"
            ev.to_mesh_clear()

        msg = f"[{mode}] load={(t1-t0)*1000:.1f}ms, depsgraph={(t2-t1)*1000:.1f}ms{ev_info}"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class FLIPFAST_PT_panel(bpy.types.Panel):
    bl_label = "FLIP Fast Render"
    bl_idname = "FLIPFAST_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "FLIP Fast"

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__package__].preferences

        box = layout.box()
        active_mode = "Bridge (FLIP Fluids detected)" if bridge.is_bridge_installed() else "Standalone (Pure NumPy)"
        box.label(text=f"Mode: {active_mode}", icon="SHADERFX")

        if standalone.LAST_STATS["frame"] >= 0:
            box.label(
                text=f"Frame {standalone.LAST_STATS['frame']}: {standalone.LAST_STATS['load_ms']:.1f} ms"
            )
            box.label(
                text=f"Surface: {standalone.LAST_STATS['surface_verts']:,} verts / {standalone.LAST_STATS['surface_tris']:,} tris"
            )

        col = layout.column(align=True)
        col.prop(prefs, "use_manifold_boolean")
        col.prop(prefs, "skip_noop_smooth")
        col.prop(prefs, "skip_static_t71908")
        col.prop(prefs, "skip_redundant_domain_attrs")

        layout.separator()
        layout.operator("flip_fast_render.benchmark_frame", icon="TIME")


def register():
    bpy.utils.register_class(FLIPFAST_OT_benchmark_frame)
    bpy.utils.register_class(FLIPFAST_PT_panel)


def unregister():
    bpy.utils.unregister_class(FLIPFAST_PT_panel)
    bpy.utils.unregister_class(FLIPFAST_OT_benchmark_frame)
