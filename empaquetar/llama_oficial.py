"""Descarga una compilación oficial de llama.cpp (GitHub ggml-org/llama.cpp) y deja en
`destino` solo llama-server y sus librerías (sin el resto de herramientas llama-*).

    python llama_oficial.py --patron 'bin-win-rocm-[\\d.]+-x64\\.zip$' --destino Cerebro/motor/rocm
Usa GITHUB_TOKEN si existe (evita el límite de peticiones en CI). Solo biblioteca estándar.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30"


def pedir(url, binario=False):
    cab = {"User-Agent": "cerebro-local-build", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN") and "api.github.com" in url:
        cab["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request(url, headers=cab), timeout=600) as r:
        return r.read() if binario else json.loads(r.read())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--patron", required=True)
    ap.add_argument("--destino", required=True)
    a = ap.parse_args(argv)
    patron = re.compile(a.patron)
    for rel in pedir(API):
        activos = [x for x in rel.get("assets", []) if patron.search(x["name"])]
        if activos:
            break
    else:
        sys.exit(f"Ninguna versión reciente de llama.cpp tiene {a.patron}")
    activo = activos[0]
    print(f"llama.cpp {rel['tag_name']}: {activo['name']} ({activo['size'] // 1048576} MB)")
    tmp = tempfile.mkdtemp()
    ruta = os.path.join(tmp, activo["name"])
    with open(ruta, "wb") as f:
        f.write(pedir(activo["browser_download_url"], binario=True))
    ext = os.path.join(tmp, "x")
    if ruta.endswith(".zip"):
        with zipfile.ZipFile(ruta) as z:
            z.extractall(ext)
    else:
        with tarfile.open(ruta) as t:
            t.extractall(ext, filter="data")
    servidor = next((os.path.join(r, f) for r, _, fs in os.walk(ext) for f in fs
                     if f in ("llama-server", "llama-server.exe")), None)
    if not servidor:
        sys.exit("El paquete no trae llama-server")
    origen = os.path.dirname(servidor)
    os.makedirs(a.destino, exist_ok=True)
    for n in os.listdir(origen):
        p = os.path.join(origen, n)
        base = n.lower()
        if base.startswith("llama-") and not base.startswith("llama-server") and (base.endswith(".exe") or "." not in base):
            continue  # otras herramientas: no hacen falta
        if base.startswith("test-") or base.endswith((".py", ".md")):
            continue
        destino = os.path.join(a.destino, n)
        (shutil.copytree if os.path.isdir(p) else shutil.copy2)(p, destino, **({"symlinks": True} if os.path.isdir(p) else {"follow_symlinks": False}))
    with open(os.path.join(a.destino, "VERSION.txt"), "w") as f:
        f.write(f"{rel['tag_name']} {activo['name']}\n")
    shutil.rmtree(tmp, ignore_errors=True)
    print("listo en", a.destino)


if __name__ == "__main__":
    main()
