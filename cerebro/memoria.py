"""Memoria con Cognee, 100% local.

Cognee usa el mismo llama-server de la app (proveedor "custom", API OpenAI) y embeddings
Fastembed en CPU, así que no hace falta ningún otro servidor. Todo se guarda en archivos
(SQLite, LanceDB y grafo embebido) dentro de datos/memoria.
"""
from __future__ import annotations

import inspect
import time
import logging
import os
from collections import Counter

from . import simulado
from .config import CONFIG, SIMULADO
from .motor import motor

log = logging.getLogger("cerebro.memoria")

SISTEMA = ("Eres el asistente personal de Joseba. Responde en español, breve y concreto, usando solo la "
           "información de su memoria. Si no está en la memoria, dilo. Cita la fuente cuando la tengas.")
OCULTAR = {"DocumentChunk", "TextSummary", "NodeSet"}

_cognee = None


def _entorno() -> None:
    m = CONFIG["memoria"]
    base = CONFIG["rutas"]["memoria"]
    valores = {
        "LLM_PROVIDER": "custom",
        "LLM_MODEL": "openai/local",
        "LLM_ENDPOINT": f"{motor.url}/v1",
        "LLM_API_KEY": ".",
        "LLM_INSTRUCTOR_MODE": "json_schema_mode",
        "EMBEDDING_PROVIDER": "fastembed",
        "EMBEDDING_MODEL": m.get("embeddings", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
        "EMBEDDING_DIMENSIONS": str(m.get("dimensiones", 384)),
        "SYSTEM_ROOT_DIRECTORY": str(base / "sistema"),
        "DATA_ROOT_DIRECTORY": str(base / "datos"),
        "TELEMETRY_DISABLED": "true",
        "ENABLE_BACKEND_ACCESS_CONTROL": "false",
        "REQUIRE_AUTHENTICATION": "false",
        "FASTEMBED_CACHE_PATH": str(CONFIG["rutas"]["modelos"] / "fastembed"),
    }
    for k, v in valores.items():
        os.environ.setdefault(k, v)


def _c():
    global _cognee
    if _cognee is None:
        _entorno()
        import cognee

        _cognee = cognee
    return _cognee


def dataset() -> str:
    return CONFIG["memoria"].get("dataset", "cerebro")


async def recordar(titulo: str, texto: str) -> None:
    if SIMULADO:
        simulado.recordar(titulo, texto)
        return
    cognee = _c()
    cerrojo = await motor.reservar(CONFIG["llama"].get("perfil_chat", "texto"))
    try:
        await cognee.remember(f"# {titulo}\n\n{texto}", dataset_name=dataset(), self_improvement=False)
    finally:
        motor.ultimo_uso = time.time()
        cerrojo.release()


async def preguntar(pregunta: str) -> str | None:
    """Respuesta de Cognee sobre el grafo, o None si no hay memoria o falla."""
    if SIMULADO:
        return None
    try:
        cognee = _c()
        cerrojo = await motor.reservar(CONFIG["llama"].get("perfil_chat", "texto"))
        try:
            res = await cognee.recall(query_text=pregunta, datasets=[dataset()], system_prompt=SISTEMA, top_k=10)
        finally:
            cerrojo.release()
        textos = [getattr(r, "text", None) or getattr(r, "content", None) or str(r) for r in res or []]
        textos = [t for t in textos if t and t.strip()]
        return textos[0].strip() if textos else None
    except Exception:
        log.exception("Cognee no pudo responder; uso las notas")
        return None


def _props(nodo):
    if isinstance(nodo, (tuple, list)) and len(nodo) >= 2:
        return str(nodo[0]), dict(nodo[1] or {})
    d = dict(nodo)
    return str(d.get("id")), d


def _arista(a):
    if isinstance(a, (tuple, list)):
        return str(a[0]), str(a[1]), str(a[2]) if len(a) > 2 else ""
    d = dict(a)
    return str(d.get("source") or d.get("source_node_id")), str(d.get("target") or d.get("target_node_id")), \
        str(d.get("relationship_name") or d.get("label") or "")


def formatear(nodos_crudos, aristas_crudas, max_nodos: int) -> dict:
    props = dict(_props(n) for n in nodos_crudos)
    aristas = [_arista(a) for a in aristas_crudas]
    tipo_entidad = {}
    for o, d, rel in aristas:  # Entity --is_a--> EntityType
        if rel == "is_a" and d in props:
            tipo_entidad[o] = str(props[d].get("name") or "entidad").lower()
    nodos = {}
    for i, p in props.items():
        tipo = str(p.get("type") or "")
        if tipo in OCULTAR:
            continue
        if tipo == "Entity":
            cat = tipo_entidad.get(i, "entidad")
        elif tipo == "EntityType":
            cat = "tipo"
        elif tipo in ("TextDocument", "Document", "AudioDocument", "ImageDocument"):
            cat = "fuente"
        else:
            cat = tipo.lower() or "otro"
        nombre = p.get("name") or p.get("title") or tipo or i[:8]
        nodos[i] = {"id": i, "label": str(nombre)[:80], "categoria": cat,
                    "desc": str(p.get("description") or "")[:400]}
    lista = [{"origen": o, "destino": d, "label": rel} for o, d, rel in aristas
             if o in nodos and d in nodos and o != d]
    grado = Counter()
    for a in lista:
        grado[a["origen"]] += 1
        grado[a["destino"]] += 1
    if len(nodos) > max_nodos:
        quedan = {i for i, _ in sorted(nodos.items(), key=lambda kv: -grado[kv[0]])[:max_nodos]}
        nodos = {i: n for i, n in nodos.items() if i in quedan}
        lista = [a for a in lista if a["origen"] in quedan and a["destino"] in quedan]
    for i, n in nodos.items():
        n["grado"] = grado[i]
    return {"nodos": list(nodos.values()), "aristas": lista}


async def grafo() -> dict:
    max_nodos = int(CONFIG["memoria"].get("max_nodos_avatar", 350))
    if SIMULADO:
        return simulado.grafo()
    try:
        _c()
        from cognee.infrastructure.databases.graph import get_graph_engine

        motor_grafo = get_graph_engine()
        if inspect.isawaitable(motor_grafo):
            motor_grafo = await motor_grafo
        nodos, aristas = await motor_grafo.get_graph_data()
        return formatear(nodos, aristas, max_nodos)
    except Exception:
        log.exception("No pude leer el grafo de Cognee")
        return {"nodos": [], "aristas": []}
