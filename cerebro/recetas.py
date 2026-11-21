"""Recetas: flujos de trabajo editables en YAML, uno por archivo en ./recetas.

Una receta dice cuándo se aplica (extensiones o carpeta de la bandeja) y qué pasos hace.
Los textos admiten {variables} del contexto: {archivo}, {nombre}, {fecha}, {hora},
{transcripcion}, y cualquier resultado guardado con guardar_como.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import CONFIG

PASOS_VALIDOS = {"transcribir", "preguntar_llm", "describir_imagen", "guardar_nota", "recordar", "avisar"}
VAR = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class RecetaInvalida(ValueError):
    pass


def carpeta() -> Path:
    return CONFIG["rutas"]["recetas"]


def validar(datos) -> dict:
    if not isinstance(datos, dict):
        raise RecetaInvalida("La receta debe ser un mapa YAML con nombre, cuando y pasos.")
    if not datos.get("nombre"):
        raise RecetaInvalida("Falta 'nombre'.")
    pasos = datos.get("pasos")
    if not isinstance(pasos, list) or not pasos:
        raise RecetaInvalida("Falta la lista 'pasos'.")
    for i, paso in enumerate(pasos, 1):
        if not isinstance(paso, dict) or len(paso) != 1:
            raise RecetaInvalida(f"El paso {i} debe ser una sola clave, por ejemplo '- transcribir: {{}}'.")
        tipo = next(iter(paso))
        if tipo not in PASOS_VALIDOS:
            raise RecetaInvalida(f"Paso {i}: '{tipo}' no existe. Usa uno de: {', '.join(sorted(PASOS_VALIDOS))}.")
    cuando = datos.setdefault("cuando", {})
    cuando["extensiones"] = [e.lower() if e.startswith(".") else "." + e.lower() for e in cuando.get("extensiones", [])]
    datos.setdefault("prioridad", 50)
    return datos


def cargar(rid: str) -> dict:
    ruta = carpeta() / f"{rid}.yaml"
    if not ruta.exists():
        raise KeyError(rid)
    datos = validar(yaml.safe_load(ruta.read_text(encoding="utf-8")))
    datos["id"] = rid
    return datos


def listar() -> list[dict]:
    salida = []
    for ruta in sorted(carpeta().glob("*.yaml")):
        try:
            r = cargar(ruta.stem)
            salida.append({"id": r["id"], "nombre": r["nombre"], "descripcion": r.get("descripcion", ""),
                           "extensiones": r["cuando"]["extensiones"], "prioridad": r["prioridad"],
                           "pasos": [next(iter(p)) for p in r["pasos"]], "valida": True})
        except Exception as e:
            salida.append({"id": ruta.stem, "nombre": ruta.stem, "valida": False, "error": str(e)})
    return salida


def texto(rid: str) -> str:
    return (carpeta() / f"{rid}.yaml").read_text(encoding="utf-8")


def guardar(rid: str, contenido: str) -> dict:
    if not re.fullmatch(r"[a-z0-9_\-]{1,40}", rid):
        raise RecetaInvalida("El identificador solo admite minúsculas, números, '-' y '_'.")
    try:
        datos = yaml.safe_load(contenido)
    except yaml.YAMLError as e:
        raise RecetaInvalida(f"YAML no válido: {e}") from e
    validar(datos)
    (carpeta() / f"{rid}.yaml").write_text(contenido, encoding="utf-8")
    return cargar(rid)


def borrar(rid: str) -> None:
    (carpeta() / f"{rid}.yaml").unlink(missing_ok=True)


def elegir(archivo: Path, explicita: str | None = None) -> dict | None:
    """Receta explícita > subcarpeta de la bandeja con el id > extensión (menor prioridad gana)."""
    if explicita:
        return cargar(explicita)
    try:
        sub = archivo.relative_to(CONFIG["rutas"]["bandeja"]).parts
        if len(sub) > 1 and (carpeta() / f"{sub[0]}.yaml").exists():
            return cargar(sub[0])
    except ValueError:
        pass
    ext = archivo.suffix.lower()
    candidatas = [r for r in listar() if r.get("valida") and ext in r["extensiones"]]
    candidatas.sort(key=lambda r: r["prioridad"])
    return cargar(candidatas[0]["id"]) if candidatas else None


def rellenar(plantilla: str, ctx: dict) -> str:
    """Sustituye {var} conocidas y deja intactas las llaves desconocidas (por ejemplo JSON)."""
    return VAR.sub(lambda m: str(ctx[m.group(1)]) if m.group(1) in ctx else m.group(0), plantilla or "")
