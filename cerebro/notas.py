"""Notas en Markdown: la fuente de verdad. Cognee es el índice inteligente encima."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .config import CONFIG


def _carpeta() -> Path:
    return CONFIG["rutas"]["notas"]


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60] or "nota"


def guardar(titulo: str, contenido: str, carpeta: str = "") -> Path:
    destino = _carpeta() / carpeta if carpeta else _carpeta()
    destino.mkdir(parents=True, exist_ok=True)
    nombre = f"{datetime.now():%Y-%m-%d_%H%M}_{_slug(titulo)}.md"
    ruta = destino / nombre
    ruta.write_text(contenido if contenido.lstrip().startswith("#") else f"# {titulo}\n\n{contenido}",
                    encoding="utf-8")
    return ruta


def _norm(s: str) -> str:
    return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()


def buscar(pregunta: str, n: int = 3) -> list[dict]:
    palabras = [w for w in re.findall(r"\w+", _norm(pregunta)) if len(w) > 3]
    if not palabras:
        return []
    resultados = []
    for ruta in _carpeta().rglob("*.md"):
        try:
            texto = ruta.read_text(encoding="utf-8")
        except OSError:
            continue
        t = _norm(texto)
        puntos = sum(t.count(w) for w in palabras)
        if not puntos:
            continue
        lineas = texto.splitlines()
        mejores = sorted(range(len(lineas)), key=lambda i: -sum(w in _norm(lineas[i]) for w in palabras))[:6]
        fragmento = "\n".join(lineas[i] for i in sorted(mejores) if lineas[i].strip())
        titulo = next((l.lstrip("# ").strip() for l in lineas if l.startswith("#")), ruta.stem)
        resultados.append({"puntos": puntos, "titulo": titulo, "fragmento": fragmento[:1200],
                           "ruta": str(ruta.relative_to(_carpeta()))})
    resultados.sort(key=lambda r: -r["puntos"])
    return resultados[:n]


def listar(n: int = 50) -> list[dict]:
    rutas = sorted(_carpeta().rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:n]
    salida = []
    for r in rutas:
        primera = r.read_text(encoding="utf-8").splitlines()[:1]
        salida.append({"ruta": str(r.relative_to(_carpeta())),
                       "titulo": primera[0].lstrip("# ").strip() if primera else r.stem,
                       "fecha": datetime.fromtimestamp(r.stat().st_mtime).isoformat(timespec="minutes")})
    return salida
