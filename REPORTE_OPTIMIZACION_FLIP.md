# Optimización del pipeline de render — FLIP Fluids + Cycles (proyecto YPF)

Reporte técnico con mediciones reales. Objetivo: reducir el costo por frame de ~20 s a
menos de 5 s **sin cambiar un solo píxel** del resultado.

---

## 1. Contexto del proyecto

| Dato | Valor |
|---|---|
| Proyecto | `D:\Proyectos_Activos\2026-11-16 YPF` |
| Escena | `Blender\ocean_motia_v8_RENDER.blend` (copia de trabajo; el original `_OK.blend` no se toca) |
| Blender | 5.1.2 (el `.blend` está escrito en 5.1; un 4.2 falla con "not a blend file") |
| Addon | FLIP Fluids **1.8.6** (`bl_ext.user_default.flip_fluids_addon`), requiere Blender ≥ 4.5 |
| Cache | `cache\bakefiles`, frames 1–1600 completos (52,4 GB, 20.800 archivos) |
| Motor | **Cycles**, 128 spp, adaptive 0.1, denoise OPTIX, max_bounces 12, transmission 12, caustics ON |
| Salida | 1920×1080, PNG **RGBA con alpha** (`film_transparent = True`) |
| Rango | frames **364 → 1600** (1237 frames) |
| Nombres | `agua_ultimo_sombra` + 4 dígitos → `agua_ultimo_sombra0364.png` |
| Hardware | RTX 4090 (OptiX), Ryzen 9 5900X 24 hilos, 64 GB RAM |

---

## 2. Diagnóstico medido

Antes de optimizar se midió con instrumentación real, no con estimaciones:

| Medición | Resultado |
|---|---|
| Frame completo (con addon, GPU) | **20,1 – 25,2 s** |
| Frame con el addon **deshabilitado** | **2,2 – 2,3 s** |
| 32 / 64 / 128 samples | **idéntico** (~27-29 s en esa sesión) → el costo NO es sampling |
| Denoise ON vs OFF | 28,9 s vs 26,5 s → el denoiser no es el cuello |
| Misma ruta, dos corridas | PSNR **71,7 dB** → el render es determinista |
| GPU vs CPU (control, misma ruta) | PSNR 44,3 dB |
| Uso de GPU durante el render | 14–36 % medio, reloj a **210 MHz (idle)**, picos a 2685 MHz |

Perfilado del frame (cProfile, 9,5 s de Python puro):

| Función | Costo |
|---|---|
| `_bpy_types.py:797(shade_flat)` ×5 objetos | **2,65 s** |
| `_bpy_types.py:684(from_pydata)` ×5 objetos | **4,23 s** (acumulado) |
| `numpy.array`, `foreach_set`, I/O | ~2,0 s |
| `_cycles.render` (render real en GPU) | **2,62 s** |

**Conclusión:** la GPU hace el render en ~2,6 s y después queda dormida esperando al
Python del addon, que reconstruye la malla del agua en cada frame.

---

## 3. Causa raíz

El cache guarda **dos mallas por frame**:

| Archivo | Tamaño | Vértices | Uso |
|---|---|---|---|
| `preview000402.bobj` | 1,8 MB | 34.060 | viewport |
| `000402.bobj` | 29 MB | **825.680** (1.651.356 tris) | **render** |

El render usa la malla **final**, 16× más densa que la del viewport. El addon la
reconstruye desde cero en Python cada frame.

---

## 4. Formato `.bobj` — decodificado y verificado

Ingeniería inversa validada contra el tamaño exacto del archivo:

```
uint32   num_vertices              = 825.680
float32  posiciones[num_vertices × 3]     // x,y,z intercalados, sin normales
uint32   num_triangles             = 1.651.356
int32    indices[num_triangles × 3]       // triángulos
```

Verificación: `4 + nv*12 + 4 + nt*12 = 29.724.440` = tamaño exacto del archivo.
`F/V = 2,0` (superficie cerrada). `max(indice) = nv − 1`.

Comprobado en los frames 402, 500, 1200 y 1600. **No hay normales en el archivo.**

> Trampa: 4 bytes después de `num_vertices*3*2` hay un valor (~mitad de los triángulos)
> que parece un conteo. No lo es. Cualquier parser que asuma normales produce basura.

Para confirmar el offset correcto del conteo de triángulos: `4 + nv*12`.

---

## 5. Dónde intervenir (código exacto del addon, GPL-3.0)

Instalación local:
`C:\Users\Tolch\AppData\Roaming\Blender Foundation\Blender\5.1\extensions\user_default\flip_fluids_addon\`

| Archivo | Línea | Función | Rol |
|---|---|---|---|
| `objects\flip_fluid_cache.py` | 1133 | `import_bobj(filename, generate_flat_array=False)` | lee el `.bobj` con `struct.unpack_from` + `list(zip(...))` |
| `utils\version_compatibility_utils.py` | 346 | `swap_object_mesh_data_geometry(...)` | arma la malla |
| `utils\version_compatibility_utils.py` | 374 | `bl_object.data.from_pydata(vertices, [], triangles)` | **el punto lento** |
| `utils\version_compatibility_utils.py` | 324 | `_set_mesh_smoothness(mesh_data, is_smooth)` | `foreach_set("use_smooth", ...)` |
| `render.py` | 304 | `__load_surface_frame(frameno, ...)` | handler por frame durante el render |

Código actual del hot path (resumido):

```python
vertices  = numpy.array(vertices, dtype=numpy.float32)
vertex_index = numpy.array(triangles, dtype=numpy.int32)
bl_object.data.clear_geometry()
bl_object.data.from_pydata(vertices, [], triangles)   # ← LENTO
_set_mesh_smoothness(bl_object.data, smooth_mesh)
```

---

## 6. Implementación de referencia (ya probada)

Reemplazo del camino de construcción. Medido: **0,83 s** (leer 0,02 s + construir 0,81 s)
contra los ~18 s del addon.

```python
import numpy as np

# --- parse ---
with open(path, "rb") as f:
    nv = int(np.fromfile(f, np.uint32, 1)[0])
    pos = np.fromfile(f, np.float32, nv * 3)
    nt = int(np.fromfile(f, np.uint32, 1)[0])
    idx = np.fromfile(f, np.int32, nt * 3)

# --- build (sin from_pydata) ---
me = obj.data
me.clear_geometry()
me.vertices.add(nv)
me.vertices.foreach_set("co", pos)
me.loops.add(nt * 3)
me.loops.foreach_set("vertex_index", idx)
me.polygons.add(nt)
me.polygons.foreach_set("loop_start", np.arange(0, nt * 3, 3, dtype=np.int32))
me.update(calc_edges=True)
# luego: _set_mesh_smoothness(...) igual que el addon
```

Resultado: malla base correcta, `verts=825.680 polys=1.651.356` (idéntico al archivo).

### Lo que falta resolver (primer objetivo)

Con la malla base idéntica, el **mesh evaluado** (con los modificadores
`FF_Smooth` + `FF_GeometryNodesSurface` + `Boolean`) da:

| | verts | polys |
|---|---|---|
| Ruta del addon | **538.437** | **1.071.001** |
| Mi prototipo | 689.917 | 1.375.747 |

La diferencia viene de cómo se arma/valida la malla antes de los modificadores.
Hay que replicar exactamente lo que hace `swap_object_mesh_data_geometry`
(incluye transferencia de vertex groups, UV maps y color attributes, y el orden
`clear_geometry → from_pydata → _set_mesh_smoothness`).

---

## 7. Criterios de aceptación

1. **Malla evaluada idéntica**: en el frame 402, `verts=538.437` y `polys=1.071.001`.
2. **Imagen idéntica**: PSNR ≥ **44 dB** contra la ruta actual en los frames 402, 500 y 1200
   (44 dB es la referencia de determinismo medida: GPU vs CPU misma ruta).
3. **Alpha intacto**: el PNG sigue siendo RGBA con `film_transparent=True`; diferencia de
   canal alpha media ≤ 0,1.
4. **Velocidad**: ≤ **5 s/frame** a 1920×1080, 128 spp, en la misma máquina (RTX 4090 + OptiX).
5. **Sin cambios de calidad**: no tocar samples, bounces, caustics, materiales ni cámara.

---

## 8. Cómo probar

```bash
B="C:/Users/Tolch/blender-portable/blender-5.1.2-windows-x64/blender.exe"
"$B" --background "D:/Proyectos_Activos/2026-11-16 YPF/Blender/ocean_motia_v8_RENDER.blend" \
     -o "D:/Proyectos_Activos/2026-11-16 YPF/Render/_test/x" -s 402 -e 402 -a
```

PSNR entre dos PNG:

```bash
ffmpeg -i a.png -i b.png -lavfi psnr -f null -
```

Referencias ya renderizadas para comparar:
- `Render\_test\gpu\g0402.png` — ruta del addon, frame 402 (válida)
- `Render\_test\ctrl\run1.png` / `run2.png` — control de determinismo (71,7 dB)

---

## 9. Alternativa evaluada y descartada

Exportar la animación a **Alembic** y renderizar con `MeshSequenceCache` (sin Python).
Se probó: con la malla final reproduce el agua (PSNR 34,7 dB) y renderiza en 4,7 s/frame.
**Pero el export cuesta 26 s/frame** (el addon igual debe importar la malla para exportarla):
8,9 h de export + 1,6 h de render = 10,5 h, contra 7,0 h del render directo. No conviene.

---

## 10. Riesgos y cuidados

- **No tocar el `.blend` original** (`ocean_motia_v8_OK.blend`). Trabajar sobre `_RENDER.blend`.
- El addon es **GPL-3.0**: modificarlo para uso interno es válido; no redistribuir el binario.
  Si se parchea, versionar el parche contra la versión exacta **1.8.6**, porque una actualización
  del addon lo pisa.
- **Backup del addon** antes de tocarlo (copiar la carpeta `flip_fluids_addon`).
- Cualquier cambio debe validarse con los 3 criterios de imagen (malla, PSNR, alpha) en
  **al menos 3 frames distintos** antes de lanzar un batch largo.
- El render actual está corriendo y es reanudable (`Render\STOP` lo detiene); cualquier prueba
  debe hacerse sobre otra copia de la escena para no interrumpirlo.
