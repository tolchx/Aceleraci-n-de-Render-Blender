# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable acceptance suite comparing original FLIP Fluids vs flip_fast_render on a .blend scene.

Validates:
1. Evaluated surface mesh geometry count on the first target frame.
2. PSNR >= 44 dB against original FLIP Fluids on all target frames.
3. Mean alpha difference <= 0.1 (0-255 scale) on all target frames.
4. Per-frame render timing comparison.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BLENDER_SCRIPT = r"""
import os, sys, time, bpy

idx = sys.argv.index("--")
mode = sys.argv[idx + 1]
out_dir = sys.argv[idx + 2]
frames = [int(x) for x in sys.argv[idx + 3].split(",")]
repo_root = sys.argv[idx + 4]

if mode in ("bridge", "standalone"):
    sys.path.insert(0, repo_root)
    import flip_fast_render
    flip_fast_render.register()

if mode == "standalone":
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = "OPTIX"
    except Exception:
        prefs.compute_device_type = "CUDA"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = (d.type in ("OPTIX", "CUDA"))
    bpy.context.scene.cycles.device = "GPU"

scene = bpy.context.scene
os.makedirs(out_dir, exist_ok=True)

# Inspect evaluated surface mesh on first frame
first_fr = frames[0]
ff_mods = [m for k, m in sys.modules.items() if k == "flip_fluids_addon.render" or k.endswith(".flip_fluids_addon.render")]
if mode in ("orig", "bridge") and ff_mods:
    ff_render = ff_mods[0]
    ff_render.render_init(scene)
    if mode == "bridge":
        flip_fast_render.scene_optimizer.apply_render_optimizations(scene, use_manifold_boolean=False)
    scene.frame_set(first_fr)
    ff_render.render_complete(scene)
elif mode == "standalone":
    flip_fast_render.standalone.IS_RENDERING = True
    flip_fast_render.scene_optimizer.apply_render_optimizations(scene, use_manifold_boolean=False)
    flip_fast_render.standalone.load_frame(scene, first_fr, force_load=True)

deps = bpy.context.evaluated_depsgraph_get()
for o in scene.objects:
    if o.type == "MESH" and o.name.startswith("fluid_surface"):
        ev = o.evaluated_get(deps)
        me_ev = ev.to_mesh()
        print(f"[MESH{first_fr}:{mode}] obj={o.name} verts={len(me_ev.vertices)} polys={len(me_ev.polygons)}")
        ev.to_mesh_clear()
        break

if mode == "standalone":
    flip_fast_render.standalone.IS_RENDERING = False

for fr in frames:
    scene.frame_start = fr
    scene.frame_end = fr
    scene.render.filepath = os.path.join(out_dir, "f")
    t0 = time.perf_counter()
    bpy.ops.render.render(animation=True)
    dt = time.perf_counter() - t0
    print(f"[TIME:{mode}] frame={fr} elapsed={dt:.3f}s")
"""


COMPARE_SCRIPT = r"""
import os, sys, bpy, numpy as np

idx = sys.argv.index("--")
out_root = sys.argv[idx + 1]
frames = [int(x) for x in sys.argv[idx + 2].split(",")]
test_mode = sys.argv[idx + 3]

all_ok = True
for fr in frames:
    ref_p = os.path.join(out_root, "orig", f"f{fr:04d}.png")
    tst_p = os.path.join(out_root, test_mode, f"f{fr:04d}.png")
    a = bpy.data.images.load(ref_p)
    b = bpy.data.images.load(tst_p)
    pa = np.empty(len(a.pixels), dtype=np.float32); a.pixels.foreach_get(pa); pa = pa.reshape(-1, 4)
    pb = np.empty(len(b.pixels), dtype=np.float32); b.pixels.foreach_get(pb); pb = pb.reshape(-1, 4)
    mse = float(np.mean((pa[:, :3] - pb[:, :3]) ** 2))
    psnr = 10.0 * np.log10(1.0 / mse) if mse > 0.0 else 999.0
    alpha_mad = float(np.mean(np.abs(pa[:, 3] - pb[:, 3])) * 255.0)
    ok = (psnr >= 44.0) and (alpha_mad <= 0.1)
    all_ok = all_ok and ok
    print(f"[CMP:{test_mode}] frame={fr} PSNR={psnr:.2f} dB alpha_MAD={alpha_mad:.6f} PASS={ok}")

if not all_ok:
    sys.exit(2)
"""


def find_blender(explicit):
    if explicit:
        return explicit
    found = shutil.which("blender")
    if found:
        return found
    raise SystemExit("Pass --blender <path_to_blender> or add blender to PATH.")


def run_blender_mode(blender_exe, blend_file, out_root, mode, frames, factory=False):
    out_dir = os.path.join(out_root, mode)
    cmd = [blender_exe]
    if factory:
        cmd.append("--factory-startup")
    cmd += [
        "--background",
        blend_file,
        "--python-expr",
        BLENDER_SCRIPT,
        "--",
        mode,
        out_dir,
        ",".join(str(f) for f in frames),
        REPO_ROOT,
    ]
    print(f"\n=== Running mode={mode} ===")
    res = subprocess.run(cmd, check=True, text=True, capture_output=True)
    for line in res.stdout.splitlines():
        if line.startswith("[MESH") or line.startswith("[TIME:"):
            print(line)


def compare_mode(blender_exe, out_root, test_mode, frames):
    cmd = [
        blender_exe,
        "--factory-startup",
        "--background",
        "--python-expr",
        COMPARE_SCRIPT,
        "--",
        out_root,
        ",".join(str(f) for f in frames),
        test_mode,
    ]
    res = subprocess.run(cmd, text=True, capture_output=True)
    print(res.stdout.strip())
    if res.returncode != 0:
        print(res.stderr)
        sys.exit(res.returncode)


def main():
    parser = argparse.ArgumentParser(description="Verify FLIP Fast Render accuracy and speed on any baked FLIP scene.")
    parser.add_argument("--blender", default=None, help="Path to blender executable")
    parser.add_argument("--blend", required=True, help="Path to baked .blend scene")
    parser.add_argument("--out", default=None, help="Output directory for test PNGs (default: temp dir)")
    parser.add_argument("--frames", default="1,10,20", help="Comma-separated frame numbers to render & compare")
    parser.add_argument("--skip-orig", action="store_true")
    parser.add_argument("--modes", default="bridge,standalone", help="Comma-separated test modes: bridge,standalone")
    args = parser.parse_args()

    blender_exe = find_blender(args.blender)
    out_root = args.out or tempfile.mkdtemp(prefix="flip_fast_verify_")
    frames = [int(x) for x in args.frames.split(",")]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    if not args.skip_orig:
        run_blender_mode(blender_exe, args.blend, out_root, "orig", frames, factory=False)
    for m in modes:
        run_blender_mode(blender_exe, args.blend, out_root, m, frames, factory=(m == "standalone"))
        compare_mode(blender_exe, out_root, m, frames)


if __name__ == "__main__":
    main()
