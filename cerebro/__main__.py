"""Punto de entrada.

    cerebro                 arranca el servidor (interfaz en http://localhost:8765)
    cerebro tui             abre la interfaz de terminal contra un servidor en marcha
    cerebro simulado        arranca con datos de ejemplo, sin modelos
    cerebro preparar        descarga llama.cpp y los modelos de voz y sale
    cerebro preparar --modelos   además descarga los modelos de lenguaje y embeddings (uso sin conexión)
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys


def _logs() -> None:
    from .config import CONFIG

    ruta = CONFIG["rutas"]["estado"] / "cerebro.log"
    archivo = logging.handlers.RotatingFileHandler(ruta, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    consola = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    for h in (archivo, consola):
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[archivo, consola])
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    orden = args[0] if args else "servidor"
    if orden == "simulado":
        os.environ["CEREBRO_MODO"] = "simulado"
        orden = "servidor"
    if orden == "tui":
        from .tui import main as tui_main

        tui_main(args[1:])
        return
    if orden in ("-h", "--help", "ayuda"):
        print(__doc__)
        return
    _logs()
    if orden == "preparar":
        import asyncio

        from . import descargas

        async def _todo():
            await descargas.preparar_todo()
            if "--modelos" in args:
                await descargas.preparar_modelos()

        asyncio.run(_todo())
        return
    import uvicorn

    from .config import CONFIG

    print(f"\n  Cerebro local en http://localhost:{CONFIG['servidor']['puerto']}  (Ctrl+C para salir)\n")
    uvicorn.run("cerebro.app:app", host=CONFIG["servidor"]["host"], port=int(CONFIG["servidor"]["puerto"]),
                log_level="warning", ws_ping_interval=20)


if __name__ == "__main__":
    main()
