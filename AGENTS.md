# AGENTS.md — Playbook para Antigravity / Agentes IA

Si un usuario te compartió este repositorio para instalar y probar `flip_fast_render` en su equipo (teniendo únicamente **Blender 4.5+ / 5.x** y **Antigravity**), seguí estos pasos en orden, sin modificar los archivos `.blend` originales ni sobrescribir renders de producción.

---

## 1. Descubrir Blender en el equipo del usuario

Buscar el ejecutable de Blender según el sistema operativo:
- **Windows**: `where blender`, `C:\Program Files\Blender Foundation\Blender *\blender.exe`, o instalaciones portables en `%USERPROFILE%`.
- **macOS**: `/Applications/Blender.app/Contents/MacOS/Blender`.
- **Linux**: `which blender` o `/usr/local/bin/blender`.

Verificar que la versión sea `>= 4.5.0` (`blender --version`).

---

## 2. Instalar `flip_fast_render` (sin tocar `flip_fluids_addon`)

El addon tiene **arquitectura dual**:
- **Bridge Mode**: si `flip_fluids_addon` está instalado y activo, lo acelera en memoria sin tocar sus archivos en disco.
- **Standalone Mode**: si `flip_fluids_addon` no está instalado/habilitado, lee los ajustes desde `bl_system_properties_get()['flip_fluid']` y carga `.bobj` / `.wwp` con NumPy + `foreach_set`.

Comandos (reemplazar `<BLENDER_EXE>` por la ruta detectada):

```bash
# 1. Instalar la extensión en las carpetas de usuario detectadas y habilitarla
python scripts/install_extension.py --install --enable --blender "<BLENDER_EXE>"

# 2. Smoke test sintético autocontenido (no requiere un .blend externo)
python scripts/smoke_test.py --blender "<BLENDER_EXE>"
```

Si `python` del sistema no está en `PATH`, usar el Python embebido dentro de la carpeta de Blender (ej. `5.1/python/bin/python.exe` en Windows o `5.1/python/bin/python3.11` en Linux/macOS).

---

## 3. (Opcional) Instalar Blender MCP (`mcp-for-blender`) para control en vivo

Si el usuario pide controlar Blender desde Antigravity vía MCP:

1. **Verificar `uv` / `uvx`**: ejecutar `uvx --version` (si falta, instalar `uv` oficial desde Astral).
2. **Registrar el servidor MCP** en `~/.gemini/config/mcp_config.json`:
   - **Windows**:
     ```json
     {
       "mcpServers": {
         "blender": {
           "command": "cmd",
           "args": ["/c", "uvx", "mcp-for-blender"]
         }
       }
     }
     ```
   - **macOS / Linux**:
     ```json
     {
       "mcpServers": {
         "blender": {
           "command": "uvx",
           "args": ["mcp-for-blender"]
         }
       }
     }
     ```
3. **Instalar el addon socket de `mcp-for-blender` en Blender**: descargar `addon.py` del repositorio oficial `ahujasid/mcp-for-blender`, instalarlo en Blender (`bpy.ops.preferences.addon_install(...)` + `addon_enable` + `save_userpref()`), y recordar al usuario iniciar el servidor en el panel `N` → **MCP for Blender** dentro de la vista 3D.

---

## 4. Probar y validar sobre el proyecto `.blend` del usuario

Antes de tocar o lanzar un render de producción:
- **Nunca modificar el `.blend` original** ni escribir en la carpeta de salida final.
- Usar `scripts/verify_acceptance.py` apuntando a un directorio temporal (`--out`):

```bash
python scripts/verify_acceptance.py \
  --blender "<BLENDER_EXE>" \
  --blend "<RUTA_AL_PROYECTO.blend>" \
  --frames 1,10,20
```

Criterios mínimos a reportar al usuario:
1. **Malla evaluada idéntica** (vértices y polígonos iguales entre `orig` y `bridge`/`standalone`).
2. **PSNR ≥ 44 dB** en todos los frames probados.
3. **Alpha MAD ≤ 0.1** (escala 0–255).
4. **Regla de seguridad `Boolean`**: mantener `use_manifold_boolean = False` (valor por defecto). Las mallas FLIP ocasionalmente tienen aristas non-manifold (ej. frame 405 del caso de referencia) donde `MANIFOLD` omite el corte y rompe la imagen.
