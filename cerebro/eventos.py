"""Difusión de eventos a todas las pantallas conectadas (WebSocket)."""
from __future__ import annotations

import asyncio
import json
import logging
import time

log = logging.getLogger("cerebro.eventos")


class Hub:
    def __init__(self) -> None:
        self.clientes: set = set()
        self.estado_avatar = {"estado": "reposo", "texto": ""}
        self.preparacion: dict = {}

    async def conectar(self, ws) -> None:
        self.clientes.add(ws)
        await ws.send_text(json.dumps({"tipo": "avatar", **self.estado_avatar}))
        if self.preparacion:
            await ws.send_text(json.dumps({"tipo": "preparacion", **self.preparacion}))

    def desconectar(self, ws) -> None:
        self.clientes.discard(ws)

    async def emitir(self, tipo: str, **datos) -> None:
        if tipo == "avatar":
            self.estado_avatar = {k: datos.get(k, "") for k in ("estado", "texto")}
        if tipo == "preparacion":
            self.preparacion = datos if datos.get("activo") else {}
        mensaje = json.dumps({"tipo": tipo, "t": time.time(), **datos}, default=str)
        muertos = []
        for ws in list(self.clientes):
            try:
                await ws.send_text(mensaje)
            except Exception:
                muertos.append(ws)
        for ws in muertos:
            self.clientes.discard(ws)

    def emitir_desde_hilo(self, loop: asyncio.AbstractEventLoop, tipo: str, **datos) -> None:
        asyncio.run_coroutine_threadsafe(self.emitir(tipo, **datos), loop)


hub = Hub()
