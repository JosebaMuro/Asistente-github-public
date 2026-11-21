"""Carga de configuración. Un único dict CONFIG para toda la app."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

VERSION = "1.1.0"


def raiz_app() -> Path:
    """Carpeta de la app (la que contiene config.yaml)."""
    if os.environ.get("CEREBRO_RAIZ"):
        return Path(os.environ["CEREBRO_RAIZ"]).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


RAIZ = raiz_app()
WEB = Path(__file__).resolve().parent.parent / "web"
if not WEB.exists():
    WEB = RAIZ / "web"


def _cargar() -> dict:
    ruta = Path(os.environ.get("CEREBRO_CONFIG", RAIZ / "config.yaml"))
    cfg = {}
    if ruta.exists():
        with open(ruta, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    if os.environ.get("CEREBRO_MODO"):
        cfg["modo"] = os.environ["CEREBRO_MODO"]
    cfg.setdefault("modo", "real")
    cfg.setdefault("servidor", {}).setdefault("puerto", 8765)
    cfg["servidor"].setdefault("host", "0.0.0.0")
    rutas = cfg.setdefault("rutas", {})
    defecto = {
        "bandeja": "datos/bandeja", "archivo": "datos/archivo", "notas": "datos/notas",
        "estado": "datos/estado", "memoria": "datos/memoria", "modelos": "modelos",
        "motor": "motor", "recetas": "recetas",
    }
    for clave, valor in defecto.items():
        p = Path(rutas.get(clave) or valor)
        p = p if p.is_absolute() else (RAIZ / p)
        p = p.resolve()
        p.mkdir(parents=True, exist_ok=True)
        rutas[clave] = p
    cfg.setdefault("llama", {})
    # Paquetes (AppImage, portable de Windows) indican aquí su llama-server incluido
    # Lista de llama-server incluidos (CUDA, ROCm, Vulkan…): Cerebro prueba cuál ve la GPU
    if os.environ.get("CEREBRO_LLAMA"):
        cfg["llama"]["incluidos"] = [p for p in os.environ["CEREBRO_LLAMA"].split(os.pathsep) if p]
    if os.environ.get("CEREBRO_OFFLINE") == "1":
        cfg["llama"]["sin_conexion"] = True
    cfg.setdefault("voz", {})
    cfg.setdefault("memoria", {})
    return cfg


CONFIG = _cargar()
SIMULADO = CONFIG["modo"] == "simulado"
