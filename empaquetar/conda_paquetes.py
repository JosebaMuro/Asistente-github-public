"""Descarga y desempaqueta paquetes de conda-forge sin instalar conda ni ejecutar nada.

Sirve para meter en el paquete de Cerebro un Python y un llama.cpp con CUDA ya
compilados, con todas sus bibliotecas, para que funcione sin conexión.

    python conda_paquetes.py --plataforma linux-64 --destino AppDir/usr \
        --fijar python=3.12 --fijar cuda-version=12.9 python llama.cpp=*cuda129*

Resolución deliberadamente simple: para cada nombre toma la versión más alta que
cumpla la fijación (o la que pida otro paquete con ==), y sigue las dependencias.
"""
import argparse
import fnmatch
import io
import json
import os
import re
import sys
import tarfile
import urllib.request
import zipfile

import zstandard

CANAL = "https://conda.anaconda.org/conda-forge"
# Dependencias que no hacen falta para ejecutar (compiladores, cabeceras, JIT de NVCC)
IGNORAR = {"cuda-nvcc-tools", "cuda-nvcc-dev_linux-64", "cuda-nvcc-impl", "cuda-crt-tools", "cuda-nvvm-tools",
           "python_abi", "vc", "vc14_runtime", "vs2015_runtime", "ucrt", "_openmp_mutex", "_libgcc_mutex",
           "tzdata", "pip", "setuptools", "wheel", "tk", "libtk", "libtcl", "fontconfig", "xorg-libx11", "xorg-libxext",
           "xorg-libxrender", "xorg-libxrandr", "libxcb", "libfreetype"}


def clave_version(v):
    partes = re.split(r"[._-]", str(v))
    k = [(0, int(p)) if p.isdigit() else (-1, p) for p in partes]
    while len(k) > 1 and k[-1] == (0, 0):
        k.pop()  # 1.2.0 == 1.2
    return k


def repodata(plataforma, cache):
    ruta = os.path.join(cache, f"repodata-{plataforma}.json.zst")
    if not os.path.exists(ruta):
        print("descargando índice", plataforma, file=sys.stderr)
        urllib.request.urlretrieve(f"{CANAL}/{plataforma}/repodata.json.zst", ruta)
    with open(ruta, "rb") as f:
        datos = zstandard.ZstdDecompressor().stream_reader(f).read()
    rd = json.loads(datos)
    paquetes = {}
    for seccion in ("packages", "packages.conda"):
        for archivo, info in rd.get(seccion, {}).items():
            info["archivo"] = archivo
            info["subdir"] = plataforma
            paquetes.setdefault(info["name"], []).append(info)
    return paquetes


def cumple(info, patron):
    """patron: 'version' o 'version=build_glob' estilo conda simplificado."""
    if not patron or patron == "*":
        return True
    ver, _, build = patron.partition("=")
    if ver and ver != "*":
        if not (info["version"] == ver or info["version"].startswith(ver + ".") or fnmatch.fnmatch(info["version"], ver)):
            return False
    if build and not fnmatch.fnmatch(info["build"], build):
        return False
    return True


def elegir(nombre, candidatos, patron):
    validos = [c for c in candidatos if cumple(c, patron)]
    if not validos:
        raise SystemExit(f"no hay {nombre} que cumpla {patron!r}")
    # preferir .conda sobre .tar.bz2 a igualdad
    return max(validos, key=lambda c: (clave_version(c["version"]), c.get("build_number", 0), c["archivo"].endswith(".conda"), c.get("timestamp", 0)))


def _ver_ok(v, spec):
    """Comprueba una versión contra una especificación conda: '>=1.2,<2', '1.2.*', '==3', '1.2|1.3'."""
    if not spec or spec == "*":
        return True
    if "|" in spec:
        return any(_ver_ok(v, s) for s in spec.split("|"))
    kv = clave_version(v)
    for parte in spec.split(","):
        m = re.fullmatch(r"(>=|<=|==|!=|>|<|~=)?\s*([^\s]+)", parte.strip())
        if not m:
            continue
        op, x = m.group(1) or "", m.group(2)
        if x.endswith(".*") or x.endswith("*"):
            base = x.rstrip("*").rstrip(".")
            if op in ("", "==") and not (v == base or v.startswith(base + ".")):
                return False
            if op == "!=" and (v == base or v.startswith(base + ".")):
                return False
            continue
        kx = clave_version(x.replace("a0", "").rstrip("."))
        if op == ">=" and not kv >= kx: return False
        if op == ">" and not kv > kx: return False
        if op == "<" and not kv < kx: return False
        if op == "<=" and not kv <= kx: return False
        if op in ("==", "") and not (v == x or (op == "" and v.startswith(x + "."))): return False
        if op == "!=" and v == x: return False
    return True


def _restricciones(elegidos):
    r = {}
    for info in elegidos.values():
        for dep in info.get("depends", []):
            partes = dep.split()
            if len(partes) > 1:
                r.setdefault(partes[0], []).append(partes[1])
    return r


def resolver(indices, pedidos, fijados):
    def candidatos(nombre):
        return [c for idx in indices for c in idx.get(nombre, [])]

    def mejor(nombre, specs):
        validos = [c for c in candidatos(nombre)
                   if cumple(c, fijados.get(nombre, pedidos.get(nombre, ""))) and all(_ver_ok(c["version"], s) for s in specs)]
        if not validos:
            return None
        return max(validos, key=lambda c: (clave_version(c["version"]), c.get("build_number", 0), c["archivo"].endswith(".conda"), c.get("timestamp", 0)))

    elegidos = {}
    for _ronda in range(10):
        cambios = False
        restr = _restricciones(elegidos)
        pendientes = list(pedidos) + [d.split()[0] for i in elegidos.values() for d in i.get("depends", [])]
        vistos = set()
        for nombre in pendientes:
            if nombre in vistos or nombre in IGNORAR or nombre.startswith("__"):
                continue
            vistos.add(nombre)
            if not candidatos(nombre):
                print(f"  aviso: {nombre} no existe, se omite", file=sys.stderr)
                continue
            actual = elegidos.get(nombre)
            if actual and all(_ver_ok(actual["version"], s) for s in restr.get(nombre, [])):
                continue
            info = mejor(nombre, restr.get(nombre, []))
            if info is None:
                print(f"  aviso: nada de {nombre} cumple {restr.get(nombre)}; uso el más nuevo", file=sys.stderr)
                info = mejor(nombre, [])
            if actual is not info:
                elegidos[nombre] = info
                cambios = True
        # quitar lo que ya nadie pide
        necesarios = set(pedidos) | {d.split()[0] for i in elegidos.values() for d in i.get("depends", [])}
        for n in list(elegidos):
            if n not in necesarios:
                del elegidos[n]
                cambios = True
        if not cambios:
            break
    return elegidos


def descargar(info, cache):
    ruta = os.path.join(cache, info["archivo"])
    if not os.path.exists(ruta) or os.path.getsize(ruta) != info.get("size", -1):
        print(f"  ↓ {info['archivo']} ({info.get('size', 0) // 1048576} MB)", file=sys.stderr)
        urllib.request.urlretrieve(f"{CANAL}/{info['subdir']}/{info['archivo']}", ruta + ".part")
        os.replace(ruta + ".part", ruta)
    return ruta


def _extraer_tar(tf, destino):
    for m in tf.getmembers():
        if m.name.startswith("/") or ".." in m.name.split("/"):
            continue  # nada fuera del destino
        tf.extract(m, destino, filter="tar")


def desempaquetar(ruta, destino):
    if ruta.endswith(".conda"):
        with zipfile.ZipFile(ruta) as z:
            for n in z.namelist():
                if n.startswith("pkg-") and n.endswith(".tar.zst"):
                    datos = zstandard.ZstdDecompressor().stream_reader(z.open(n)).read()
                    with tarfile.open(fileobj=io.BytesIO(datos)) as tf:
                        _extraer_tar(tf, destino)
    else:
        with tarfile.open(ruta, "r:bz2") as tf:
            _extraer_tar(tf, destino)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plataforma", default="linux-64")
    ap.add_argument("--destino", required=True)
    ap.add_argument("--cache", default=os.path.expanduser("~/.cache/cerebro-conda"))
    ap.add_argument("--fijar", action="append", default=[], help="nombre=version[=build]")
    ap.add_argument("--incluir", action="append", default=[], help="no ignorar este paquete (p. ej. vc14_runtime en Windows)")
    ap.add_argument("--lista", action="store_true", help="solo mostrar qué se descargaría")
    ap.add_argument("paquetes", nargs="+", help="nombre o nombre=version[=build]")
    a = ap.parse_args(argv)
    os.makedirs(a.cache, exist_ok=True)
    IGNORAR.difference_update(a.incluir)
    indices = [repodata(a.plataforma, a.cache), repodata("noarch", a.cache)]
    fijados = dict(f.split("=", 1) for f in a.fijar)
    pedidos = {}
    for p in a.paquetes:
        n, _, pat = p.partition("=")
        pedidos[n] = pat
    elegidos = resolver(indices, pedidos, fijados)
    total = sum(i.get("size", 0) for i in elegidos.values())
    for n in sorted(elegidos):
        i = elegidos[n]
        print(f"{n:32} {i['version']:18} {i['build']:28} {i.get('size', 0) // 1048576:5} MB")
    print(f"total {total // 1048576} MB en {len(elegidos)} paquetes")
    if a.lista:
        return
    os.makedirs(a.destino, exist_ok=True)
    for i in elegidos.values():
        desempaquetar(descargar(i, a.cache), a.destino)
    print("listo en", a.destino)


if __name__ == "__main__":
    main()
