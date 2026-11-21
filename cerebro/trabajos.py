"""Bandeja y ejecución de recetas, un trabajo detrás de otro (una sola GPU)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import memoria, notas, recetas, voz
from .config import CONFIG, SIMULADO
from .eventos import hub
from .motor import motor

log = logging.getLogger("cerebro.trabajos")
TEXTO = {".txt", ".md"}


def _mmss(s: float) -> str:
    s = int(s or 0)
    return f"{s // 3600}h {s // 60 % 60:02d}min" if s >= 3600 else f"{s // 60}:{s % 60:02d} min"


def _resumen_corto(texto: str) -> str:
    m = re.search(r"##\s*Resumen\s*\n+(.+?)(\n\n|\n##|$)", texto, re.S)
    frase = (m.group(1) if m else texto).strip().split("\n")[0]
    return frase[:220]


def _trozos(texto: str, palabras: int) -> list[str]:
    lineas, trozos, actual, n = texto.splitlines(), [], [], 0
    for l in lineas:
        c = len(l.split())
        if actual and n + c > palabras:
            trozos.append("\n".join(actual))
            actual, n = [], 0
        actual.append(l)
        n += c
    if actual:
        trozos.append("\n".join(actual))
    return trozos or [texto]


class Gestor:
    def __init__(self) -> None:
        self.estado_dir: Path = CONFIG["rutas"]["estado"]
        self.ruta_lista = self.estado_dir / "trabajos.json"
        self.ruta_noche = self.estado_dir / "memoria_pendiente.json"
        self.lista: list[dict] = self._leer(self.ruta_lista, [])
        self.noche: list[dict] = self._leer(self.ruta_noche, [])
        self.cola: asyncio.Queue = asyncio.Queue()
        self.vistos: set[str] = {t["origen"] for t in self.lista}
        self.aprendiendo = False

    # --- persistencia -------------------------------------------------
    @staticmethod
    def _leer(ruta: Path, defecto):
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return defecto

    def _guardar(self) -> None:
        self.ruta_lista.write_text(json.dumps(self.lista[-300:], ensure_ascii=False, indent=1), encoding="utf-8")
        self.ruta_noche.write_text(json.dumps(self.noche, ensure_ascii=False, indent=1), encoding="utf-8")

    async def _cambio(self, t: dict) -> None:
        self._guardar()
        await hub.emitir("trabajo", trabajo=t)

    # --- entrada --------------------------------------------------------
    async def añadir(self, ruta: Path, receta_id: str | None = None) -> dict:
        receta = recetas.elegir(ruta, receta_id)
        t = {"id": uuid.uuid4().hex[:10], "archivo": ruta.name, "origen": str(ruta),
             "receta": receta["id"] if receta else None, "receta_nombre": receta["nombre"] if receta else "",
             "estado": "en_cola" if receta else "sin_receta", "paso": "", "error": "",
             "creado": datetime.now().isoformat(timespec="seconds"), "nota": ""}
        self.lista.append(t)
        self.vistos.add(str(ruta))
        await self._cambio(t)
        if receta:
            await self.cola.put(t["id"])
        return t

    async def vigilar_bandeja(self) -> None:
        """Mira la bandeja cada 3 s. Sirve para Syncthing o para copiar archivos a mano."""
        bandeja: Path = CONFIG["rutas"]["bandeja"]
        tamaños: dict[str, int] = {}
        while True:
            try:
                for p in bandeja.rglob("*"):
                    if not p.is_file() or p.name.startswith(".") or p.suffix in (".parcial", ".tmp") \
                            or str(p) in self.vistos:
                        continue
                    tam = p.stat().st_size
                    if tamaños.get(str(p)) == tam:  # estable: ya terminó de copiarse
                        tamaños.pop(str(p), None)
                        await self.añadir(p)
                    else:
                        tamaños[str(p)] = tam
            except Exception:
                log.exception("Error vigilando la bandeja")
            await asyncio.sleep(3)

    def reanudar(self) -> None:
        for t in self.lista:
            if t["estado"] in ("en_cola", "procesando"):
                t["estado"] = "en_cola"
                self.cola.put_nowait(t["id"])

    # --- ejecución ------------------------------------------------------
    async def trabajador(self) -> None:
        while True:
            tid = await self.cola.get()
            t = next((x for x in self.lista if x["id"] == tid), None)
            if t:
                await self._ejecutar(t)

    async def _ejecutar(self, t: dict) -> None:
        ruta = Path(t["origen"])
        if not ruta.exists():
            t.update(estado="error", error="El archivo ya no está en la bandeja")
            await self._cambio(t)
            return
        try:
            receta = recetas.cargar(t["receta"])
        except Exception as e:
            t.update(estado="error", error=f"Receta no válida: {e}")
            await self._cambio(t)
            return
        ahora = datetime.now()
        ctx = {"archivo": ruta.name, "nombre": ruta.stem.replace("_", " "), "fecha": f"{ahora:%d/%m/%Y}",
               "hora": f"{ahora:%H:%M}", "ruta": str(ruta), "duracion": "", "personas": "",
               "transcripcion": "", "resumen_corto": ""}
        if ruta.suffix.lower() in TEXTO:
            ctx["contenido"] = ruta.read_text(encoding="utf-8", errors="replace")
        t.update(estado="procesando", error="")
        await self._cambio(t)
        await hub.emitir("avatar", estado="aprendiendo", texto=f"Procesando {ruta.name}")
        try:
            for n, paso in enumerate(receta["pasos"], 1):
                tipo, params = next(iter(paso.items()))
                t["paso"] = f"{n}/{len(receta['pasos'])} {tipo}"
                await self._cambio(t)
                await getattr(self, f"_p_{tipo}")(ctx, params or {}, t, ruta)
            destino = CONFIG["rutas"]["archivo"] / f"{ahora:%Y-%m}"
            destino.mkdir(parents=True, exist_ok=True)
            final = destino / ruta.name
            if final.exists():
                final = destino / f"{ruta.stem}_{t['id']}{ruta.suffix}"
            shutil.move(str(ruta), final)
            t.update(origen=str(final), estado=t.get("estado_final", "hecho"), paso="")
        except Exception as e:
            log.exception("Fallo en %s", t["archivo"])
            t.update(estado="error", error=str(e)[:300])
        await self._cambio(t)
        await hub.emitir("avatar", estado="reposo", texto="")

    # --- pasos ----------------------------------------------------------
    async def _p_transcribir(self, ctx, p, t, ruta) -> None:
        res = await asyncio.to_thread(voz.transcribir, ruta, bool(p.get("separar_voces", True)))
        voz.liberar()
        ctx.update(transcripcion=res["texto"], duracion=_mmss(res["duracion"]),
                   personas=res["personas"] or "—", segmentos=res["segmentos"])

    async def _p_preguntar_llm(self, ctx, p, t, ruta) -> None:
        perfil = p.get("perfil", "texto")
        destino = p.get("guardar_como", "respuesta")
        entrada = p.get("entrada")
        max_t = int(p.get("max_tokens", 900))
        if entrada and p.get("trocear") and len(str(ctx.get(entrada, "")).split()) > int(p["trocear"]):
            partes = []
            trozos = _trozos(str(ctx[entrada]), int(p["trocear"]))
            for i, trozo in enumerate(trozos, 1):
                t["paso"] = f"{t['paso'].split(' ·')[0]} · parte {i}/{len(trozos)}"
                await self._cambio(t)
                partes.append(await motor.chat(
                    [{"role": "user", "content": recetas.rellenar(p["prompt"], {**ctx, entrada: trozo})}],
                    perfil=perfil, max_tokens=max_t))
            union = p.get("prompt_union") or (
                "Une estos resúmenes parciales de un mismo documento en uno solo, en español, con el mismo "
                "formato y secciones, sin repetir:\n\n{partes}")
            respuesta = await motor.chat(
                [{"role": "user", "content": recetas.rellenar(union, {**ctx, "partes": "\n\n---\n\n".join(partes)})}],
                perfil=perfil, max_tokens=max_t)
        else:
            respuesta = await motor.chat([{"role": "user", "content": recetas.rellenar(p["prompt"], ctx)}],
                                         perfil=perfil, max_tokens=max_t)
        ctx[destino] = respuesta
        if not ctx.get("resumen_corto"):
            ctx["resumen_corto"] = _resumen_corto(respuesta)

    async def _p_describir_imagen(self, ctx, p, t, ruta) -> None:
        texto = recetas.rellenar(p.get("prompt", "Describe esta imagen en español."), ctx)
        ctx[p.get("guardar_como", "descripcion")] = await motor.chat(
            [{"role": "user", "content": texto}], perfil=p.get("perfil", "vision"),
            max_tokens=int(p.get("max_tokens", 700)), imagen=ruta)

    async def _p_guardar_nota(self, ctx, p, t, ruta) -> None:
        titulo = recetas.rellenar(p.get("titulo", "{nombre}"), ctx)
        contenido = recetas.rellenar(p.get("contenido", "{resumen}"), ctx)
        ruta_nota = notas.guardar(titulo, contenido, p.get("carpeta", ""))
        ctx.update(nota=contenido, titulo_nota=titulo)
        t["nota"] = str(ruta_nota.relative_to(CONFIG["rutas"]["notas"]))

    async def _p_recordar(self, ctx, p, t, ruta) -> None:
        titulo = recetas.rellenar(p.get("titulo", ctx.get("titulo_nota", "{nombre}")), ctx)
        contenido = recetas.rellenar(p.get("contenido", "{nota}"), ctx)
        if p.get("de_noche") and not SIMULADO:
            self.noche.append({"titulo": titulo, "contenido": contenido, "trabajo": t["id"]})
            t["estado_final"] = "memoria_esta_noche"
            self._guardar()
            await hub.emitir("memoria", pendientes=len(self.noche))
            return
        await memoria.recordar(titulo, contenido)
        await hub.emitir("grafo_actualizado")

    async def _p_avisar(self, ctx, p, t, ruta) -> None:
        await hub.emitir("aviso", texto=recetas.rellenar(p.get("mensaje", "Trabajo terminado"), ctx))

    # --- memoria nocturna --------------------------------------------------
    async def aprender_pendientes(self) -> int:
        if self.aprendiendo or not self.noche:
            return 0
        self.aprendiendo = True
        hechos = 0
        try:
            while self.noche:
                item = self.noche[0]
                await hub.emitir("avatar", estado="aprendiendo",
                                 texto=f"Aprendiendo: {item['titulo']} ({len(self.noche)} pendientes)")
                await memoria.recordar(item["titulo"], item["contenido"])
                self.noche.pop(0)
                hechos += 1
                for t in self.lista:
                    if t["id"] == item.get("trabajo") and t["estado"] == "memoria_esta_noche":
                        t["estado"] = "hecho"
                        await hub.emitir("trabajo", trabajo=t)
                self._guardar()
                await hub.emitir("grafo_actualizado")
                await hub.emitir("memoria", pendientes=len(self.noche))
        except Exception:
            log.exception("Fallo aprendiendo; queda pendiente para la próxima vez")
        finally:
            self.aprendiendo = False
            await hub.emitir("avatar", estado="reposo", texto="")
        return hechos

    async def reloj_nocturno(self) -> None:
        hora = int(CONFIG["memoria"].get("hora_nocturna", 3))
        ultimo_dia = None
        while True:
            ahora = datetime.now()
            if ahora.hour == hora and ultimo_dia != ahora.date() and self.cola.empty():
                ultimo_dia = ahora.date()
                await self.aprender_pendientes()
            await asyncio.sleep(60)


gestor: Gestor | None = None


def obtener() -> Gestor:
    global gestor
    if gestor is None:
        gestor = Gestor()
    return gestor
