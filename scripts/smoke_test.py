# SPDX-License-Identifier: GPL-3.0-or-later
"""Self-contained synthetic smoke test for flip_fast_render inside Blender (no external .blend needed)."""

import argparse
import os
import shutil
import subprocess
import sys


BLENDER_SMOKE = r"""
import json, os, struct, sys, tempfile, bpy, numpy as np

repo_root = sys.argv[sys.argv.index("--") + 1]
sys.path.insert(0, repo_root)
import flip_fast_render
from flip_fast_render import fast_io, mesh_builder, standalone

flip_fast_render.register()

with tempfile.TemporaryDirectory() as tmp:
    bake = os.path.join(tmp, "bakefiles")
    os.makedirs(bake, exist_ok=True)

    # Synthetic 1-tetrahedron .bobj (4 verts, 4 tris)
    verts = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float32)
    tris = np.array([
        [0, 2, 1],
        [0, 1, 3],
        [1, 2, 3],
        [2, 0, 3],
    ], dtype=np.int32)
    bobj_path = os.path.join(bake, "000001.bobj")
    with open(bobj_path, "wb") as f:
        f.write(struct.pack("<I", 4))
        f.write(verts.tobytes())
        f.write(struct.pack("<I", 4))
        f.write(tris.tobytes())

    # Synthetic .wwp (3 particles at 100%)
    wwp_path = os.path.join(bake, "foam000001.wwp")
    hdr = np.full(256, 2, dtype=np.int32)  # count - 1 = 2 -> 3 particles
    ww_pts = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9], dtype=np.float32)
    with open(wwp_path, "wb") as f:
        f.write(hdr.tobytes())
        f.write(ww_pts.tobytes())

    pos, idx = fast_io.read_bobj(bobj_path)
    assert pos.size == 12 and idx.size == 12, f"Unexpected bobj sizes: {pos.size}, {idx.size}"
    wpos, _ = fast_io.read_wwp(wwp_path, 100)
    assert wpos.size == 9, f"Unexpected wwp size: {wpos.size}"

    # Build mesh via mesh_builder
    me = bpy.data.meshes.new("smoke_mesh")
    obj = bpy.data.objects.new("fluid_surface_smoke", me)
    bpy.context.scene.collection.objects.link(obj)
    mesh_builder.swap_mesh_geometry(obj, pos, idx, smooth_mesh=True)
    assert len(me.vertices) == 4 and len(me.polygons) == 4
    assert me.polygons[0].use_smooth is True

    mesh_builder.swap_mesh_geometry(obj, pos, idx, smooth_mesh=False)
    assert me.polygons[0].use_smooth is False

    print("[SMOKE] fast_io + mesh_builder + register/unregister PASSED")

flip_fast_render.unregister()
"""


def main():
    parser = argparse.ArgumentParser(description="Run self-contained Blender smoke test for flip_fast_render.")
    parser.add_argument("--blender", default=None, help="Path to blender executable")
    args = parser.parse_args()

    blender_exe = args.blender or shutil.which("blender")
    if not blender_exe:
        raise SystemExit("Pass --blender <path_to_blender> or add blender to PATH.")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = [blender_exe, "--factory-startup", "--background", "--python-expr", BLENDER_SMOKE, "--", repo_root]
    res = subprocess.run(cmd, text=True, capture_output=True)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr)
        sys.exit(res.returncode)


if __name__ == "__main__":
    main()
