#!/bin/bash
# Construye el AppImage de Linux: Python 3.12 + llama.cpp (CUDA 12.9, Vulkan y CPU)
# + todas las dependencias + driver NVIDIA para la live de Ubuntu 24.04. Autónomo.
#
#   empaquetar/construir-linux.sh            → dist/Cerebro-x86_64.AppImage
#   NVIDIA_KERNELS="6.17.0-14-generic" empaquetar/construir-linux.sh
#
# Necesita: bash, python3 (>=3.10) con pip, curl. No instala nada en el sistema.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
SAL="${SALIDA:-$RAIZ/dist}"
APPDIR="$SAL/Cerebro.AppDir"
CACHE="${CACHE:-$HOME/.cache/cerebro-build}"
KERNELS="${NVIDIA_KERNELS:-6.17.0-14-generic 7.0.0-14-generic}"
mkdir -p "$SAL" "$CACHE"

# Entorno de construcción aislado (solo zstandard para leer paquetes conda)
[ -x "$CACHE/venv/bin/python" ] || python3 -m venv "$CACHE/venv"
"$CACHE/venv/bin/pip" install -q --upgrade pip zstandard
PY="$CACHE/venv/bin/python"

echo "== 1/6 Python 3.12 y llama.cpp CUDA desde conda-forge"
rm -rf "$APPDIR"
"$PY" "$RAIZ/empaquetar/conda_paquetes.py" --cache "$CACHE/conda" --destino "$APPDIR/usr" \
  --fijar python=3.12 --fijar cuda-version=12.9 --fijar cuda-nvrtc=12.9 "llama.cpp=9923=cuda129*" python libgomp
"$PY" "$RAIZ/empaquetar/conda_paquetes.py" --cache "$CACHE/conda" --destino "$CACHE/stub" \
  --fijar cuda-version=12.9 --fijar cuda-driver-dev_linux-64=12.9 "cuda-driver-dev=12.9" >/dev/null
ln -sf libgomp.so.1.0.0 "$APPDIR/usr/lib/libgomp.so.1"  # el enlace lo pone _openmp_mutex, que no se usa
mkdir -p "$APPDIR/usr/lib/cuda-stub"
cp "$CACHE/stub/targets/x86_64-linux/lib/stubs/libcuda.so" "$APPDIR/usr/lib/cuda-stub/libcuda.so.1"

# Vulkan: se usa el cargador del sistema (encuentra Mesa RADV/ANV y el de NVIDIA); el incluido solo si falta
mkdir -p "$APPDIR/usr/lib/vulkan-respaldo"
mv "$APPDIR"/usr/lib/libvulkan.so* "$APPDIR/usr/lib/vulkan-respaldo/"
echo "   llama.cpp oficial con ROCm para AMD"
"$PY" "$RAIZ/empaquetar/llama_oficial.py" --patron 'bin-ubuntu-rocm-[\d.]+-x64\.(tar\.gz|zip)$' --destino "$APPDIR/usr/rocm" \
  || echo "   (aviso: sin versión ROCm; las AMD usarán Vulkan)"

echo "== 2/6 Dependencias de Python (ruedas para cp312 / manylinux)"
SP="$APPDIR/usr/lib/python3.12/site-packages"
PLAT=""
for p in manylinux_2_39 manylinux_2_35 manylinux_2_34 manylinux_2_31 manylinux_2_28 manylinux_2_27 manylinux_2_24 manylinux_2_17 manylinux2014 manylinux1 linux; do
  PLAT="$PLAT --platform ${p}_x86_64"
done
REQ="${REQUISITOS:-$RAIZ/empaquetar/requisitos-fijados.txt}"
[ -f "$REQ" ] || REQ="$RAIZ/requirements.txt"
mkdir -p "$CACHE/ruedas"
for intento in 1 2 3 4 5 6 7 8 9 10; do
  if "$PY" -m pip install -q --target "$SP" --python-version 3.12 --implementation cp --abi cp312 --abi abi3 --abi none \
      $PLAT --platform any --only-binary=:all: --find-links "$CACHE/ruedas" -r "$REQ" 2>"$CACHE/pip.err"; then break; fi
  FALTA=$(grep -o "No matching distribution found for [^ ]*" "$CACHE/pip.err" | awk '{print $NF}' || true)
  [ -n "$FALTA" ] || { cat "$CACHE/pip.err"; exit 1; }
  echo "   $FALTA solo existe como código fuente: creando rueda"
  "$PY" -m pip wheel -q --no-deps "$FALTA" -w "$CACHE/ruedas"
done

echo "== 3/6 Quitando lo innecesario"
U="$APPDIR/usr"
find "$U/bin" -mindepth 1 ! -name llama-server ! -name python3.12 ! -name python3 ! -name python -delete
rm -rf "$U"/{include,share/doc,share/man,share/info,compiler_compat,x86_64-conda-linux-gnu,Library,info,sbin,conda-meta} \
  "$U/targets/x86_64-linux/include" "$U/lib/pkgconfig" "$U/lib/cmake" \
  "$U"/lib/python3.12/{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3,pydoc_data,__pycache__} \
  "$U"/lib/python3.12/config-3.12-x86_64-linux-gnu "$U"/lib/python3.12/lib-dynload/_tkinter*
find "$U/lib" -maxdepth 1 -name "libllama-*-impl.so" ! -name "libllama-server-impl.so" -delete
find "$U/lib" "$U/targets" -name "*.a" -delete
find "$SP" -name "__pycache__" -type d -prune -exec rm -rf {} +

echo "== 4/6 Aplicación"
mkdir -p "$APPDIR/app" "$APPDIR/nvidia"
cp -r "$RAIZ/cerebro" "$RAIZ/web" "$RAIZ/recetas" "$RAIZ/config.yaml" "$APPDIR/app/"
find "$APPDIR/app" -name "__pycache__" -type d -prune -exec rm -rf {} +
cp "$RAIZ/empaquetar/linux/AppRun" "$RAIZ/empaquetar/linux/cerebro.desktop" "$APPDIR/"
cp "$RAIZ"/docs/*.pdf "$APPDIR/"; cp "$RAIZ/web/icono-512.png" "$APPDIR/cerebro.png"; cp "$RAIZ/web/icono-512.png" "$APPDIR/.DirIcon"
cp "$RAIZ/empaquetar/nvidia/"*.sh "$RAIZ/empaquetar/nvidia/nvidia_debs.py" "$APPDIR/nvidia/"
chmod +x "$APPDIR/AppRun" "$APPDIR/nvidia/"*.sh

echo "== 5/6 Driver NVIDIA sin conexión para: $KERNELS"
python3 -I "$RAIZ/empaquetar/nvidia/nvidia_debs.py" --destino "$APPDIR/nvidia/debs" $KERNELS || echo "   (aviso: algún kernel sin driver)"

echo "== 6/6 Empaquetando"
if [ -z "${APPIMAGETOOL:-}" ] && command -v appimagetool >/dev/null; then APPIMAGETOOL=appimagetool; fi
if [ -z "${APPIMAGETOOL:-}" ]; then
  if curl -fsSL -o "$CACHE/appimagetool" \
      https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage; then
    chmod +x "$CACHE/appimagetool"; APPIMAGETOOL="$CACHE/appimagetool"
  fi
fi
if [ -n "${APPIMAGETOOL:-}" ]; then
  ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" --comp zstd -n "$APPDIR" "$SAL/Cerebro-x86_64.AppImage"
  echo "Listo: $SAL/Cerebro-x86_64.AppImage"
else
  tar -C "$SAL" -cf - Cerebro.AppDir | zstd -T0 -10 -o "$SAL/Cerebro-linux-x86_64.tar.zst"
  echo "Sin appimagetool: queda la carpeta lista en $SAL/Cerebro-linux-x86_64.tar.zst (se arranca con ./AppRun)"
fi
