/* Avatar: el grafo de Cognee flotando en 3D, dibujado en canvas 2D sin librerías.
   Estados: reposo · escuchando · pensando · hablando · aprendiendo */
(function () {
  "use strict";
  const CATEGORIAS = {
    persona: "--c-persona", "organización": "--c-org", organizacion: "--c-org", empresa: "--c-org",
    tema: "--c-tema", concepto: "--c-tema", "decisión": "--c-decision", decision: "--c-decision",
    tarea: "--c-tarea", fecha: "--c-fecha", evento: "--c-fecha", lugar: "--c-lugar", ubicacion: "--c-lugar",
    fuente: "--c-fuente", tipo: "--c-tipo"
  };
  const EXTRA = ["--c-persona", "--c-tema", "--c-org", "--c-tarea", "--c-decision", "--c-lugar", "--c-fecha"];

  function hash(s) { let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) | 0; return Math.abs(h); }
  function tokenDe(cat) { return CATEGORIAS[cat] || EXTRA[hash(cat || "x") % EXTRA.length]; }

  class Avatar {
    constructor(canvas, opciones = {}) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.nodos = []; this.aristas = []; this.porId = new Map(); this.vecinos = new Map();
      this.yaw = 0.6; this.pitch = -0.22; this.zoom = 1; this.t = 0;
      this.estado = "reposo"; this.nivel = 0; this.energia = 0;
      this.seleccionado = null; this.encima = null; this.resaltados = new Set();
      this.particulas = [];
      this.alSeleccionar = opciones.alSeleccionar || (() => {});
      this.reducido = matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.colores = {};
      this._leerColores();
      new ResizeObserver(() => this._medir()).observe(canvas.parentElement);
      try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => this._leerColores()); } catch (e) {}
      this._eventos();
      this._medir();
      this._ultimo = performance.now();
      requestAnimationFrame((t) => this._bucle(t));
    }

    _leerColores() {
      const s = getComputedStyle(document.documentElement);
      const g = (n) => s.getPropertyValue(n).trim();
      this.colores = { tinta: g("--ink"), suave: g("--muted"), fondo: g("--bg"), sombra: g("--shadow"), acento: g("--accent") };
      this.colorToken = {};
      for (const k of new Set([...Object.values(CATEGORIAS), ...EXTRA])) this.colorToken[k] = g(k);
    }
    color(cat) { return this.colorToken[tokenDe(cat)] || this.colores.acento; }

    _medir() {
      const r = this.canvas.parentElement.getBoundingClientRect();
      this.dpr = Math.min(window.devicePixelRatio || 1, 2);
      this.W = r.width; this.H = r.height;
      this.canvas.width = Math.round(this.W * this.dpr);
      this.canvas.height = Math.round(this.H * this.dpr);
      this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    }

    /* Datos: conserva posiciones de nodos que ya existían */
    setDatos(datos) {
      const viejos = this.porId;
      this.nodos = (datos.nodos || []).map((n) => {
        const v = viejos.get(n.id);
        return Object.assign({}, n, v ? { x: v.x, y: v.y, z: v.z } : { x: (Math.random() - 0.5) * 200, y: (Math.random() - 0.5) * 200, z: (Math.random() - 0.5) * 200, nuevo: !!viejos.size });
      });
      this.porId = new Map(this.nodos.map((n) => [n.id, n]));
      this.aristas = (datos.aristas || []).filter((a) => this.porId.has(a.origen) && this.porId.has(a.destino));
      this.vecinos = new Map(this.nodos.map((n) => [n.id, new Set()]));
      for (const a of this.aristas) { this.vecinos.get(a.origen).add(a.destino); this.vecinos.get(a.destino).add(a.origen); }
      for (const n of this.nodos) { // los nuevos aparecen junto a un vecino
        if (n.nuevo) { const v = [...this.vecinos.get(n.id)].map((id) => this.porId.get(id)).find((m) => !m.nuevo); if (v) { n.x = v.x + 8; n.y = v.y + 8; n.z = v.z; } }
      }
      this._simular(viejos.size ? 160 : 420);
      if (this.seleccionado && !this.porId.has(this.seleccionado)) this.seleccionar(null);
    }

    _simular(pasos) {
      const N = this.nodos.length; if (!N) return;
      const rep = 2600 * Math.max(0.35, Math.min(1, 40 / N));
      for (let it = 0; it < pasos; it++) {
        const a = 1 - it / pasos;
        for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
          const p = this.nodos[i], q = this.nodos[j];
          let dx = p.x - q.x, dy = p.y - q.y, dz = p.z - q.z;
          const d2 = Math.max(dx * dx + dy * dy + dz * dz, 1), d = Math.sqrt(d2), f = Math.min(rep / d2, 8) * a;
          dx /= d; dy /= d; dz /= d;
          p.x += dx * f; p.y += dy * f; p.z += dz * f; q.x -= dx * f; q.y -= dy * f; q.z -= dz * f;
        }
        for (const e of this.aristas) {
          const p = this.porId.get(e.origen), q = this.porId.get(e.destino);
          const dx = q.x - p.x, dy = q.y - p.y, dz = q.z - p.z, d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
          const k = 0.06 * (d - 60) / d * a;
          p.x += dx * k; p.y += dy * k; p.z += dz * k; q.x -= dx * k; q.y -= dy * k; q.z -= dz * k;
        }
        for (const n of this.nodos) { n.x *= 0.995; n.y *= 0.995; n.z *= 0.995; }
      }
      let r = 1; for (const n of this.nodos) r = Math.max(r, Math.hypot(n.x, n.y, n.z));
      const s = 150 / r;
      this.nodos.forEach((n, i) => { n.x *= s; n.y *= s; n.z *= s; n.fase = i * 1.7; n.nuevo = false; });
    }

    setEstado(e) { if (e !== this.estado) { this.estado = e; if (e === "hablando") this.energia = 1; } }
    setNivel(v) { this.nivel = Math.max(0, Math.min(1, v)); }
    pulso() { this.energia = Math.min(1.4, this.energia + 0.6); }
    resaltar(ids) {
      this.resaltados = new Set(ids || []);
      for (const id of this.resaltados) this._chispas(id, 3);
    }
    seleccionar(id) { this.seleccionado = id && this.porId.has(id) ? id : null; this.alSeleccionar(this.seleccionado ? this.porId.get(this.seleccionado) : null); }

    _chispas(id, n) {
      const vs = [...(this.vecinos.get(id) || [])];
      for (let i = 0; i < n && vs.length; i++) this.particulas.push({ a: id, b: vs[(Math.random() * vs.length) | 0], t: 0, v: 0.6 + Math.random() * 0.8 });
    }

    _proyectar(n, fit) {
      const bob = this.reducido ? 0 : Math.sin(this.t * 1.1 + n.fase) * 3;
      const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw), cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
      const x1 = n.x * cy + n.z * sy, z1 = -n.x * sy + n.z * cy, y0 = n.y + bob;
      const y1 = y0 * cp - z1 * sp, z2 = y0 * sp + z1 * cp;
      const s = 460 / (460 + z2);
      const lift = this.reducido ? 0 : Math.sin(this.t * 0.7) * 7;
      return { x: this.W / 2 + x1 * s * fit, y: this.H / 2 - 10 + y1 * s * fit + lift, z: z2, s: s * fit };
    }

    _bucle(ahora) {
      const dt = Math.min(0.05, (ahora - this._ultimo) / 1000); this._ultimo = ahora;
      if (!this.reducido) {
        this.t += dt;
        const vel = { reposo: 0.1, escuchando: 0.06, pensando: 0.55, hablando: 0.14, aprendiendo: 0.25 }[this.estado] || 0.1;
        if (!this._arrastrando) this.yaw += dt * vel;
      }
      this.energia *= Math.pow(0.08, dt);
      const tasa = { pensando: 14, aprendiendo: 6, hablando: 4 }[this.estado] || 0.4;
      if (this.nodos.length && Math.random() < tasa * dt) {
        const pool = this.resaltados.size ? [...this.resaltados] : this.nodos.map((n) => n.id);
        this._chispas(pool[(Math.random() * pool.length) | 0], 1);
      }
      this._dibujar();
      requestAnimationFrame((t) => this._bucle(t));
    }

    _dibujar() {
      const { ctx, W, H } = this; if (!W || !H) return;
      ctx.clearRect(0, 0, W, H);
      let escala = 1 + (this.reducido ? 0 : Math.sin(this.t * 1.6) * 0.012);
      if (this.estado === "escuchando") escala += this.nivel * 0.14;
      escala += this.energia * 0.05;
      const fit = Math.min(W, H) / 380 * this.zoom * escala;

      // sombra en el suelo: levita
      const lift = this.reducido ? 0 : Math.sin(this.t * 0.7);
      const shW = 150 * fit * (1 - lift * 0.05), shY = H / 2 + 172 * fit;
      if (shY < H - 4 && this.nodos.length) {
        ctx.save(); ctx.translate(W / 2, shY); ctx.scale(1, 0.15);
        const g = ctx.createRadialGradient(0, 0, 0, 0, 0, shW);
        g.addColorStop(0, this.colores.sombra); g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.globalAlpha = 0.55 - lift * 0.12; ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(0, 0, shW, 0, Math.PI * 2); ctx.fill(); ctx.restore();
      }
      // halo según estado
      if (this.estado !== "reposo") {
        const r = 175 * fit;
        const g = ctx.createRadialGradient(W / 2, H / 2, r * 0.2, W / 2, H / 2, r * 1.2);
        g.addColorStop(0, "rgba(0,0,0,0)"); g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.globalAlpha = 0.18 + this.energia * 0.2 + this.nivel * 0.3;
        ctx.strokeStyle = this.colores.acento; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(W / 2, H / 2 - 10, r * (1.02 + this.energia * 0.04), 0, Math.PI * 2); ctx.stroke();
      }

      const P = new Map(); for (const n of this.nodos) P.set(n.id, this._proyectar(n, fit));
      const sel = this.seleccionado, foco = sel ? this.vecinos.get(sel) : null;
      const hay = this.resaltados.size > 0;
      const encendido = (id) => (sel ? id === sel || foco.has(id) : !hay || this.resaltados.has(id));

      ctx.lineCap = "round";
      for (const e of this.aristas) {
        const p = P.get(e.origen), q = P.get(e.destino);
        const lit = sel ? (e.origen === sel || e.destino === sel) : hay && this.resaltados.has(e.origen) && this.resaltados.has(e.destino);
        const prof = Math.max(0.15, Math.min(1, ((p.s + q.s) / 2) / fit));
        ctx.globalAlpha = lit ? 0.95 : (sel || hay ? 0.07 : 0.3 * prof);
        ctx.strokeStyle = lit ? this.color(this.porId.get(e.origen === sel ? e.destino : e.origen).categoria) : this.colores.suave;
        ctx.lineWidth = lit ? 1.8 : 1;
        ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke();
      }
      // partículas que viajan por las conexiones
      const dt = 1 / 60;
      this.particulas = this.particulas.filter((k) => (k.t += dt * k.v) < 1 && P.has(k.a) && P.has(k.b));
      for (const k of this.particulas) {
        const p = P.get(k.a), q = P.get(k.b);
        const x = p.x + (q.x - p.x) * k.t, y = p.y + (q.y - p.y) * k.t;
        ctx.globalAlpha = Math.sin(k.t * Math.PI);
        ctx.fillStyle = this.color(this.porId.get(k.b).categoria);
        ctx.beginPath(); ctx.arc(x, y, 2.2, 0, Math.PI * 2); ctx.fill();
      }
      const orden = this.nodos.slice().sort((a, b) => P.get(b.id).z - P.get(a.id).z);
      const muchos = this.nodos.length > 150;
      for (const n of orden) {
        const p = P.get(n.id), r = (3 + Math.min(n.grado || 0, 14) * 0.7) * p.s; p.r = r;
        const lit = encendido(n.id), marcado = this.resaltados.has(n.id);
        ctx.globalAlpha = lit ? 1 : 0.16;
        const c = this.color(n.categoria);
        ctx.fillStyle = c;
        ctx.shadowColor = c; ctx.shadowBlur = lit && (!muchos || marcado || n.id === sel) ? r * 1.6 : 0;
        ctx.beginPath(); ctx.arc(p.x, p.y, r * (marcado ? 1.25 : 1), 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
        if (n.id === sel || n.id === this.encima) {
          ctx.globalAlpha = 1; ctx.strokeStyle = this.colores.tinta; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.arc(p.x, p.y, r + 4, 0, Math.PI * 2); ctx.stroke();
        }
      }
      // etiquetas: seleccionado y vecinos, resaltados, o los más conectados
      const top = new Set(this.nodos.slice().sort((a, b) => (b.grado || 0) - (a.grado || 0)).slice(0, 10).map((n) => n.id));
      ctx.textBaseline = "middle"; ctx.lineJoin = "round";
      for (const n of orden) {
        const p = P.get(n.id);
        const fuerte = n.id === sel || n.id === this.encima || this.resaltados.has(n.id);
        const ver = fuerte || (sel ? foco.has(n.id) : (!hay && top.has(n.id) && p.s / fit > 0.95));
        if (!ver) continue;
        ctx.globalAlpha = fuerte ? 1 : 0.8;
        ctx.font = (fuerte ? "600 13px " : "500 11.5px ") + "Inter, 'Segoe UI', system-ui, sans-serif";
        const tx = p.x + p.r + 6;
        ctx.lineWidth = 3; ctx.strokeStyle = this.colores.fondo; ctx.strokeText(n.label, tx, p.y);
        ctx.fillStyle = this.colores.tinta; ctx.fillText(n.label, tx, p.y);
      }
      ctx.globalAlpha = 1;
    }

    _eventos() {
      const c = this.canvas;
      let x0 = 0, y0 = 0, lx = 0, ly = 0, movido = 0;
      const local = (e) => { const r = c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
      const tocar = (x, y) => {
        let mejor = null, bd = Infinity;
        const fit = Math.min(this.W, this.H) / 380 * this.zoom;
        for (const n of this.nodos) { const p = this._proyectar(n, fit); const d = Math.hypot(p.x - x, p.y - y); const r = (3 + Math.min(n.grado || 0, 14) * 0.7) * p.s; if (d < r + 9 && d < bd) { bd = d; mejor = n.id; } }
        return mejor;
      };
      c.addEventListener("pointerdown", (e) => { this._arrastrando = true; movido = 0; [x0, y0] = local(e); lx = x0; ly = y0; c.setPointerCapture(e.pointerId); c.classList.add("arrastrando"); });
      c.addEventListener("pointermove", (e) => {
        const [x, y] = local(e);
        if (this._arrastrando) { const dx = x - lx, dy = y - ly; lx = x; ly = y; movido += Math.abs(dx) + Math.abs(dy); this.yaw += dx * 0.008; this.pitch = Math.max(-1.2, Math.min(1.2, this.pitch + dy * 0.008)); }
        else { const h = tocar(x, y); if (h !== this.encima) { this.encima = h; c.style.cursor = h ? "pointer" : ""; } }
      });
      c.addEventListener("pointerup", (e) => { if (!this._arrastrando) return; this._arrastrando = false; c.classList.remove("arrastrando"); if (movido < 6) { const [x, y] = local(e); this.seleccionar(tocar(x, y)); } });
      c.addEventListener("pointercancel", () => { this._arrastrando = false; c.classList.remove("arrastrando"); });
      c.addEventListener("wheel", (e) => { e.preventDefault(); this.zoom = Math.max(0.5, Math.min(2.4, this.zoom * (e.deltaY < 0 ? 1.08 : 0.93))); }, { passive: false });
    }
  }
  Avatar.tokenDe = tokenDe;
  window.Avatar = Avatar;
})();
