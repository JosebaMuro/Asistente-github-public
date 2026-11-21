"""Gestor de llama-server: un solo modelo cargado cada vez, para caber en 6 GB de VRAM.

Cerebro arranca llama-server directamente (sin Ollama) con el perfil que haga falta,
lo cambia cuando otro paso necesita otro modelo y lo apaga cuando nadie lo usa.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

from . import descargas, simulado
from .config import CONFIG, SIMULADO
from .eventos import hub

log = logging.getLogger("cerebro.motor")
PENSAR = re.compile(r"<think>.*?</think>", re.S)


class Motor:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.perfil: str | None = None
        self.cerrojo = asyncio.Lock()
        self.ultimo_uso = time.time()
        cfg = CONFIG["llama"]
        self.puerto = int(cfg.get("puerto", 8766))
        self.url = f"http://127.0.0.1:{self.puerto}"

    def perfiles(self) -> dict:
        return CONFIG["llama"].get("perfiles", {})

    def vivo(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def _parar(self) -> None:
        if not self.vivo():
            self.proc, self.perfil = None, None
            return
        log.info("Parando llama-server (%s)", self.perfil)
        self.proc.terminate()
        for _ in range(50):
            if self.proc.poll() is not None:
                break
            await asyncio.sleep(0.1)
        else:
            self.proc.kill()
        self.proc, self.perfil = None, None

    async def _arrancar(self, perfil: str) -> None:
        conf = self.perfiles().get(perfil)
        if not conf:
            raise ValueError(f"Perfil de modelo desconocido: {perfil}")
        binario = await descargas.preparar_llama()
        descargas.cache_llama()
        args = [str(binario), "--host", "127.0.0.1", "--port", str(self.puerto),
                "-c", str(conf.get("contexto", 4096)),
                "-ngl", str(CONFIG["llama"].get("capas_gpu", 99)),
                "--alias", "local", "--jinja", "--no-webui"]
        if conf.get("modelo"):
            args += ["-m", str(conf["modelo"])]
            if conf.get("mmproj"):
                args += ["--mmproj", str(conf["mmproj"])]
        else:
            args += ["-hf", conf["hf"]]
        if CONFIG["llama"].get("sin_conexion") and "hf" in conf:
            args.append("--offline")  # usa solo la caché local de modelos, no toca la red
        args += [str(a) for a in conf.get("extra", [])]
        registro = open(CONFIG["rutas"]["estado"] / "llama-server.log", "ab")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        log.info("Arrancando llama-server: %s", " ".join(args))
        self.proc = subprocess.Popen(args, stdout=registro, stderr=subprocess.STDOUT,
                                     cwd=str(binario.parent), creationflags=flags, env=os.environ.copy())
        self.perfil = perfil
        inicio = time.time()
        await hub.emitir("preparacion", activo=True, texto=f"Cargando modelo {perfil}", progreso=0)
        async with httpx.AsyncClient(timeout=5) as c:
            while True:
                if not self.vivo():
                    raise RuntimeError("llama-server se cerró al arrancar. Mira datos/estado/llama-server.log")
                try:
                    r = await c.get(self.url + "/health")
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.time() - inicio > 3600:
                    raise TimeoutError("llama-server tarda demasiado en arrancar")
                await asyncio.sleep(1)
        await hub.emitir("preparacion", activo=False, texto="", progreso=100)

    async def asegurar(self, perfil: str) -> None:
        if self.perfil == perfil and self.vivo():
            return
        await self._parar()
        await self._arrancar(perfil)

    async def chat(self, mensajes: list[dict], perfil: str = "texto", max_tokens: int = 1200,
                   imagen: Path | None = None, temperatura: float = 0.3) -> str:
        if SIMULADO:
            await asyncio.sleep(0.6)
            return simulado.respuesta_llm(mensajes)
        if imagen is not None:
            datos = base64.b64encode(Path(imagen).read_bytes()).decode()
            tipo = "png" if str(imagen).lower().endswith(".png") else "jpeg"
            ultimo = mensajes[-1]
            ultimo["content"] = [
                {"type": "text", "text": ultimo["content"]},
                {"type": "image_url", "image_url": {"url": f"data:image/{tipo};base64,{datos}"}},
            ]
        async with self.cerrojo:
            await self.asegurar(perfil)
            self.ultimo_uso = time.time()
            cuerpo = {"model": "local", "messages": mensajes, "max_tokens": max_tokens,
                      "temperature": temperatura,
                      "chat_template_kwargs": {"enable_thinking": False}}
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=1800)) as c:
                r = await c.post(self.url + "/v1/chat/completions", json=cuerpo)
                r.raise_for_status()
            self.ultimo_uso = time.time()
        texto = r.json()["choices"][0]["message"].get("content") or ""
        return PENSAR.sub("", texto).strip()

    async def reservar(self, perfil: str):
        """Para Cognee: deja cargado un perfil y bloquea cambios mientras dure."""
        await self.cerrojo.acquire()
        try:
            await self.asegurar(perfil)
        except Exception:
            self.cerrojo.release()
            raise
        return self.cerrojo

    async def vigilar_inactividad(self) -> None:
        minutos = float(CONFIG["llama"].get("descargar_tras_minutos", 10))
        while True:
            await asyncio.sleep(30)
            if self.vivo() and not self.cerrojo.locked() and time.time() - self.ultimo_uso > minutos * 60:
                async with self.cerrojo:
                    await self._parar()
                    log.info("VRAM liberada por inactividad")

    async def cerrar(self) -> None:
        await self._parar()


motor = Motor()
