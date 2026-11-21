"""Modo simulado: datos de ejemplo para probar la interfaz sin modelos ni GPU."""
from __future__ import annotations

import re
import unicodedata

_E = [
    # id, nombre, categoría, descripción
    ("ana", "Ana", "persona", "Lleva las finanzas. Dijo que la publicidad se lleva el 40 % del gasto y propuso recortarla un 10 %."),
    ("iker", "Iker", "persona", "Desarrollador de la app móvil. Se encarga del fallo de login en Android."),
    ("maite", "Maite", "persona", "Coordina la campaña de primavera. Preocupada por los plazos de la imprenta."),
    ("tu", "Joseba", "persona", "Participa en las tres reuniones. Tarea abierta: pedir un segundo presupuesto de imprenta."),
    ("imprenta", "Imprenta Norte", "organización", "Proveedor de imprenta. Entrega en 3 semanas si se confirma el pedido antes del 10 de diciembre."),
    ("presupuesto", "Presupuesto Q1", "tema", "Total previsto para el primer trimestre: 48.000 €, con la publicidad como partida principal."),
    ("campana", "Campaña de primavera", "tema", "Lanzamiento previsto en marzo. Depende de la imprenta y del recorte de publicidad."),
    ("app", "App móvil", "tema", "Beta prevista para enero. Bloqueada por el fallo de login en Android."),
    ("plazos", "Plazos de entrega", "tema", "La imprenta necesita 3 semanas; la campaña necesita el material a finales de febrero."),
    ("onboarding", "Onboarding", "tema", "Idea de un recorrido guiado de tres pantallas para la app."),
    ("recorte", "Recorte del 10 % en publicidad", "decisión", "Acordado por Ana y Maite. Libera unos 1.900 € para la campaña de primavera."),
    ("beta", "Beta de la app en enero", "decisión", "Condicionada a arreglar el login en Android antes del 15 de diciembre."),
    ("t_ana", "Nueva estimación de costes", "tarea", "Responsable: Ana. Fecha: viernes 27 de noviembre."),
    ("t_iker", "Arreglar login en Android", "tarea", "Responsable: Iker. Fecha límite: 15 de diciembre."),
    ("t_tu", "Pedir segundo presupuesto de imprenta", "tarea", "Responsable: Joseba. Antes del 10 de diciembre."),
    ("dic10", "10 de diciembre", "fecha", "Fecha límite para confirmar el pedido de imprenta."),
    ("dic15", "15 de diciembre", "fecha", "Fecha límite para arreglar el login en Android."),
    ("r1", "Reunión presupuesto Q1", "fuente", "presupuesto_q1.m4a · 52 min · 18 nov"),
    ("r2", "Revisión de sprint", "fuente", "sprint_19nov.m4a · 35 min · 19 nov"),
    ("r3", "Llamada con la imprenta", "fuente", "llamada_imprenta.m4a · 18 min · 20 nov"),
    ("f1", "Foto de pizarra del sprint", "fuente", "pizarra_sprint.jpg · 19 nov"),
]
_A = [
    ("r1", "ana", "menciona"), ("r1", "maite", "menciona"), ("r1", "tu", "menciona"), ("r1", "presupuesto", "trata"),
    ("r1", "campana", "trata"), ("r1", "recorte", "contiene"), ("r1", "t_ana", "contiene"), ("r1", "t_tu", "contiene"),
    ("r2", "iker", "menciona"), ("r2", "tu", "menciona"), ("r2", "app", "trata"), ("r2", "beta", "contiene"),
    ("r2", "t_iker", "contiene"), ("r3", "imprenta", "menciona"), ("r3", "plazos", "trata"), ("r3", "campana", "trata"),
    ("r3", "tu", "menciona"), ("f1", "app", "trata"), ("f1", "onboarding", "trata"),
    ("ana", "recorte", "propone"), ("maite", "recorte", "apoya"), ("ana", "t_ana", "responsable de"),
    ("iker", "t_iker", "responsable de"), ("tu", "t_tu", "responsable de"), ("t_tu", "imprenta", "sobre"),
    ("recorte", "presupuesto", "afecta a"), ("recorte", "campana", "financia"), ("beta", "app", "sobre"),
    ("t_iker", "beta", "bloquea"), ("t_iker", "dic15", "vence"), ("t_tu", "dic10", "vence"), ("imprenta", "dic10", "exige"),
    ("maite", "campana", "coordina"), ("maite", "plazos", "preocupada por"), ("onboarding", "app", "parte de"),
    ("imprenta", "plazos", "define"),
]

NODOS = [{"id": i, "label": n, "categoria": c, "desc": d} for i, n, c, d in _E]
ARISTAS = [{"origen": a, "destino": b, "label": l} for a, b, l in _A]


def grafo() -> dict:
    grado = {}
    for a in ARISTAS:
        grado[a["origen"]] = grado.get(a["origen"], 0) + 1
        grado[a["destino"]] = grado.get(a["destino"], 0) + 1
    return {"nodos": [{**n, "grado": grado.get(n["id"], 0)} for n in NODOS], "aristas": ARISTAS}


def norm(s: str) -> str:
    return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()


def buscar(pregunta: str) -> list[str]:
    palabras = [w for w in re.findall(r"\w+", norm(pregunta)) if len(w) > 3]
    puntos = []
    for n in NODOS:
        texto = norm(n["label"] + " " + n["desc"])
        p = sum(3 if w in norm(n["label"]) else 1 for w in palabras if w in texto)
        if "tarea" in norm(pregunta) and n["categoria"] == "tarea":
            p += 2
        if p:
            puntos.append((p, f"{n['label']}: {n['desc']}"))
    puntos.sort(reverse=True)
    return [t for _, t in puntos[:4]]


def recordar(titulo: str, texto: str) -> None:
    nuevo = f"s{len(NODOS)}"
    NODOS.append({"id": nuevo, "label": titulo, "categoria": "fuente", "desc": texto[:300]})
    t = norm(texto + " " + titulo)
    enlazados = 0
    for n in NODOS[:-1]:
        if n["categoria"] != "fuente" and norm(n["label"]).split()[0] in t:
            ARISTAS.append({"origen": nuevo, "destino": n["id"], "label": "menciona"})
            enlazados += 1
    if not enlazados:
        ARISTAS.append({"origen": nuevo, "destino": "tu", "label": "capturado por"})


def transcripcion(nombre: str) -> dict:
    segs = [
        (0, "Persona 1", "Vale, empezamos con lo de la imprenta."),
        (6, "Persona 2", "Me han dicho que necesitan tres semanas desde que confirmemos el pedido."),
        (14, "Persona 1", "Entonces hay que confirmarlo antes del 10 de diciembre."),
        (21, "Persona 2", "Yo pido otro presupuesto para comparar y os digo el lunes."),
    ]
    segmentos = [{"inicio": s, "fin": s + 6, "persona": p, "texto": t} for s, p, t in segs]
    texto = "\n".join(f"[00:{s['inicio']:02d}] {s['persona']}: {s['texto']}" for s in segmentos)
    return {"segmentos": segmentos, "texto": texto, "duracion": 27.0, "personas": 2}


def pregunta_por_voz() -> str:
    return "¿Qué tareas tengo pendientes?"


def respuesta_llm(mensajes: list[dict]) -> str:
    ultimo = mensajes[-1]["content"]
    if isinstance(ultimo, list):
        ultimo = ultimo[0]["text"]
    if "## Resumen" in ultimo or "RESUMEN" in ultimo.upper()[:400]:
        return ("## Resumen\nLa imprenta necesita tres semanas desde la confirmación del pedido, así que hay que "
                "confirmarlo antes del 10 de diciembre.\n\n## Decisiones\n- Confirmar el pedido antes del 10 de diciembre.\n\n"
                "## Tareas\n- [ ] Persona 2: pedir otro presupuesto y avisar el lunes.\n\n## Temas abiertos\n- Ninguno.")
    if "imagen" in ultimo.lower() or "foto" in ultimo.lower():
        return "Pizarra con tres prioridades del sprint: login de Android, notificaciones y onboarding."
    contexto = ultimo.split("Pregunta:")[0]
    lineas = [l.strip("- ").strip() for l in contexto.splitlines() if ":" in l and not l.startswith("Contexto")]
    if lineas:
        return "Según tu memoria: " + " ".join(lineas[:2]) + " (Respuesta de ejemplo: en modo real contesta tu modelo local.)"
    return "No encuentro nada sobre eso en la memoria de ejemplo. Prueba con presupuesto, Ana, app móvil o tareas."
