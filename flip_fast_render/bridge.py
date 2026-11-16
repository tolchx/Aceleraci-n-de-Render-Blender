# SPDX-License-Identifier: GPL-3.0-or-later
"""In-memory accelerator bridge for FLIP Fluids v1.8.6 when it is installed & enabled."""

import os
import sys
import numpy as np
import bpy

from . import fast_io
from . import mesh_builder


_PATCHED_TARGETS = None
_ORIGINALS = {}
_DOMAIN_ATTR_CACHE = {}


def find_flip_fluids_root_module():
    """Return the loaded flip_fluids_addon root module if active, else None."""
    for name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        if name == "flip_fluids_addon" or name.endswith(".flip_fluids_addon"):
            if hasattr(mod, "render") and hasattr(mod, "objects"):
                return mod
    return None


def is_bridge_installed():
    return _PATCHED_TARGETS is not None


def _has_animation(obj):
    if obj is None or obj.animation_data is None:
        return False
    ad = obj.animation_data
    if ad.action is not None:
        return True
    if ad.drivers and len(ad.drivers) > 0:
        return True
    return False


def _fast_update_attribute(cache_self, import_fn, frameno, attr_name, data_type, is_vector=False):
    cache_object = cache_self.get_cache_object()
    if cache_object is None:
        return
    data, _ = import_fn(frameno)
    if data is None or len(data) == 0:
        return
    arr = data if isinstance(data, np.ndarray) else np.asarray(data)
    if is_vector:
        arr = arr.astype(np.float32, copy=False).ravel()
    mesh_builder.set_point_attribute(cache_object.data, attr_name, data_type, arr)


def _make_fast_domain_attr_updater(orig_fn):
    def _fast_update_domain_data_storage_attributes(self, current_frame):
        domain_object = self._get_domain_object()
        if not domain_object:
            return

        if self.enable_uid_attribute:
            orig_fn(self, current_frame)
            return

        bakefiles_directory = self._get_bakefiles_directory()
        metadata_filename = "metadata" + self._frame_number_to_string(current_frame) + ".json"
        metadata_filepath = os.path.join(bakefiles_directory, metadata_filename)
        metadata_dict = fast_io.read_json_file(metadata_filepath) or {}

        time_scale_value = float(metadata_dict.get("time_scale", 1.0))
        world_scale_value = float(metadata_dict.get("world_scale", 1.0))

        mesh = domain_object.data
        nv = len(mesh.vertices)
        cache_key = (domain_object.name, nv)
        prev = _DOMAIN_ATTR_CACHE.get(cache_key)
        has_attrs = (
            mesh.attributes.get("flip_time_scale") is not None
            and mesh.attributes.get("flip_world_scale") is not None
        )
        if prev == (time_scale_value, world_scale_value) and has_attrs:
            return

        if nv > 0:
            mesh_builder.set_point_attribute(
                mesh, "flip_time_scale", "FLOAT", np.full(nv, time_scale_value, dtype=np.float32)
            )
            mesh_builder.set_point_attribute(
                mesh, "flip_world_scale", "FLOAT", np.full(nv, world_scale_value, dtype=np.float32)
            )
        _DOMAIN_ATTR_CACHE[cache_key] = (time_scale_value, world_scale_value)

    return _fast_update_domain_data_storage_attributes


def _make_fast_id_attr_updater():
    def _fast_update_id_attribute(self, frameno):
        if not self.enable_id_attribute:
            return
        cache_object = self.get_cache_object()
        if cache_object is None:
            return
        id_data, ffp3_header_info = self._import_id_attribute_data(frameno)
        if id_data is None or len(id_data) == 0:
            return

        mesh = cache_object.data
        mesh_builder.set_point_attribute(mesh, "flip_id", "INT", id_data)

        if ffp3_header_info is not None:
            ns = ffp3_header_info["num_surface_particles_to_read"]
            nb = ffp3_header_info["num_boundary_particles_to_read"]
            ni = ffp3_header_info["num_interior_particles_to_read"]
            total = ns + nb + ni
            is_s = np.zeros(total, dtype=bool)
            is_s[:ns] = True
            is_b = np.zeros(total, dtype=bool)
            is_b[ns:ns + nb] = True
            is_i = np.zeros(total, dtype=bool)
            is_i[ns + nb:] = True
            mesh_builder.set_point_attribute(mesh, "flip_is_surface_particle", "BOOLEAN", is_s)
            mesh_builder.set_point_attribute(mesh, "flip_is_boundary_particle", "BOOLEAN", is_b)
            mesh_builder.set_point_attribute(mesh, "flip_is_interior_particle", "BOOLEAN", is_i)

    return _fast_update_id_attribute


def _make_fast_wwp_attr_updater():
    def _fast_update_whitewater_proximity_attribute(self, frameno):
        if not self.enable_whitewater_proximity_attribute:
            return
        cache_object = self.get_cache_object()
        if cache_object is None:
            return
        data, _ = self._import_whitewater_proximity_attribute_data(frameno)
        if data is None or len(data) == 0:
            return
        arr = data if isinstance(data, np.ndarray) else np.asarray(data, dtype=np.float32)
        mesh = cache_object.data
        mesh_builder.set_point_attribute(mesh, "flip_foam_proximity", "FLOAT", arr[0::3])
        mesh_builder.set_point_attribute(mesh, "flip_bubble_proximity", "FLOAT", arr[1::3])
        mesh_builder.set_point_attribute(mesh, "flip_spray_proximity", "FLOAT", arr[2::3])

    return _fast_update_whitewater_proximity_attribute


def install_bridge(skip_static_t71908=True, skip_redundant_domain_attrs=True):
    """Patch FLIP Fluids in-memory hot paths. Safe to call repeatedly."""
    global _PATCHED_TARGETS, _ORIGINALS
    if _PATCHED_TARGETS is not None:
        return True

    root = find_flip_fluids_root_module()
    if root is None:
        return False

    base_name = root.__name__
    cache_mod = sys.modules.get(base_name + ".objects.flip_fluid_cache")
    vcu_mod = sys.modules.get(base_name + ".utils.version_compatibility_utils")
    api_mod = sys.modules.get(base_name + ".utils.api_workaround_utils")
    if cache_mod is None or vcu_mod is None:
        return False

    cls = cache_mod.FlipFluidMeshCache

    _ORIGINALS = {
        "import_bobj": cls.import_bobj,
        "import_wwp": cls.import_wwp,
        "import_wwi": cls.import_wwi,
        "import_wwf": cls.import_wwf,
        "import_ffp3": cls.import_ffp3,
        "import_floats": cls.import_floats,
        "import_ints": cls.import_ints,
        "_set_mesh_smoothness": cls._set_mesh_smoothness,
        "_update_velocity_attribute": cls._update_velocity_attribute,
        "_update_speed_attribute": cls._update_speed_attribute,
        "_update_vorticity_attribute": cls._update_vorticity_attribute,
        "_update_age_attribute": cls._update_age_attribute,
        "_update_color_attribute": cls._update_color_attribute,
        "_update_source_id_attribute": cls._update_source_id_attribute,
        "_update_uid_attribute": cls._update_uid_attribute,
        "_update_viscosity_attribute": cls._update_viscosity_attribute,
        "_update_density_attribute": cls._update_density_attribute,
        "_update_id_attribute": cls._update_id_attribute,
        "_update_lifetime_attribute": cls._update_lifetime_attribute,
        "_update_whitewater_proximity_attribute": cls._update_whitewater_proximity_attribute,
        "_update_domain_data_storage_attributes": cls._update_domain_data_storage_attributes,
        "vcu_swap": vcu_mod.swap_object_mesh_data_geometry,
        "vcu_smooth": vcu_mod._set_mesh_smoothness,
        "t71908": getattr(api_mod, "frame_change_post_apply_T71908_workaround", None) if api_mod else None,
    }

    cls.import_bobj = lambda self, filename, generate_flat_array=False: fast_io.read_bobj(filename)
    cls.import_wwp = lambda self, filename, pct, generate_flat_array=False: fast_io.read_wwp(filename, pct)
    cls.import_wwi = lambda self, filename, pct: fast_io.read_wwi(filename, pct)
    cls.import_wwf = lambda self, filename, pct: fast_io.read_wwf(filename, pct)
    cls.import_ffp3 = (
        lambda self, filename, pct_surface=1.0, pct_boundary=1.0, pct_interior=1.0,
        attribute_type="ATTRIBUTE_TYPE_UNKNOWN", generate_flat_array=False:
        fast_io.read_ffp3(filename, pct_surface, pct_boundary, pct_interior, attribute_type)
    )
    cls.import_floats = lambda self, filename: fast_io.read_floats(filename)
    cls.import_ints = lambda self, filename: fast_io.read_ints(filename)
    cls._set_mesh_smoothness = lambda self, mesh_data, is_smooth: mesh_builder.set_mesh_smoothness(mesh_data, is_smooth)

    cls._update_velocity_attribute = lambda self, frameno: (
        _fast_update_attribute(self, self._import_velocity_attribute_data, frameno, "flip_velocity", "FLOAT_VECTOR", True)
        if self.enable_velocity_attribute else None
    )
    cls._update_speed_attribute = lambda self, frameno: (
        _fast_update_attribute(self, self._import_speed_attribute_data, frameno, "flip_speed", "FLOAT", False)
        if self.enable_speed_attribute else None
    )
    cls._update_vorticity_attribute = lambda self, frameno: (
        _fast_update_attribute(self, self._import_vorticity_attribute_data, frameno, "flip_vorticity", "FLOAT_VECTOR", True)
        if self.enable_vorticity_attribute else None
    )
    cls._update_age_attribute = lambda self, frameno: (
        _fast_update_attribute(self, self._import_age_attribute_data, frameno, "flip_age", "FLOAT", False)
        if self.enable_age_attribute else None
    )
    cls._update_color_attribute = lambda self, frameno: (
        _fast_update_attribute(self, self._import_color_attribute_data, frameno, "flip_color", "FLOAT_VECTOR", True)
        if self.enable_color_attribute else None
    )
    cls._update_source_id_attribute = lambda self, frameno: (
        _fast_update_attribute(self, self._import_source_id_attribute_data, frameno, "flip_source_id", "INT", False)
        if self.enable_source_id_attribute else None
    )
    cls._update_uid_attribute = lambda self, frameno: (
        _fast_update_attribute(self, self._import_uid_attribute_data, frameno, "flip_uid", "INT", False)
        if self.enable_uid_attribute else None
    )
    cls._update_viscosity_attribute = lambda self, frameno: (
        _fast_update_attribute(self, self._import_viscosity_attribute_data, frameno, "flip_viscosity", "FLOAT", False)
        if self.enable_viscosity_attribute else None
    )
    cls._update_density_attribute = lambda self, frameno: (
        _fast_update_attribute(self, self._import_density_attribute_data, frameno, "flip_density", "FLOAT", False)
        if self.enable_density_attribute else None
    )
    cls._update_id_attribute = _make_fast_id_attr_updater()
    cls._update_lifetime_attribute = lambda self, frameno: (
        _fast_update_attribute(self, self._import_lifetime_attribute_data, frameno, "flip_lifetime", "FLOAT", False)
        if self.enable_lifetime_attribute else None
    )
    cls._update_whitewater_proximity_attribute = _make_fast_wwp_attr_updater()

    if skip_redundant_domain_attrs:
        cls._update_domain_data_storage_attributes = _make_fast_domain_attr_updater(
            _ORIGINALS["_update_domain_data_storage_attributes"]
        )

    vcu_mod.swap_object_mesh_data_geometry = mesh_builder.swap_mesh_geometry
    vcu_mod._set_mesh_smoothness = mesh_builder.set_mesh_smoothness

    if skip_static_t71908 and api_mod is not None and _ORIGINALS["t71908"] is not None:
        orig_t71908 = _ORIGINALS["t71908"]

        def _smart_t71908(context, depsgraph=None):
            dprops = context.scene.flip_fluid.get_domain_properties()
            if dprops is None:
                return
            dom = context.scene.flip_fluid.get_domain_object()
            objs = [
                dom,
                dprops.mesh_cache.surface.get_cache_object(),
                dprops.mesh_cache.particles.get_cache_object(),
                dprops.mesh_cache.foam.get_cache_object(),
                dprops.mesh_cache.bubble.get_cache_object(),
                dprops.mesh_cache.spray.get_cache_object(),
                dprops.mesh_cache.dust.get_cache_object(),
            ]
            if not any(_has_animation(o) for o in objs):
                return
            orig_t71908(context, depsgraph)

        api_mod.frame_change_post_apply_T71908_workaround = _smart_t71908

    _PATCHED_TARGETS = (cache_mod, vcu_mod, api_mod)
    return True


def uninstall_bridge():
    """Restore original FLIP Fluids methods if patched."""
    global _PATCHED_TARGETS, _ORIGINALS
    if _PATCHED_TARGETS is None:
        return

    cache_mod, vcu_mod, api_mod = _PATCHED_TARGETS
    cls = cache_mod.FlipFluidMeshCache

    for attr_name in (
        "import_bobj",
        "import_wwp",
        "import_wwi",
        "import_wwf",
        "import_ffp3",
        "import_floats",
        "import_ints",
        "_set_mesh_smoothness",
        "_update_velocity_attribute",
        "_update_speed_attribute",
        "_update_vorticity_attribute",
        "_update_age_attribute",
        "_update_color_attribute",
        "_update_source_id_attribute",
        "_update_uid_attribute",
        "_update_viscosity_attribute",
        "_update_density_attribute",
        "_update_id_attribute",
        "_update_lifetime_attribute",
        "_update_whitewater_proximity_attribute",
        "_update_domain_data_storage_attributes",
    ):
        if attr_name in _ORIGINALS:
            setattr(cls, attr_name, _ORIGINALS[attr_name])

    vcu_mod.swap_object_mesh_data_geometry = _ORIGINALS["vcu_swap"]
    vcu_mod._set_mesh_smoothness = _ORIGINALS["vcu_smooth"]
    if api_mod is not None and _ORIGINALS.get("t71908") is not None:
        api_mod.frame_change_post_apply_T71908_workaround = _ORIGINALS["t71908"]

    _PATCHED_TARGETS = None
    _ORIGINALS.clear()
    _DOMAIN_ATTR_CACHE.clear()
