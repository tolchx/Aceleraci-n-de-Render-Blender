# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-platform packager and installer for flip_fast_render (Blender 4.5+ / 5.x)."""

import argparse
import os
import platform
import shutil
import subprocess
import zipfile


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_SRC = os.path.join(REPO_ROOT, "flip_fast_render")


def get_blender_user_base():
    sys_name = platform.system()
    if sys_name == "Windows":
        return os.path.join(os.environ.get("APPDATA", ""), "Blender Foundation", "Blender")
    if sys_name == "Darwin":
        return os.path.expanduser("~/Library/Application Support/Blender")
    return os.path.expanduser("~/.config/blender")


def discover_extension_targets():
    base = get_blender_user_base()
    targets = []
    if os.path.isdir(base):
        for ver in sorted(os.listdir(base), reverse=True):
            ver_dir = os.path.join(base, ver)
            if os.path.isdir(ver_dir) and ver[0].isdigit():
                targets.append(os.path.join(ver_dir, "extensions", "user_default", "flip_fast_render"))
    if not targets:
        targets.append(os.path.join(base, "5.1", "extensions", "user_default", "flip_fast_render"))
    return targets


def build_zip(output_zip):
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ADDON_SRC):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if fname.endswith(".pyc"):
                    continue
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, REPO_ROOT).replace("\\", "/")
                zf.write(full_path, rel_path)
    print(f"Created extension archive: {output_zip}")


def install_extension(target_dir):
    os.makedirs(os.path.dirname(target_dir), exist_ok=True)
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    shutil.copytree(
        ADDON_SRC,
        target_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    print(f"Installed flip_fast_render to: {target_dir}")


def enable_in_blender(blender_exe):
    expr = (
        "import bpy, addon_utils\n"
        "for mod in ('bl_ext.user_default.flip_fast_render', 'flip_fast_render'):\n"
        "    try:\n"
        "        bpy.ops.preferences.addon_enable(module=mod)\n"
        "        bpy.ops.wm.save_userpref()\n"
        "        print('Enabled and saved preferences for:', mod)\n"
        "        break\n"
        "    except Exception as e:\n"
        "        pass\n"
    )
    subprocess.run([blender_exe, "--background", "--python-expr", expr], check=True)


def main():
    parser = argparse.ArgumentParser(description="Package or install flip_fast_render.")
    parser.add_argument("--zip", action="store_true", help="Create dist/flip_fast_render.zip")
    parser.add_argument("--install", action="store_true", help="Install into detected Blender 4.5+/5.x extensions/user_default")
    parser.add_argument("--target", default=None, help="Explicit Blender extension target directory")
    parser.add_argument("--blender", default=None, help="Blender executable path (with --enable, enables and saves userpref)")
    parser.add_argument("--enable", action="store_true", help="Enable addon in Blender and save preferences (requires --blender)")
    args = parser.parse_args()

    if not args.zip and not args.install and not args.enable:
        args.zip = True

    if args.zip:
        dist_dir = os.path.join(REPO_ROOT, "dist")
        os.makedirs(dist_dir, exist_ok=True)
        build_zip(os.path.join(dist_dir, "flip_fast_render.zip"))

    if args.install:
        targets = [args.target] if args.target else discover_extension_targets()
        for t in targets:
            install_extension(t)

    if args.enable:
        if not args.blender:
            raise SystemExit("--enable requires --blender <path_to_blender>")
        enable_in_blender(args.blender)


if __name__ == "__main__":
    main()
