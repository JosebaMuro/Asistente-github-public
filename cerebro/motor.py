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
import shutil
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
# Línea de `llama-server --list-devices`: "  ROCm0: AMD Radeon RX 7600 (8176 MiB, 7900 MiB free)"
DISPOSITIVO = re.compile(r"^\s*([A-Za-z]+\d+):\s*(.+?)\s*\((\d+) MiB,\s*(\d+) MiB free\)", re.M)
INTEGRADA = re.compile(r"llvmpipe|lavapipe|Intel|Radeon\(TM\) Graphics|Radeon Graphics|Vega \d+ Graphics|"
                       r"Radeon \d+M|780M|880M|890M", re.I)
# Preferencia de backend: el nativo de cada fabricante primero, Vulkan después
ORDEN = {"cuda": 0, "rocm": 1, "vulkan": 2, "sycl": 3}


def _entorno(binario: Path) -> dict:
    """Cada llama-server carga primero las librerías de su carpeta (evita mezclar las del ROCm con las del CUDA)."""
    env = os.environ.copy()
    if sys.platform != "win32":
        env["LD_LIBRARY_PATH"] = os.pathsep.join(x for x in (str(binario.parent), str(binario.parent.parent / "lib"),
                                                              env.get("LD_LIBRARY_PATH", "")) if x)
    return env


def _tipo(nombre_disp: str) -> str:
    n = nombre_disp.lower()
    for t in ("cuda", "rocm", "vulkan", "sycl"):
        if n.startswith(t):
            return t
    return n.rstrip("0123456789")


class Motor:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.perfil: str | None = None
        self.cerrojo = asyncio.Lock()
        self.ultimo_uso = time.time()
        cfg = CONFIG["llama"]
        self.puerto = int(cfg.get("puerto", 8766))
        self.url = f"http://127.0.0.1:{self.puerto}"
        self.eleccion: dict | None = None  # {"binario", "dispositivo", "tipo", "nombre"}

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
        eleccion = await self.elegir()
        binario = eleccion["binario"]
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
        if eleccion.get("dispositivo"):
            args += ["--device", eleccion["dispositivo"]]
        if CONFIG["llama"].get("sin_conexion") and "hf" in conf:
            args.append("--offline")  # usa solo la caché local de modelos, no toca la red
        args += [str(a) for a in conf.get("extra", [])]
        registro = open(CONFIG["rutas"]["estado"] / "llama-server.log", "ab")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        log.info("Arrancando llama-server: %s", " ".join(args))
        self.proc = subprocess.Popen(args, stdout=registro, stderr=subprocess.STDOUT,
                                     cwd=str(binario.parent), creationflags=flags, env=_entorno(binario))
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

    async def _dispositivos(self, binario: Path) -> list[dict]:
        """Pregunta a un llama-server qué GPUs ve. Si no arranca (falta su driver), devuelve []."""
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = await asyncio.create_subprocess_exec(
                str(binario), "--list-devices", cwd=str(binario.parent), creationflags=flags, env=_entorno(binario),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            salida, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except Exception as e:  # noqa: BLE001
            log.info("%s no arranca: %s", binario, e)
            return []
        texto = salida.decode("utf-8", "replace")
        return [{"dispositivo": m.group(1), "nombre": m.group(2), "memoria": int(m.group(3)),
                 "libre": int(m.group(4)), "tipo": _tipo(m.group(1))} for m in DISPOSITIVO.finditer(texto)]

    async def elegir(self) -> dict:
        """Elige motor y GPU una vez por sesión: CUDA (NVIDIA) > ROCm (AMD) > Vulkan (cualquiera) > CPU.
        Prefiere la tarjeta dedicada a la integrada. Se puede forzar con llama.variante / llama.dispositivo."""
        if self.eleccion:
            return self.eleccion
        cfg = CONFIG["llama"]
        if cfg.get("binario"):
            lista = [Path(cfg["binario"])]
        else:
            lista = descargas.candidatos() or [await descargas.preparar_llama()]
        forzado = (cfg.get("variante") or "auto").lower()
        fabricantes = descargas.gpus()
        if shutil.which("nvidia-smi"):
            fabricantes.append("nvidia")
        mejor, puntos_mejor = None, None
        for b in lista:
            carpeta = b.parent.name.lower()
            # Sin su driver, el exe de CUDA/ROCm ni arranca (en Windows saldría un aviso de DLL que falta)
            if (descargas.es_windows() and fabricantes and
                    (("cuda" in carpeta and "nvidia" not in fabricantes) or ("rocm" in carpeta and "amd" not in fabricantes))):
                continue
            for d in await self._dispositivos(b):
                if forzado not in ("auto", d["tipo"]):
                    continue
                integrada = bool(INTEGRADA.search(d["nombre"])) and d["tipo"] in ("vulkan", "sycl", "rocm")
                puntos = (integrada, ORDEN.get(d["tipo"], 9), -d["memoria"])
                log.info("GPU vista por %s: %s %s (%d MiB)", b.parent.name, d["dispositivo"], d["nombre"], d["memoria"])
                if puntos_mejor is None or puntos < puntos_mejor:
                    mejor, puntos_mejor = {**d, "binario": b}, puntos
        if cfg.get("dispositivo"):
            mejor = {**(mejor or {"binario": lista[0], "tipo": "manual", "nombre": cfg["dispositivo"]}),
                     "dispositivo": cfg["dispositivo"]}
        if mejor is None:
            log.warning("No veo ninguna GPU: llama.cpp irá en la CPU (más lento)")
            mejor = {"binario": lista[0], "dispositivo": "none", "tipo": "cpu", "nombre": "CPU"}
        log.info("Motor elegido: %s · %s (%s)", mejor["binario"], mejor["nombre"], mejor["dispositivo"])
        self.eleccion = mejor
        return mejor

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
