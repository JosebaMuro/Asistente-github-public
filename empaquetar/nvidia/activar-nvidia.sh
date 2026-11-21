#!/bin/bash
# Activa la GPU NVIDIA en una sesión live de Ubuntu 24.04 sin conexión a internet.
# Uso (lo llama el AppImage):  ./Cerebro-x86_64.AppImage activar-nvidia
#   $1 = carpeta con debs incluidos en el AppImage   $2 = carpeta extra en el USB
# Solo toca la sesión live (RAM): al apagar no queda nada instalado.
set -u
INCLUIDOS="${1:-$(dirname "$0")}/debs"
USB="${2:-}"
K="$(uname -r)"
verde() { printf '\033[32m%s\033[0m\n' "$*"; }
rojo()  { printf '\033[31m%s\033[0m\n' "$*"; }

if [ "$(id -u)" != 0 ]; then rojo "Hace falta sudo: sudo $0"; exit 1; fi
if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
  verde "La GPU NVIDIA ya está activa:"; nvidia-smi -L; exit 0
fi
if ! lspci 2>/dev/null | grep -qi "nvidia"; then
  rojo "No veo ninguna tarjeta NVIDIA en este equipo. Cerebro usará Vulkan o CPU."; exit 1
fi

echo "Kernel de esta live: $K"
DEBS=""
for d in "$USB/$K" "$INCLUIDOS/$K"; do
  if ls "$d"/linux-modules-nvidia-*"$K"*.deb >/dev/null 2>&1; then DEBS="$d"; break; fi
done
if [ -z "$DEBS" ]; then
  rojo "No tengo el driver para el kernel $K."
  echo "Kernels incluidos: $(ls "$INCLUIDOS" 2>/dev/null | tr '\n' ' ')"
  echo "Solución: con internet ejecuta una vez   ./Cerebro-x86_64.AppImage preparar-usb"
  echo "y guardará en el USB el driver de este kernel para usarlo después sin conexión."
  exit 2
fi
echo "Usando paquetes de: $DEBS"

# 1. Soltar nouveau (el driver libre) si está cargado
if lsmod | grep -q "^nouveau"; then
  echo "Descargando el driver nouveau…"
  if ! modprobe -r nouveau 2>/dev/null; then
    rojo "nouveau está en uso y no se puede descargar."
    echo "Reinicia la live y, en el menú de arranque, pulsa 'e' y añade al final de la línea 'linux':"
    echo "    modprobe.blacklist=nouveau nouveau.modeset=0"
    echo "Luego vuelve a ejecutar esto."
    exit 3
  fi
fi
printf 'blacklist nouveau\noptions nouveau modeset=0\n' > /etc/modprobe.d/cerebro-sin-nouveau.conf

# 2. Instalar los paquetes en la sesión live (sin red)
echo "Instalando driver NVIDIA en la sesión live…"
DEBIAN_FRONTEND=noninteractive dpkg -i --force-depends "$DEBS"/*.deb >/tmp/cerebro-nvidia.log 2>&1 || true
depmod -a "$K"

# 3. Cargar los módulos y crear los dispositivos
if ! modprobe nvidia 2>>/tmp/cerebro-nvidia.log; then
  rojo "No se pudo cargar el módulo nvidia. Detalle en /tmp/cerebro-nvidia.log"
  if mokutil --sb-state 2>/dev/null | grep -qi enabled; then
    echo "Secure Boot está activo: estos módulos van firmados por Canonical y deberían cargar;"
    echo "si no, desactiva Secure Boot en la BIOS del Victus (F10) para la prueba."
  fi
  dmesg | grep -i nvidia | tail -5
  exit 4
fi
modprobe nvidia_uvm 2>/dev/null || true
for n in nvidia nvidia-uvm; do
  M=$(awk -v n="$n" '$2==n{print $1}' /proc/devices)
  [ -z "$M" ] && continue
  if [ "$n" = nvidia ]; then
    [ -e /dev/nvidiactl ] || mknod -m 666 /dev/nvidiactl c "$M" 255
    for g in $(seq 0 $(( $(lspci | grep -Ei "vga|3d|display" | grep -ci nvidia) - 1 ))); do
      [ -e /dev/nvidia$g ] || mknod -m 666 /dev/nvidia$g c "$M" "$g"
    done
  else
    [ -e /dev/nvidia-uvm ] || mknod -m 666 /dev/nvidia-uvm c "$M" 0
    [ -e /dev/nvidia-uvm-tools ] || mknod -m 666 /dev/nvidia-uvm-tools c "$M" 1
  fi
done
ldconfig

if nvidia-smi -L >/dev/null 2>&1; then
  verde "✓ GPU NVIDIA lista:"; nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
  echo "Arranca Cerebro normalmente: ./Cerebro-x86_64.AppImage"
else
  rojo "El módulo cargó pero nvidia-smi no responde. Detalle: /tmp/cerebro-nvidia.log y 'dmesg | grep -i nvidia'"
  exit 5
fi
