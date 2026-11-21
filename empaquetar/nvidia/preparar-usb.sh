#!/bin/bash
# Con internet, deja en el USB todo lo necesario para usar Cerebro sin conexión:
#   - modelos (llama.cpp GGUF, voz sherpa-onnx, embeddings)
#   - driver NVIDIA para el kernel de esta live (y los que pases como argumento)
# Uso:  ./Cerebro-x86_64.AppImage preparar-usb [kernel ...]
set -u
DATOS="$1"; shift || true
AQUI="$(dirname "$(readlink -f "$0")")"
APP="$(dirname "$AQUI")"
echo "Carpeta de datos: $DATOS"
KERNELS="$(uname -r) $*"
echo "1/2 Driver NVIDIA para: $KERNELS"
"$APP/usr/bin/python3.12" -s -P "$AQUI/nvidia_debs.py" --destino "$DATOS/nvidia" $KERNELS || echo "(algún kernel no tiene driver 580 en Ubuntu; ver arriba)"
echo "2/2 Modelos (varios GB, tarda)…"
CEREBRO_OFFLINE=0 "$APP/AppRun" preparar --modelos
echo "Listo. Ya puedes usar Cerebro sin internet desde este USB."
