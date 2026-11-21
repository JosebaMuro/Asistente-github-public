"""Descarga los paquetes mínimos del driver NVIDIA 580 (módulo firmado por Canonical,
firmware GSP, libcuda y nvidia-smi) para un kernel concreto de Ubuntu 24.04.

No instala nada: solo deja los .deb en una carpeta para usarlos luego sin conexión
con activar-nvidia.sh. Funciona con cualquier Python 3 y solo usa la biblioteca estándar.

    python3 nvidia_debs.py --destino debs 6.17.0-14-generic 7.0.0-14-generic
    python3 nvidia_debs.py --destino debs "$(uname -r)"
"""
import argparse
import lzma
import os
import re
import sys
import urllib.request

ARCHIVO = "http://archive.ubuntu.com/ubuntu"
RAMA = "580"
POOL = f"{ARCHIVO}/pool/restricted/n/nvidia-graphics-drivers-{RAMA}/"


def bajar(url):
    pedido = urllib.request.Request(url, headers={"User-Agent": "Debian APT-HTTP/1.3 (cerebro-local)"})
    with urllib.request.urlopen(pedido, timeout=120) as r:
        return r.read()


def indices():
    paquetes = {}
    for bolsillo in ("noble-updates", "noble-security", "noble"):
        for comp in ("restricted", "main"):
            try:
                texto = lzma.decompress(bajar(f"{ARCHIVO}/dists/{bolsillo}/{comp}/binary-amd64/Packages.xz")).decode("utf-8", "replace")
            except Exception as e:  # noqa: BLE001
                print("  aviso:", bolsillo, comp, e, file=sys.stderr)
                continue
            for bloque in texto.split("\n\n"):
                campos = dict(re.findall(r"^([A-Za-z-]+): (.*)$", bloque, re.M))
                if "Package" in campos:
                    paquetes.setdefault(campos["Package"], campos)
    return paquetes


def guardar(url, carpeta):
    nombre = url.rsplit("/", 1)[1]
    ruta = os.path.join(carpeta, nombre)
    if not os.path.exists(ruta):
        print("  ↓", nombre, file=sys.stderr)
        datos = bajar(url)
        with open(ruta + ".part", "wb") as f:
            f.write(datos)
        os.replace(ruta + ".part", ruta)
    return nombre


def del_pool(listado, nombre, version):
    """Elige en el pool el .deb de `nombre` con esa versión de NVIDIA, preferiblemente compilado para 24.04."""
    patron = re.compile(re.escape(nombre) + r"_(" + re.escape(version) + r"-[^_]+)_amd64\.deb")
    opciones = sorted(set(patron.findall(listado)))
    if not opciones:
        return None
    mejores = [o for o in opciones if "24.04" in o] or opciones
    return f"{nombre}_{mejores[-1]}_amd64.deb"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--destino", required=True)
    ap.add_argument("--abierto", default="open", choices=["open", "cerrado"],
                    help="módulo open (recomendado para RTX 20xx en adelante) o el clásico")
    ap.add_argument("kernels", nargs="+")
    a = ap.parse_args(argv)
    print("Leyendo índices de Ubuntu 24.04…", file=sys.stderr)
    idx = indices()
    listado = bajar(POOL).decode("utf-8", "replace")
    fallos = 0
    for k in a.kernels:
        k = k if k.endswith("-generic") else k + "-generic"
        nombre_mod = f"linux-modules-nvidia-{RAMA}-{'open-' if a.abierto == 'open' else ''}{k}"
        info = idx.get(nombre_mod)
        if not info:
            print(f"✗ No hay módulo NVIDIA {RAMA} para el kernel {k}.", file=sys.stderr)
            fallos += 1
            continue
        m = re.search(rf"nvidia-kernel-common-{RAMA} \(>= ([0-9.]+)\)", info.get("Depends", ""))
        if not m:
            print(f"✗ No sé qué versión de NVIDIA pide {nombre_mod}", file=sys.stderr)
            fallos += 1
            continue
        v = m.group(1)
        carpeta = os.path.join(a.destino, k)
        os.makedirs(carpeta, exist_ok=True)
        print(f"Kernel {k}: driver {v}", file=sys.stderr)
        hechos = [guardar(f"{ARCHIVO}/{info['Filename']}", carpeta)]
        for nombre in (f"nvidia-kernel-common-{RAMA}", f"nvidia-firmware-{RAMA}-{v}", f"libnvidia-compute-{RAMA}", f"nvidia-utils-{RAMA}"):
            deb = del_pool(listado, nombre, v)
            if not deb:
                print(f"  ✗ falta {nombre} {v} en el archivo de Ubuntu", file=sys.stderr)
                fallos += 1
                continue
            hechos.append(guardar(POOL + deb, carpeta))
        ocl = idx.get("ocl-icd-libopencl1")
        if ocl:
            hechos.append(guardar(f"{ARCHIVO}/{ocl['Filename']}", carpeta))
        with open(os.path.join(carpeta, "LEEME.txt"), "w") as f:
            f.write(f"Driver NVIDIA {v} para el kernel {k} (Ubuntu 24.04)\n" + "\n".join(hechos) + "\n")
        print(f"✓ {k}: {len(hechos)} paquetes en {carpeta}", file=sys.stderr)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
