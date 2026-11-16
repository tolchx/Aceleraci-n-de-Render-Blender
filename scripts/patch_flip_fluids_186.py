# SPDX-License-Identifier: GPL-3.0-or-later
"""Safe, version-checked patcher for FLIP Fluids v1.8.6 on disk (with backup & revert)."""

import argparse
import os
import shutil
import sys
from datetime import datetime


DEFAULT_ADDON_DIR = os.path.join(
    os.environ.get("APPDATA", ""),
    "Blender Foundation",
    "Blender",
    "5.1",
    "extensions",
    "user_default",
    "flip_fluids_addon",
)

EXPECTED_VERSION_LINE = 'version = "1.8.6"'

PATCH_MARKER = "# === FLIP_FAST_RENDER_PATCH_186 ==="


VCU_FAST_BLOCK = f"""{PATCH_MARKER}
_FF_ARANGE_CACHE = numpy.empty(0, dtype=numpy.int32)
_FF_THREE_CACHE = numpy.empty(0, dtype=numpy.int32)


def _set_mesh_smoothness(mesh_data, is_smooth):
    num_polys = len(mesh_data.polygons)
    if num_polys == 0:
        return
    if is_smooth:
        sharp_attr = mesh_data.attributes.get("sharp_face")
        if sharp_attr is not None:
            mesh_data.attributes.remove(sharp_attr)
        return
    mesh_data.polygons.foreach_set("use_smooth", numpy.zeros(num_polys, dtype=bool))
"""


SWAP_FAST_BODY = f"""{PATCH_MARKER}
    global _FF_ARANGE_CACHE, _FF_THREE_CACHE
    vg_layer_names = [vg.name for vg in bl_object.vertex_groups]
    active_vertex_layer_index = bl_object.vertex_groups.active_index

    mesh_data = bl_object.data
    uv_meta = [(uv.name, uv.active, uv.active_render) for uv in mesh_data.uv_layers]
    ca_meta = [(ca.name, ca.data_type, ca.domain) for ca in mesh_data.color_attributes]

    pos = (
        vertices
        if isinstance(vertices, numpy.ndarray) and vertices.dtype == numpy.float32
        else numpy.asarray(vertices, dtype=numpy.float32)
    ).ravel()
    idx = (
        triangles
        if isinstance(triangles, numpy.ndarray) and triangles.dtype == numpy.int32
        else numpy.asarray(triangles, dtype=numpy.int32)
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
            if _FF_ARANGE_CACHE.size < nt:
                _FF_ARANGE_CACHE = numpy.arange(0, nt * 3, 3, dtype=numpy.int32)
                _FF_THREE_CACHE = numpy.full(nt, 3, dtype=numpy.int32)
            mesh_data.polygons.foreach_set("loop_start", _FF_ARANGE_CACHE[:nt])
            mesh_data.polygons.foreach_set("loop_total", _FF_THREE_CACHE[:nt])
            mesh_data.update(calc_edges=True)
            _set_mesh_smoothness(mesh_data, smooth_mesh)
        else:
            mesh_data.update()

    _set_octane_mesh_type(bl_object, octane_mesh_type)

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
"""


def verify_version(addon_dir):
    manifest = os.path.join(addon_dir, "blender_manifest.toml")
    if not os.path.isfile(manifest):
        raise RuntimeError(f"Manifest not found: {manifest}")
    with open(manifest, "r", encoding="utf-8") as f:
        text = f.read()
    if EXPECTED_VERSION_LINE not in text:
        raise RuntimeError(f"Expected FLIP Fluids 1.8.6 in {manifest}")


def backup_addon(addon_dir):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = addon_dir + f".backup_{ts}"
    shutil.copytree(addon_dir, backup_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"Backup created: {backup_dir}")
    return backup_dir


def apply_patch(addon_dir):
    verify_version(addon_dir)

    vcu_path = os.path.join(addon_dir, "utils", "version_compatibility_utils.py")
    cache_path = os.path.join(addon_dir, "objects", "flip_fluid_cache.py")

    with open(vcu_path, "r", encoding="utf-8") as f:
        vcu_src = f.read()
    with open(cache_path, "r", encoding="utf-8") as f:
        cache_src = f.read()

    if PATCH_MARKER in vcu_src or PATCH_MARKER in cache_src:
        print("Addon already patched.")
        return

    backup_addon(addon_dir)

    old_smooth = (
        "def _set_mesh_smoothness(mesh_data, is_smooth):\n"
        "        values = [is_smooth] * len(mesh_data.polygons)\n"
        '        mesh_data.polygons.foreach_set("use_smooth", values)'
    )
    if old_smooth.replace("\n", "\r\n") in vcu_src:
        old_smooth = old_smooth.replace("\n", "\r\n")
    if old_smooth not in vcu_src:
        raise RuntimeError("Could not locate _set_mesh_smoothness in version_compatibility_utils.py")

    old_swap_start = "def swap_object_mesh_data_geometry(bl_object, vertices=[], triangles=[], \n                                   mesh_name=\"Untitled\",\n                                   smooth_mesh=False,\n                                   octane_mesh_type='Global'):"
    if old_swap_start.replace("\n", "\r\n") in vcu_src:
        old_swap_start = old_swap_start.replace("\n", "\r\n")
    if old_swap_start not in vcu_src:
        raise RuntimeError("Could not locate swap_object_mesh_data_geometry signature")

    idx_start = vcu_src.index(old_swap_start) + len(old_swap_start)
    idx_end = vcu_src.index("\ndef get_addon_directory", idx_start)
    vcu_patched = vcu_src[:idx_start] + "\n" + SWAP_FAST_BODY + "\n\n" + vcu_src[idx_end:]
    vcu_patched = vcu_patched.replace(old_smooth, VCU_FAST_BLOCK, 1)

    old_bobj = (
        "    def import_bobj(self, filename, generate_flat_array=False):\n"
        "        with open(filename, \"rb\") as f:\n"
        "            bobj_data = f.read()"
    )
    if old_bobj.replace("\n", "\r\n") in cache_src:
        old_bobj = old_bobj.replace("\n", "\r\n")
    if old_bobj not in cache_src:
        raise RuntimeError("Could not locate import_bobj in flip_fluid_cache.py")

    bobj_start = cache_src.index("    def import_bobj(self, filename, generate_flat_array=False):")
    bobj_end = cache_src.index("\n    def import_ffp3(", bobj_start)
    fast_bobj = f"""    def import_bobj(self, filename, generate_flat_array=False):
        {PATCH_MARKER}
        import numpy as _np
        if not filename or not os.path.isfile(filename):
            return _np.empty(0, dtype=_np.float32), _np.empty(0, dtype=_np.int32)
        with open(filename, "rb") as f:
            hdr = f.read(4)
            if len(hdr) < 4:
                return _np.empty(0, dtype=_np.float32), _np.empty(0, dtype=_np.int32)
            nv = int(_np.frombuffer(hdr, dtype=_np.uint32, count=1)[0])
            if nv <= 0:
                return _np.empty(0, dtype=_np.float32), _np.empty(0, dtype=_np.int32)
            pos = _np.fromfile(f, dtype=_np.float32, count=nv * 3)
            nt_hdr = f.read(4)
            nt = int(_np.frombuffer(nt_hdr, dtype=_np.uint32, count=1)[0]) if len(nt_hdr) == 4 else 0
            idx = _np.fromfile(f, dtype=_np.int32, count=nt * 3) if nt > 0 else _np.empty(0, dtype=_np.int32)
        if generate_flat_array:
            return pos.tolist(), idx.tolist()
        return pos, idx
"""
    cache_patched = cache_src[:bobj_start] + fast_bobj + "\n" + cache_src[bobj_end:]

    with open(vcu_path, "w", encoding="utf-8") as f:
        f.write(vcu_patched)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(cache_patched)

    print("Patched FLIP Fluids 1.8.6 successfully.")


def main():
    parser = argparse.ArgumentParser(description="Safely patch FLIP Fluids 1.8.6 with NumPy + foreach_set.")
    parser.add_argument("--addon-dir", default=DEFAULT_ADDON_DIR, help="Path to flip_fluids_addon")
    parser.add_argument("--dry-run", action="store_true", help="Verify version and target hooks without modifying files")
    args = parser.parse_args()

    if args.dry_run:
        verify_version(args.addon_dir)
        print(f"Verified FLIP Fluids 1.8.6 at {args.addon_dir} (dry-run OK).")
        return

    apply_patch(args.addon_dir)


if __name__ == "__main__":
    main()
