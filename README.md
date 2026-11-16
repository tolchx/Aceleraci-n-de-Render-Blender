# FLIP Fast Render (`flip_fast_render`)

Addon optimizado para **Blender 4.5+ / 5.1+** que acelera el renderizado de cachés de **FLIP Fluids** (`.bobj`, `.wwp`, `.wwi`, `.wwf`, `.ffp3`) reemplazando el cuello de botella de reconstrucción de malla en Python (`from_pydata` + `shade_flat`) por carga binaria directa con **NumPy + `foreach_set`**, sin perder calidad ni modificar la escena.

---

## Instalación rápida con Antigravity (IA + Blender MCP)

Si solo tenés instalados **Blender** y **Antigravity**, copiá y pegale este prompt a tu agente con el link de este repositorio:

```text
Cloná o leé este repo: https://github.com/tolchx/Aceleraci-n-de-Render-Blender
Seguí las instrucciones de AGENTS.md:
1. Detectá mi instalación de Blender (4.5+ / 5.x).
2. Instalá y configurá el MCP de Blender (mcp-for-blender) si no lo tengo configurado.
3. Instalá y habilitá el addon flip_fast_render sin tocar mi escena original.
4. Corré el smoke_test.py y luego probalo sobre mi archivo .blend de forma no destructiva, comparando tiempo por frame y PSNR.
```

---

## Qué optimiza

1. **Carga binaria directa con `numpy.fromfile`** (`flip_fast_render/fast_io.py`): elimina `struct.unpack_from` y `list(zip(...))` por frame.
2. **Armado de malla vía `foreach_set` con buffers reutilizables** (`flip_fast_render/mesh_builder.py`): reemplaza `from_pydata` incluyendo `loop_total = 3`, `update(calc_edges=True)` y `update_transforms()`, obteniendo exactamente la misma malla evaluada que el addon original.
3. **Sombreado y atributos sin overhead**: en Blender 5.1, una malla limpia tras `clear_geometry()` ya es suave por defecto cuando no existe el atributo `sharp_face`, evitando escribir millones de booleanos por frame.
4. **Caché de metadata y omisión inteligente de `T71908`**: evita evaluar el depsgraph o reescribir `flip_time_scale` / `flip_world_scale` en el dominio cuando no hay animación ni drivers.
5. **Arquitectura dual**:
   - **Modo Bridge** (`bridge.py`): si `flip_fluids_addon` está activo, acelera sus métodos en memoria sin modificar los archivos originales del addon.
   - **Modo Standalone** (`standalone.py`): si `flip_fluids_addon` está deshabilitado, lee la configuración guardada en `bl_system_properties_get()['flip_fluid']` y carga la caché directamente.

---

## Benchmarks medidos (escena `ocean_motia_v8_RENDER.blend`, 1920×1080 Cycles OptiX 128 spp, RTX 4090)

| Configuración | Frames | Tiempo / frame (régimen) | Malla eval (f402) | PSNR RGB | Alpha MAD (0–255) |
|---|---|---|---|---|---|
| **Original FLIP Fluids 1.8.6** | 402–403 (solo) / 418 (prod) | `21.61 s` (403) · `25.28 s` (prod) | `538.437` / `1.071.001` | Ref | Ref |
| **`flip_fast_render` Bridge (`FLOAT` seguro)** | 402–406 (solo continuo) | **`14.86 s`** (`403: 14.09 s`) | `538.437` / `1.071.001` | **96.48 – 97.20 dB** | **0.000000** |
| **`flip_fast_render` Bridge (multi-rango)** | 402, 500, 1200 (cold start) | `13.71 – 15.46 s` | `538.437` / `1.071.001` | **73.40 – 74.39 dB** | **≤ 0.000008** |
| **`flip_fast_render` Standalone** | 402, 500, 1200 (cold start) | `12.46 – 16.56 s` | `538.437` / `1.071.001` | **53.66 – 73.35 dB** | **≤ 0.001984** |
| Bridge con solver `MANIFOLD` *(desactivado por defecto)* | 402–406 (solo continuo) | `11.22 s` (`406: 10.48 s`) | `538.437` / `1.071.001` | `16.61 dB` en f405 | `5.71` en f405 |

> **Nota crítica (`MANIFOLD` vs `FLOAT`):** en el frame `405`, `000405.bobj` contiene 4 aristas non-manifold que hacen que el solver `MANIFOLD` de Blender omita el recorte (`Cannot execute, non-manifold inputs`). Por seguridad, `use_manifold_boolean` viene **`False` por defecto** (`FLOAT`), garantizando **97.15 dB** incluso en frames con topología no-manifold.

- Documentación visual para compartir al equipo: [REPORTE_TEAM_FLIP_FAST_RENDER.pdf](REPORTE_TEAM_FLIP_FAST_RENDER.pdf)
- Reporte técnico original del diagnóstico: [REPORTE_OPTIMIZACION_FLIP.md](REPORTE_OPTIMIZACION_FLIP.md)

---

## Instalación manual (para el equipo)

### Opción 1: Desde Blender UI (recomendado)
1. Descargar [dist/flip_fast_render.zip](dist/flip_fast_render.zip).
2. En Blender: **`Edit` → `Preferences...` → `Get Extensions` (o `Add-ons`) → menú `⌄` → `Install from Disk...`**.
3. Seleccionar `flip_fast_render.zip`, verificar que **`FLIP Fast Render`** quede habilitado y guardar preferencias (**`Save Preferences`**).

### Opción 2: Por script (instalación + smoke test)
```bash
python scripts/install_extension.py --install --enable --blender "<RUTA_A_BLENDER>"
python scripts/smoke_test.py --blender "<RUTA_A_BLENDER>"
```

### Opción 3: Validación completa sobre un `.blend` real
```bash
python scripts/verify_acceptance.py \
  --blender "<RUTA_A_BLENDER>" \
  --blend "<RUTA_A_TU_ESCENA.blend>" \
  --frames 402,500,1200
```

### Opción 4: Parche directo sobre `flip_fluids_addon` 1.8.6 (con backup automático)
```bash
python scripts/patch_flip_fluids_186.py --dry-run
python scripts/patch_flip_fluids_186.py
```

---

## Estructura del repositorio

- `flip_fast_render/` — Extensión/addon de Blender (`fast_io.py`, `mesh_builder.py`, `bridge.py`, `standalone.py`, `scene_optimizer.py`, `ui.py`, `__init__.py`, `blender_manifest.toml`)
- `dist/flip_fast_render.zip` — Paquete listo para *Install from Disk*
- `scripts/install_extension.py` — Instalador/empaquetador multiplataforma
- `scripts/smoke_test.py` — Smoke test sintético en Blender (sin `.blend` externo)
- `scripts/verify_acceptance.py` — Suite de comparación (malla evaluada, PSNR, alpha MAD y tiempos)
- `scripts/patch_flip_fluids_186.py` — Parcheador opcional en disco para FLIP Fluids 1.8.6
- `AGENTS.md` — Guía paso a paso para agentes IA (Antigravity + Blender MCP)
- `REPORTE_TEAM_FLIP_FAST_RENDER.pdf` — Reporte ejecutivo en PDF con capturas

---

## Roadmap futuro (próxima etapa de optimización)

Mediciones identificadas para bajar aún más de `14.9 s/frame` hacia `~3.5–6.0 s/frame` cuando el proyecto lo habilite:
1. **Boolean `AUTO`**: chequeo vectorizado de aristas non-manifold en NumPy (`~0.20 s/frame` medidos) para usar `MANIFOLD` en frames cerrados y caer a `FLOAT` solo cuando haya aristas non-manifold (`~11.4 s/frame` est.).
2. **Desactivar Tiling + Denoise en GPU**: en `ocean_motia_v8_RENDER.blend`, `use_auto_tile=True` (`tile_size=512`) y `OPENIMAGEDENOISE` con `denoising_use_gpu=False` consumían ~5.4 s en CPU/disco por frame (`~9.5–10.0 s/frame` est. solo activando GPU denoise + 1 tile en VRAM).
3. **2 instancias paralelas en GPU de 24 GB**: cada instancia usa ~8.5 GB de VRAM y ~34 % de CPU; correr pares/impares en paralelo aprovecha los 15.5 GB libres.
4. **Pre-recorte de `Boolean` estático**: eliminar el modificador `Boolean` por frame pre-recortando la caché `.bobj` fuera del render loop.
