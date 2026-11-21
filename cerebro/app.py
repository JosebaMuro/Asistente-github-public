"""Servidor web de Cerebro: API, WebSocket y la interfaz con el avatar."""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import socket
import time
import unicodedata
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import descargas, memoria, notas, recetas, trabajos, voz
from .config import CONFIG, SIMULADO, VERSION, WEB
from .eventos import hub
from .motor import motor

log = logging.getLogger("cerebro.app")
_grafo_cache: dict = {"t": 0, "datos": None}


async def _grafo(forzar: bool = False) -> dict:
    if forzar or not _grafo_cache["datos"] or time.time() - _grafo_cache["t"] > 300:
        _grafo_cache.update(datos=await memoria.grafo(), t=time.time())
    return _grafo_cache["datos"]


@asynccontextmanager
async def vida(app: FastAPI):
    g = trabajos.obtener()
    g.reanudar()
    tareas = [asyncio.create_task(g.trabajador()), asyncio.create_task(g.vigilar_bandeja()),
              asyncio.create_task(g.reloj_nocturno()), asyncio.create_task(motor.vigilar_inactividad())]
    if not SIMULADO:
        tareas.append(asyncio.create_task(descargas.preparar_todo()))
    log.info("Cerebro %s en modo %s", VERSION, CONFIG["modo"])
    yield
    for t in tareas:
        t.cancel()
    await motor.cerrar()


app = FastAPI(title="Cerebro local", version=VERSION, lifespan=vida)


def _norm(s: str) -> str:
    return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()


def _ips() -> list[str]:
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


# --- estado -----------------------------------------------------------------
@app.get("/api/estado")
async def estado():
    g = trabajos.obtener()
    puerto = CONFIG["servidor"]["puerto"]
    return {
        "version": VERSION, "modo": CONFIG["modo"],
        "motor": {"cargado": motor.perfil if motor.vivo() else None,
                  "binario": str(descargas.binario_llama() or ""), "variante": descargas.variante()},
        "perfiles": {k: v.get("hf") or v.get("modelo") for k, v in motor.perfiles().items()},
        "trabajos": {"en_cola": g.cola.qsize(), "total": len(g.lista)},
        "memoria_pendiente": len(g.noche),
        "avatar": hub.estado_avatar, "preparacion": hub.preparacion,
        "direcciones": [f"http://{ip}:{puerto}" for ip in _ips()],
    }


@app.get("/api/grafo")
async def grafo(forzar: bool = False):
    return await _grafo(forzar)


# --- preguntar ----------------------------------------------------------------
def _nodos_relevantes(texto: str, datos: dict) -> list[str]:
    t = _norm(texto)
    hallados = []
    for n in datos.get("nodos", []):
        etiqueta = _norm(n["label"])
        if len(etiqueta) >= 3 and re.search(r"\b" + re.escape(etiqueta) + r"\b", t):
            hallados.append(n["id"])
    return hallados[:25]


async def responder(pregunta: str) -> dict:
    await hub.emitir("avatar", estado="pensando", texto=pregunta[:120])
    fuentes = []
    try:
        respuesta = await memoria.preguntar(pregunta)
        if not respuesta:
            if SIMULADO:
                from . import simulado

                contexto = "\n".join(f"- {r}" for r in simulado.buscar(pregunta))
            else:
                encontradas = notas.buscar(pregunta, 3)
                fuentes = [n["ruta"] for n in encontradas]
                contexto = "\n\n".join(f"### {n['titulo']} ({n['ruta']})\n{n['fragmento']}" for n in encontradas)
            respuesta = await motor.chat([
                {"role": "system", "content": memoria.SISTEMA},
                {"role": "user", "content": f"Contexto de la memoria:\n{contexto or '(vacío)'}\n\nPregunta: {pregunta}"},
            ], perfil=CONFIG["llama"].get("perfil_chat", "texto"), max_tokens=500)
    except Exception as e:
        log.exception("Fallo respondiendo")
        await hub.emitir("avatar", estado="reposo", texto="")
        raise HTTPException(503, f"No pude responder: {e}")
    datos = await _grafo()
    nodos = _nodos_relevantes(pregunta + " " + respuesta, datos)
    await hub.emitir("respuesta", pregunta=pregunta, respuesta=respuesta, nodos=nodos, fuentes=fuentes)
    await hub.emitir("avatar", estado="reposo", texto="")
    return {"respuesta": respuesta, "nodos": nodos, "fuentes": fuentes}


@app.post("/api/preguntar")
async def preguntar(cuerpo: dict = Body(...)):
    texto = str(cuerpo.get("texto", "")).strip()
    if not texto:
        raise HTTPException(400, "Escribe una pregunta.")
    return await responder(texto)


@app.post("/api/preguntar_audio")
async def preguntar_audio(audio: UploadFile = File(...)):
    tmp = CONFIG["rutas"]["estado"] / f"pregunta_{uuid.uuid4().hex[:8]}{Path(audio.filename or 'a.webm').suffix}"
    with open(tmp, "wb") as f:
        shutil.copyfileobj(audio.file, f)
    try:
        await hub.emitir("avatar", estado="escuchando", texto="Transcribiendo…")
        pregunta = (await asyncio.to_thread(voz.transcribir_corto, tmp)).strip()
    finally:
        tmp.unlink(missing_ok=True)
    if not pregunta:
        await hub.emitir("avatar", estado="reposo", texto="")
        raise HTTPException(422, "No he entendido nada en el audio.")
    return {"pregunta": pregunta, **await responder(pregunta)}


# --- bandeja ------------------------------------------------------------------
@app.post("/api/subir")
async def subir(archivo: UploadFile = File(...), receta: str | None = Form(None)):
    nombre = Path(archivo.filename or "captura").name
    nombre = re.sub(r"[^\w.\-]+", "_", nombre)
    if receta:
        try:
            recetas.cargar(receta)
        except Exception:
            raise HTTPException(400, f"La receta '{receta}' no existe o no es válida.")
    destino = CONFIG["rutas"]["bandeja"] / f"{time.strftime('%Y%m%d_%H%M%S')}_{nombre}"
    parcial = destino.with_suffix(destino.suffix + ".parcial")
    with open(parcial, "wb") as f:
        shutil.copyfileobj(archivo.file, f)
    parcial.rename(destino)
    g = trabajos.obtener()
    g.vistos.add(str(destino))
    return await g.añadir(destino, receta)


@app.post("/api/texto")
async def texto(cuerpo: dict = Body(...)):
    contenido = str(cuerpo.get("texto", "")).strip()
    if not contenido:
        raise HTTPException(400, "El texto está vacío.")
    titulo = re.sub(r"[^\w\- ]+", "", str(cuerpo.get("titulo") or contenido[:40])).strip() or "texto"
    destino = CONFIG["rutas"]["bandeja"] / f"{time.strftime('%Y%m%d_%H%M%S')}_{titulo.replace(' ', '_')}.txt"
    destino.write_text(contenido, encoding="utf-8")
    g = trabajos.obtener()
    g.vistos.add(str(destino))
    return await g.añadir(destino, cuerpo.get("receta") or None)


@app.get("/api/trabajos")
async def lista_trabajos():
    return list(reversed(trabajos.obtener().lista[-60:]))


@app.post("/api/trabajos/{tid}/reintentar")
async def reintentar(tid: str):
    g = trabajos.obtener()
    t = next((x for x in g.lista if x["id"] == tid), None)
    if not t:
        raise HTTPException(404, "Ese trabajo no existe.")
    if t["estado"] not in ("error", "sin_receta"):
        raise HTTPException(409, "Solo se reintentan trabajos con error.")
    if t["estado"] == "sin_receta":
        r = recetas.elegir(Path(t["origen"]))
        if not r:
            raise HTTPException(409, "Sigue sin haber una receta para ese tipo de archivo.")
        t["receta"], t["receta_nombre"] = r["id"], r["nombre"]
    t["estado"] = "en_cola"
    await hub.emitir("trabajo", trabajo=t)
    await g.cola.put(tid)
    return t


@app.post("/api/memoria/aprender")
async def aprender():
    g = trabajos.obtener()
    if not g.noche:
        return {"pendientes": 0, "mensaje": "No hay nada pendiente."}
    asyncio.create_task(g.aprender_pendientes())
    return {"pendientes": len(g.noche), "mensaje": "Aprendiendo ahora."}


@app.get("/api/notas")
async def lista_notas():
    return notas.listar()


@app.get("/api/notas/{ruta:path}")
async def ver_nota(ruta: str):
    base = CONFIG["rutas"]["notas"].resolve()
    p = (base / ruta).resolve()
    if base not in p.parents or not p.exists():
        raise HTTPException(404, "Nota no encontrada.")
    return PlainTextResponse(p.read_text(encoding="utf-8"))


# --- recetas ------------------------------------------------------------------
@app.get("/api/recetas")
async def lista_recetas():
    return recetas.listar()


@app.get("/api/recetas/{rid}")
async def ver_receta(rid: str):
    try:
        return PlainTextResponse(recetas.texto(rid))
    except OSError:
        raise HTTPException(404, "Receta no encontrada.")


@app.put("/api/recetas/{rid}")
async def guardar_receta(rid: str, contenido: str = Body(..., media_type="text/plain")):
    try:
        r = recetas.guardar(rid, contenido)
    except recetas.RecetaInvalida as e:
        raise HTTPException(422, str(e))
    await hub.emitir("recetas")
    return {"id": r["id"], "nombre": r["nombre"]}


@app.delete("/api/recetas/{rid}")
async def borrar_receta(rid: str):
    recetas.borrar(rid)
    await hub.emitir("recetas")
    return {"ok": True}


# --- tiempo real ----------------------------------------------------------------
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    await hub.conectar(websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("tipo") == "avatar":  # una pantalla habla o escucha: lo ven todas
                await hub.emitir("avatar", estado=msg.get("estado", "reposo"), texto=msg.get("texto", ""))
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        hub.desconectar(websocket)


@app.get("/")
async def inicio():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=str(WEB)), name="web")


@app.exception_handler(Exception)
async def error_general(request, exc):
    log.exception("Error no controlado")
    return JSONResponse({"detail": "Error interno. Mira datos/estado/cerebro.log"}, status_code=500)
