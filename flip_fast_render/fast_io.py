# SPDX-License-Identifier: GPL-3.0-or-later
"""Zero-copy / NumPy binary readers for FLIP Fluids cache files."""

import json
import math
import os
import numpy as np


_EMPTY_F32 = np.empty(0, dtype=np.float32)
_EMPTY_I32 = np.empty(0, dtype=np.int32)
_EMPTY_U16 = np.empty(0, dtype=np.uint16)
_EMPTY_U64 = np.empty(0, dtype=np.uint64)


def read_bobj(filepath):
    """Read a .bobj surface/obstacle mesh file into flat NumPy arrays.

    Format verified on FLIP Fluids 1.8.6:
        uint32  num_vertices
        float32 positions[num_vertices * 3]
        uint32  num_triangles
        int32   indices[num_triangles * 3]
    """
    if not filepath or not os.path.isfile(filepath):
        return _EMPTY_F32, _EMPTY_I32

    with open(filepath, "rb") as f:
        hdr = f.read(4)
        if len(hdr) < 4:
            return _EMPTY_F32, _EMPTY_I32
        nv = int(np.frombuffer(hdr, dtype=np.uint32, count=1)[0])
        if nv <= 0:
            return _EMPTY_F32, _EMPTY_I32

        pos = np.fromfile(f, dtype=np.float32, count=nv * 3)
        nt_hdr = f.read(4)
        if len(nt_hdr) < 4:
            return pos, _EMPTY_I32
        nt = int(np.frombuffer(nt_hdr, dtype=np.uint32, count=1)[0])
        idx = np.fromfile(f, dtype=np.int32, count=nt * 3) if nt > 0 else _EMPTY_I32

    return pos, idx


def _ww_count(f, pct):
    if pct <= 0:
        return 0
    header = np.fromfile(f, dtype=np.int32, count=256)
    if header.size < 256:
        return 0
    dataidx = int(math.ceil((pct / 100.0) * 255.0))
    dataidx = max(0, min(255, dataidx))
    return max(0, int(header[dataidx]) + 1)


def read_wwp(filepath, pct=100):
    """Read a .wwp whitewater particle positions file into a flat float32 array."""
    if pct <= 0 or not filepath or not os.path.isfile(filepath):
        return _EMPTY_F32, _EMPTY_I32

    with open(filepath, "rb") as f:
        n = _ww_count(f, pct)
        if n <= 0:
            return _EMPTY_F32, _EMPTY_I32
        pos = np.fromfile(f, dtype=np.float32, count=n * 3)

    return pos, _EMPTY_I32


def read_wwi(filepath, pct=100):
    """Read a .wwi whitewater int32 attribute file."""
    if pct <= 0 or not filepath or not os.path.isfile(filepath):
        return _EMPTY_I32, _EMPTY_I32

    with open(filepath, "rb") as f:
        n = _ww_count(f, pct)
        if n <= 0:
            return _EMPTY_I32, _EMPTY_I32
        vals = np.fromfile(f, dtype=np.int32, count=n)

    return vals, _EMPTY_I32


def read_wwf(filepath, pct=100):
    """Read a .wwf whitewater float32 attribute file."""
    if pct <= 0 or not filepath or not os.path.isfile(filepath):
        return _EMPTY_F32, _EMPTY_I32

    with open(filepath, "rb") as f:
        n = _ww_count(f, pct)
        if n <= 0:
            return _EMPTY_F32, _EMPTY_I32
        vals = np.fromfile(f, dtype=np.float32, count=n)

    return vals, _EMPTY_I32


_FFP3_DTYPE = {
    "ATTRIBUTE_TYPE_VECTOR": (np.float32, 3),
    "ATTRIBUTE_TYPE_INT": (np.int32, 1),
    "ATTRIBUTE_TYPE_FLOAT": (np.float32, 1),
    "ATTRIBUTE_TYPE_UINT16": (np.uint16, 1),
    "ATTRIBUTE_TYPE_ULONGLONG": (np.uint64, 1),
}


def read_ffp3(
    filepath,
    pct_surface=1.0,
    pct_boundary=1.0,
    pct_interior=1.0,
    attribute_type="ATTRIBUTE_TYPE_VECTOR",
):
    """Read a .ffp3 fluid particle attribute file using slice offsets."""
    if not filepath or not os.path.isfile(filepath):
        return _EMPTY_F32, _EMPTY_I32, None
    if pct_surface == 0.0 and pct_boundary == 0.0 and pct_interior == 0.0:
        return _EMPTY_F32, _EMPTY_I32, None

    dtype, comp = _FFP3_DTYPE[attribute_type]
    itemsize = np.dtype(dtype).itemsize * comp

    with open(filepath, "rb") as f:
        hdr = np.fromfile(f, dtype=np.uint32, count=4)
        if hdr.size < 4:
            return _EMPTY_F32, _EMPTY_I32, None
        n_surf, n_bound, n_inter, id_limit = (int(hdr[0]), int(hdr[1]), int(hdr[2]), int(hdr[3]))
        id_table = np.fromfile(f, dtype=np.uint32, count=id_limit * 3).reshape(id_limit, 3)

        tol = 1e-9
        id_s = int(math.ceil(pct_surface * (id_limit - 1)))
        id_b = int(math.ceil(pct_boundary * (id_limit - 1)))
        id_i = int(math.ceil(pct_interior * (id_limit - 1)))

        cnt_s = 0 if pct_surface < tol else int(id_table[id_s, 0])
        cnt_b = 0 if pct_boundary < tol else int(id_table[id_b, 1])
        cnt_i = 0 if pct_interior < tol else int(id_table[id_i, 2])

        base_offset = (4 + id_limit * 3) * 4
        off_s = base_offset
        off_b = off_s + n_surf * itemsize
        off_i = off_b + n_bound * itemsize

        parts = []
        if cnt_s > 0:
            f.seek(off_s)
            parts.append(np.fromfile(f, dtype=dtype, count=cnt_s * comp))
        if cnt_b > 0:
            f.seek(off_b)
            parts.append(np.fromfile(f, dtype=dtype, count=cnt_b * comp))
        if cnt_i > 0:
            f.seek(off_i)
            parts.append(np.fromfile(f, dtype=dtype, count=cnt_i * comp))

    values = np.concatenate(parts) if len(parts) > 1 else (parts[0] if parts else np.empty(0, dtype=dtype))
    info = {
        "num_surface_particles": n_surf,
        "num_boundary_particles": n_bound,
        "num_interior_particles": n_inter,
        "id_limit": id_limit,
        "num_surface_particles_to_read": cnt_s,
        "num_boundary_particles_to_read": cnt_b,
        "num_interior_particles_to_read": cnt_i,
    }
    return values, _EMPTY_I32, info


def read_floats(filepath):
    if not filepath or not os.path.isfile(filepath):
        return _EMPTY_F32
    return np.fromfile(filepath, dtype=np.float32)


def read_ints(filepath):
    if not filepath or not os.path.isfile(filepath):
        return _EMPTY_I32
    return np.fromfile(filepath, dtype=np.int32)


def read_json_file(filepath):
    if not filepath or not os.path.isfile(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)
