"""Interfaz de terminal (TUI) de Cerebro. Se conecta a un servidor en marcha.

    cerebro tui [--url http://localhost:8765]

Teclas: q salir · a aprender ahora · r refrescar · Tab cambiar de zona · Ctrl+S guardar receta
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random

import httpx
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (Button, DataTable, Footer, Header, Input, Label, ListItem, ListView, RichLog, Static,
                             TabbedContent, TabPane, TextArea)

ESTADOS = {"reposo": "en reposo", "pensando": "pensando…", "escuchando": "escuchando…",
           "hablando": "hablando", "aprendiendo": "aprendiendo…"}
ICONO_TRABAJO = {"en_cola": "· en cola", "procesando": "▶ procesando", "hecho": "✓ hecho",
                 "memoria_esta_noche": "☾ memoria esta noche", "error": "✗ error", "sin_receta": "? sin receta"}


class Avatar(Static):
    """El grafo de Cognee girando en la terminal, en miniatura."""

    def on_mount(self) -> None:
        self.puntos: list[tuple[float, float, float, int]] = []
        self.aristas: list[tuple[int, int]] = []
        self.angulo = 0.0
        self.estado = "reposo"
        self.set_interval(1 / 12, self.girar)

    def cargar(self, datos: dict) -> None:
        nodos = datos.get("nodos", [])[:120]
        idx = {n["id"]: i for i, n in enumerate(nodos)}
        rnd = random.Random(7)
        self.puntos = []
        for n in nodos:
            u, v = rnd.random() * 2 * math.pi, math.acos(2 * rnd.random() - 1)
            r = 0.55 + 0.45 * rnd.random()
            self.puntos.append((r * math.sin(v) * math.cos(u), r * math.cos(v), r * math.sin(v) * math.sin(u),
                                int(n.get("grado", 0))))
        self.aristas = [(idx[a["origen"]], idx[a["destino"]]) for a in datos.get("aristas", [])
                        if a["origen"] in idx and a["destino"] in idx][:200]

    def girar(self) -> None:
        velocidad = {"pensando": 0.16, "aprendiendo": 0.08, "escuchando": 0.05}.get(self.estado, 0.03)
        self.angulo += velocidad
        ancho = max(20, self.size.width - 2)
        alto = max(8, self.size.height - 2)
        lienzo = [[" "] * ancho for _ in range(alto)]
        c, s = math.cos(self.angulo), math.sin(self.angulo)
        latido = 1 + (0.06 * math.sin(self.angulo * 6) if self.estado in ("hablando", "escuchando") else 0)
        proy = []
        for x, y, z, g in self.puntos:
            x2, z2 = x * c + z * s, -x * s + z * c
            px = int(ancho / 2 + x2 * ancho * 0.42 * latido)
            py = int(alto / 2 + y * alto * 0.42 * latido)
            proy.append((px, py, z2, g))
        for a, b in self.aristas:  # enlaces como puntos tenues
            (x1, y1, _, _), (x2, y2, _, _) = proy[a], proy[b]
            pasos = max(abs(x2 - x1), abs(y2 - y1), 1)
            for k in range(1, pasos, 2):
                xx, yy = x1 + (x2 - x1) * k // pasos, y1 + (y2 - y1) * k // pasos
                if 0 <= xx < ancho and 0 <= yy < alto and lienzo[yy][xx] == " ":
                    lienzo[yy][xx] = "·"
        for px, py, z, g in sorted(proy, key=lambda p: -p[2]):
            if 0 <= px < ancho and 0 <= py < alto:
                lienzo[py][px] = "●" if g >= 4 and z < 0 else ("•" if z < 0.2 else "∘")
        color = {"pensando": "magenta", "aprendiendo": "yellow", "escuchando": "cyan", "hablando": "green"}.get(
            self.estado, "blue")
        self.update(f"[{color}]" + "\n".join("".join(f) for f in lienzo) + "[/]")


class CerebroTUI(App):
    TITLE = "Cerebro local"
    CSS = """
    #izquierda { width: 42%; }
    #avatar { height: 16; border: round $primary; }
    #estado { height: auto; padding: 0 1; }
    #trabajos { height: 1fr; border: round $secondary; }
    #chat { height: 1fr; border: round $primary; }
    #pregunta { dock: bottom; }
    #lista_recetas { width: 30; border: round $secondary; }
    #editor { height: 1fr; }
    #barra_receta { height: 3; }
    #error_receta { color: $error; height: auto; }
    .titulo { text-style: bold; padding: 0 1; }
    """
    BINDINGS = [Binding("q", "quit", "Salir"), Binding("a", "aprender", "Aprender ahora"),
                Binding("r", "refrescar", "Refrescar"), Binding("ctrl+s", "guardar_receta", "Guardar receta")]

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url.rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(10, read=900))
        self.receta_actual: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="principal"):
            with TabPane("Principal", id="principal"):
                with Horizontal():
                    with Vertical(id="izquierda"):
                        yield Avatar(id="avatar")
                        yield Static("Conectando…", id="estado")
                        yield DataTable(id="trabajos", cursor_type="row", zebra_stripes=True)
                    with Vertical():
                        yield RichLog(id="chat", wrap=True, markup=True)
                        yield Input(placeholder="Pregunta a tu memoria y pulsa Enter…", id="pregunta")
            with TabPane("Recetas", id="recetas"):
                with Horizontal():
                    yield ListView(id="lista_recetas")
                    with Vertical():
                        yield Label("Elige una receta para editarla. Ctrl+S guarda.", id="info_receta", classes="titulo")
                        yield TextArea("", language="yaml", id="editor", show_line_numbers=True)
                        yield Static("", id="error_receta")
                        with Horizontal(id="barra_receta"):
                            yield Button("Guardar", id="guardar", variant="primary")
                            yield Input(placeholder="id de receta nueva (p. ej. ticket)", id="nueva")
                            yield Button("Crear", id="crear")
        yield Footer()

    async def on_mount(self) -> None:
        tabla = self.query_one("#trabajos", DataTable)
        tabla.add_columns("Archivo", "Receta", "Estado", "Paso")
        self.query_one("#chat", RichLog).write(
            f"[b]Cerebro local[/b] · conectado a {self.url}\nEscribe una pregunta abajo. Ejemplo: ¿qué tareas tengo pendientes?")
        await self.action_refrescar()
        self.escuchar()

    # --- datos ------------------------------------------------------------------
    async def action_refrescar(self) -> None:
        try:
            est = (await self.http.get("/api/estado")).json()
            self.pintar_estado(est)
            self.pintar_trabajos((await self.http.get("/api/trabajos")).json())
            self.query_one(Avatar).cargar((await self.http.get("/api/grafo")).json())
            await self.cargar_recetas()
        except httpx.HTTPError as e:
            self.query_one("#estado", Static).update(
                f"[red]No conecto con {self.url}[/]: {e}\nArranca el servidor con «cerebro» y pulsa r.")

    def pintar_estado(self, est: dict) -> None:
        motor = est["motor"].get("cargado") or "descargado (VRAM libre)"
        av = est.get("avatar", {})
        prep = est.get("preparacion") or {}
        lineas = [f"[b]Modo[/b] {est['modo']} · [b]Modelo[/b] {motor} · [b]GPU[/b] {est['motor']['variante']}",
                  f"[b]Cola[/b] {est['trabajos']['en_cola']} · [b]Memoria pendiente[/b] {est['memoria_pendiente']}",
                  f"[b]Avatar[/b] {ESTADOS.get(av.get('estado'), av.get('estado'))} {av.get('texto', '')}"]
        if prep.get("activo"):
            lineas.append(f"[yellow]{prep.get('texto')} {prep.get('progreso', '')}%[/]")
        if est.get("direcciones"):
            lineas.append("Desde el móvil: " + "  ".join(est["direcciones"]))
        self.query_one("#estado", Static).update("\n".join(lineas))
        self.query_one(Avatar).estado = av.get("estado", "reposo")

    def pintar_trabajos(self, lista: list[dict]) -> None:
        tabla = self.query_one("#trabajos", DataTable)
        tabla.clear()
        for t in lista[:40]:
            estado = ICONO_TRABAJO.get(t["estado"], t["estado"])
            if t.get("error"):
                estado += f": {t['error'][:40]}"
            tabla.add_row(t["archivo"][:34], t.get("receta_nombre") or "—", estado, t.get("paso") or "", key=t["id"])

    @work(exclusive=True, group="ws")
    async def escuchar(self) -> None:
        import websockets

        ws_url = self.url.replace("http", "ws", 1) + "/ws"
        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    async for crudo in ws:
                        await self.evento(json.loads(crudo))
            except Exception:
                await asyncio.sleep(3)

    async def evento(self, ev: dict) -> None:
        tipo = ev.get("tipo")
        chat = self.query_one("#chat", RichLog)
        if tipo == "avatar":
            self.query_one(Avatar).estado = ev.get("estado", "reposo")
            await self._estado_silencioso()
        elif tipo == "trabajo":
            self.pintar_trabajos((await self.http.get("/api/trabajos")).json())
        elif tipo == "aviso":
            chat.write(f"[yellow]● {ev.get('texto')}[/]")
        elif tipo == "grafo_actualizado":
            self.query_one(Avatar).cargar((await self.http.get("/api/grafo", params={"forzar": True})).json())
        elif tipo in ("preparacion", "memoria"):
            await self._estado_silencioso()
        elif tipo == "recetas":
            await self.cargar_recetas()

    async def _estado_silencioso(self) -> None:
        try:
            self.pintar_estado((await self.http.get("/api/estado")).json())
        except httpx.HTTPError:
            pass

    # --- chat -------------------------------------------------------------------
    @on(Input.Submitted, "#pregunta")
    async def enviar(self, evento: Input.Submitted) -> None:
        texto = evento.value.strip()
        if not texto:
            return
        evento.input.value = ""
        self.query_one("#chat", RichLog).write(f"\n[b cyan]Tú:[/] {texto}")
        self.preguntar(texto)

    @work(group="chat")
    async def preguntar(self, texto: str) -> None:
        chat = self.query_one("#chat", RichLog)
        try:
            r = await self.http.post("/api/preguntar", json={"texto": texto})
            if r.status_code != 200:
                chat.write(f"[red]{r.json().get('detail', r.text)}[/]")
                return
            d = r.json()
            chat.write(f"[b green]Cerebro:[/] {d['respuesta']}")
            if d.get("fuentes"):
                chat.write(f"[dim]Fuentes: {', '.join(d['fuentes'])}[/]")
        except httpx.HTTPError as e:
            chat.write(f"[red]Sin respuesta del servidor: {e}[/]")

    async def action_aprender(self) -> None:
        r = (await self.http.post("/api/memoria/aprender")).json()
        self.query_one("#chat", RichLog).write(f"[yellow]● {r['mensaje']}[/]")

    # --- recetas ------------------------------------------------------------------
    async def cargar_recetas(self) -> None:
        lista = self.query_one("#lista_recetas", ListView)
        datos = (await self.http.get("/api/recetas")).json()
        await lista.clear()
        for r in datos:
            marca = "" if r.get("valida") else " ⚠"
            await lista.append(ListItem(Label(f"{r['nombre']}{marca}"), name=r["id"]))

    @on(ListView.Selected, "#lista_recetas")
    async def abrir_receta(self, evento: ListView.Selected) -> None:
        rid = evento.item.name
        self.receta_actual = rid
        texto = (await self.http.get(f"/api/recetas/{rid}")).text
        self.query_one("#editor", TextArea).text = texto
        self.query_one("#info_receta", Label).update(f"Editando recetas/{rid}.yaml · Ctrl+S guarda")
        self.query_one("#error_receta", Static).update("")

    async def action_guardar_receta(self) -> None:
        if not self.receta_actual:
            self.query_one("#error_receta", Static).update("Elige o crea una receta primero.")
            return
        r = await self.http.put(f"/api/recetas/{self.receta_actual}", content=self.query_one("#editor", TextArea).text,
                                headers={"Content-Type": "text/plain"})
        msg = "[green]Guardada.[/]" if r.status_code == 200 else f"[red]{r.json().get('detail')}[/]"
        self.query_one("#error_receta", Static).update(msg)

    @on(Button.Pressed, "#guardar")
    async def boton_guardar(self) -> None:
        await self.action_guardar_receta()

    @on(Button.Pressed, "#crear")
    async def crear(self) -> None:
        rid = self.query_one("#nueva", Input).value.strip().lower()
        if not rid:
            return
        self.receta_actual = rid
        self.query_one("#editor", TextArea).text = (
            "nombre: Mi receta\ndescripcion: Qué hace\ncuando:\n  extensiones: [.pdf]\nprioridad: 30\n\npasos:\n"
            "  - preguntar_llm:\n      perfil: rapido\n      guardar_como: resumen\n      prompt: |\n"
            "        Resume esto: {contenido}\n  - guardar_nota:\n      titulo: \"{nombre}\"\n"
            "      contenido: \"{resumen}\"\n")
        self.query_one("#info_receta", Label).update(f"Nueva receta recetas/{rid}.yaml · Ctrl+S guarda")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="cerebro tui")
    p.add_argument("--url", default="http://localhost:8765", help="dirección del servidor de Cerebro")
    a = p.parse_args(argv)
    CerebroTUI(a.url).run()


if __name__ == "__main__":
    main()
