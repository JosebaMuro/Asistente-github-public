#!/bin/bash
# Construye la versión portable de Windows (carpeta + zip) desde Linux o desde CI,
# sin ejecutar nada de Windows: Python oficial (NuGet), ruedas win_amd64 y
# llama.cpp CUDA 12.9 + Vulkan de conda-forge con solo las DLL que usa.
#   empaquetar/construir-windows.sh   → dist/Cerebro-windows-x64.zip
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
SAL="${SALIDA:-$RAIZ/dist}"; W="$SAL/Cerebro"
CACHE="${CACHE:-$HOME/.cache/cerebro-build}"
PYVER="${PYVER:-3.12.10}"
mkdir -p "$SAL" "$CACHE"
[ -x "$CACHE/venv/bin/python" ] || python3 -m venv "$CACHE/venv"
"$CACHE/venv/bin/pip" install -q --upgrade pip zstandard pefile
PY="$CACHE/venv/bin/python"
rm -rf "$W"; mkdir -p "$W"

echo "== 1/4 Python $PYVER para Windows"
[ -f "$CACHE/python-$PYVER.nupkg" ] || curl -fsSL -o "$CACHE/python-$PYVER.nupkg" "https://api.nuget.org/v3-flatcontainer/python/$PYVER/python.$PYVER.nupkg"
"$PY" - "$CACHE/python-$PYVER.nupkg" "$W/python" <<'PYEOF'
import os, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
for n in z.namelist():
    if n.startswith("tools/") and not n.endswith("/") and ".." not in n:
        t = os.path.join(sys.argv[2], n[6:]); os.makedirs(os.path.dirname(t), exist_ok=True)
        open(t, "wb").write(z.read(n))
PYEOF

echo "== 2/4 Dependencias (ruedas win_amd64)"
mkdir -p "$CACHE/ruedas"
for intento in 1 2 3 4 5 6 7 8; do
  if "$PY" -m pip install -q --target "$W/python/Lib/site-packages" --python-version 3.12 --implementation cp \
      --abi cp312 --abi abi3 --abi none --platform win_amd64 --platform any --only-binary=:all: --no-deps \
      --find-links "$CACHE/ruedas" -r "$RAIZ/empaquetar/requisitos-windows.txt" 2>"$CACHE/pip.err"; then break; fi
  FALTA=$(grep -o "No matching distribution found for [^ ]*" "$CACHE/pip.err" | awk '{print $NF}' || true)
  [ -n "$FALTA" ] || { cat "$CACHE/pip.err"; exit 1; }
  "$PY" -m pip wheel -q --no-deps "$FALTA" -w "$CACHE/ruedas"
done
find "$W/python" -name "__pycache__" -type d -prune -exec rm -rf {} +
rm -rf "$W/python/Lib/test" "$W/python/Lib/idlelib" "$W/python/Lib/tkinter" "$W/python/Lib/turtledemo" "$W/python/include" "$W/python/libs"

echo "== 3/4 llama.cpp CUDA 12.9 + Vulkan"
rm -rf "$CACHE/win-conda"
"$PY" "$RAIZ/empaquetar/conda_paquetes.py" --plataforma win-64 --cache "$CACHE/conda" --destino "$CACHE/win-conda" \
  --incluir vc14_runtime --fijar cuda-version=12.9 --fijar cuda-nvrtc=12.9 "llama.cpp=9923=cuda129*"
mkdir -p "$W/motor/cuda"
"$PY" - "$CACHE/win-conda" "$W/motor/cuda" <<'PYEOF'
# Copia llama-server.exe y solo las DLL que de verdad carga (cierre de importaciones PE)
import os, shutil, sys, pefile
origen, destino = sys.argv[1], sys.argv[2]
todos = {}
for d in (os.path.join(origen, "Library", "bin"), origen):
    for f in os.listdir(d):
        if f.lower().endswith((".dll", ".exe")):
            todos.setdefault(f.lower(), os.path.join(d, f))
pendientes, vistos = ["llama-server.exe"], set()
while pendientes:
    n = pendientes.pop()
    if n in vistos: continue
    vistos.add(n)
    pe = pefile.PE(todos[n], fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"], pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) + getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []):
        d = e.dll.decode().lower()
        if d in todos: pendientes.append(d)
for n in vistos: shutil.copy2(todos[n], destino)
print(len(vistos), "archivos")
PYEOF

echo "== 3b/4 llama.cpp oficial para AMD: ROCm (HIP) y Vulkan (cualquier GPU)"
"$PY" "$RAIZ/empaquetar/llama_oficial.py" --patron 'bin-win-(rocm|hip)[-\w.]*-x64\.zip$' --destino "$W/motor/rocm" \
  || echo "   (aviso: sin versión ROCm; las AMD usarán Vulkan)"
"$PY" "$RAIZ/empaquetar/llama_oficial.py" --patron 'bin-win-vulkan-x64\.zip$' --destino "$W/motor/vulkan"

echo "== 4/4 Aplicación y lanzadores"
cp -r "$RAIZ/cerebro" "$RAIZ/web" "$RAIZ/recetas" "$RAIZ/config.yaml" "$W/"
find "$W/cerebro" -name "__pycache__" -type d -prune -exec rm -rf {} +
cp "$RAIZ"/empaquetar/windows/*.bat "$RAIZ"/empaquetar/windows/*.cmd "$RAIZ"/empaquetar/windows/LEEME.txt "$RAIZ"/docs/*.pdf "$W/"
(cd "$SAL" && rm -f Cerebro-windows-x64.zip && "$PY" -c "
import os, zipfile
with zipfile.ZipFile('Cerebro-windows-x64.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
    for r, _, fs in os.walk('Cerebro'):
        for f in fs: z.write(os.path.join(r, f))
")
echo "Listo: $SAL/Cerebro-windows-x64.zip"
