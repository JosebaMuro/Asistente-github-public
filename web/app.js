/* Cerebro local: interfaz. Funciona igual en el PC y en el móvil (navegador o app Android). */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
  const ESTADOS = { reposo: "En reposo", escuchando: "Escuchando", pensando: "Pensando", hablando: "Hablando", aprendiendo: "Aprendiendo" };
  const NOMBRE_ESTADO = { en_cola: "En cola", procesando: "Procesando", hecho: "Hecho", memoria_esta_noche: "Memoria esta noche", error: "Error", sin_receta: "Sin receta" };
  const guardado = { get(k, d) { try { return JSON.parse(localStorage.getItem("cerebro." + k)) ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem("cerebro." + k, JSON.stringify(v)); } catch (e) {} } };

  let grafo = { nodos: [], aristas: [] };
  const avatar = new window.Avatar($("#avatar"), { alSeleccionar: pintarDetalle });

  /* ---------- utilidades ---------- */
  async function api(ruta, opciones = {}) {
    const r = await fetch(ruta, opciones);
    const tipo = r.headers.get("content-type") || "";
    const cuerpo = tipo.includes("json") ? await r.json() : await r.text();
    if (!r.ok) throw new Error((cuerpo && cuerpo.detail) || cuerpo || r.statusText);
    return cuerpo;
  }
  let toastT;
  function toast(texto) { const t = $("#toast"); t.textContent = texto; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), 4500); }
  function msg(quien, texto, src) {
    const m = el("div", "msg " + quien, texto);
    if (src) m.append(el("span", "src", src));
    $("#registro").append(m); $("#registro").scrollTop = $("#registro").scrollHeight;
  }

  /* ---------- tiempo real ---------- */
  let ws, wsEspera = 1000;
  function conectar() {
    const url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws";
    ws = new WebSocket(url);
    ws.onopen = () => { wsEspera = 1000; $("#conexion").className = "conexion ok"; $("#conexion-texto").textContent = "Conectado"; refrescar(); };
    ws.onclose = () => { $("#conexion").className = "conexion mal"; $("#conexion-texto").textContent = "Sin conexión, reintentando"; setTimeout(conectar, wsEspera); wsEspera = Math.min(wsEspera * 2, 15000); };
    ws.onmessage = (e) => { try { evento(JSON.parse(e.data)); } catch (err) { console.error(err); } };
  }
  function enviarEstado(estado, texto = "") { try { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ tipo: "avatar", estado, texto })); } catch (e) {} }

  function evento(ev) {
    switch (ev.tipo) {
      case "avatar": pintarEstadoAvatar(ev.estado, ev.texto); break;
      case "trabajo": cargarTrabajos(); break;
      case "aviso": toast(ev.texto); msg("sistema", ev.texto); break;
      case "grafo_actualizado": cargarGrafo(true); break;
      case "memoria": pintarPendiente(ev.pendientes); break;
      case "preparacion": pintarPreparacion(ev); break;
      case "recetas": cargarRecetas(); break;
      case "respuesta": if (ev.nodos) avatar.resaltar(ev.nodos); break;
    }
  }
  function pintarEstadoAvatar(estado, texto) {
    if (!hablando || estado === "hablando") avatar.setEstado(estado || "reposo");
    const caja = $("#estado-avatar");
    caja.classList.toggle("activo", estado && estado !== "reposo");
    $("#estado-texto").textContent = (ESTADOS[estado] || estado || "En reposo") + (texto ? " · " + texto : "");
  }
  function pintarPreparacion(ev) {
    const caja = $("#preparacion");
    caja.hidden = !ev.activo;
    caja.classList.toggle("error", !!ev.error);
    $("#prep-texto").textContent = ev.texto || "";
    $("#prep-barra").style.width = (ev.progreso || 0) + "%";
  }
  function pintarPendiente(n) { $("#pendiente").textContent = n ? `${n} elemento${n === 1 ? "" : "s"} esperando a la memoria nocturna.` : ""; }

  /* ---------- datos ---------- */
  async function refrescar() {
    try {
      const e = await api("/api/estado");
      const chip = $("#modo");
      chip.textContent = e.modo === "simulado" ? "Modo simulado: datos de ejemplo" : (e.motor.cargado ? "Modelo: " + e.motor.cargado : "Modelo en espera");
      chip.classList.toggle("simulado", e.modo === "simulado");
      pintarEstadoAvatar(e.avatar.estado, e.avatar.texto);
      pintarPendiente(e.memoria_pendiente);
      if (e.preparacion && e.preparacion.activo) pintarPreparacion(e.preparacion);
    } catch (err) { console.warn(err); }
    cargarGrafo(); cargarTrabajos(); cargarRecetas(); cargarNotas();
  }
  async function cargarGrafo(forzar) {
    try {
      grafo = await api("/api/grafo" + (forzar ? "?forzar=true" : ""));
      avatar.setDatos(grafo);
      $("#vacio").hidden = grafo.nodos.length > 0;
      pintarLeyenda();
      if (!avatar.seleccionado) pintarDetalle(null);
    } catch (err) { console.warn(err); }
  }
  function pintarLeyenda() {
    const cuenta = {};
    grafo.nodos.forEach((n) => (cuenta[n.categoria] = (cuenta[n.categoria] || 0) + 1));
    const ley = $("#leyenda"); ley.replaceChildren();
    Object.entries(cuenta).sort((a, b) => b[1] - a[1]).slice(0, 7).forEach(([c, n]) => {
      const s = el("span"); const i = el("i"); i.style.background = avatar.color(c); s.append(i, `${c} ${n}`); ley.append(s);
    });
  }
  async function cargarTrabajos() {
    try {
      const lista = await api("/api/trabajos");
      const ul = $("#trabajos"); ul.replaceChildren();
      if (!lista.length) ul.append(el("li", "pista", "Aún no hay nada. Lo que captures aparecerá aquí."));
      lista.slice(0, 30).forEach((t) => {
        const li = el("li", "trabajo");
        li.append(el("span", "nombre", t.archivo));
        const meta = el("span", "meta");
        meta.append(el("span", "estado " + t.estado, NOMBRE_ESTADO[t.estado] || t.estado));
        if (t.receta_nombre) meta.append(el("span", null, t.receta_nombre));
        if (t.paso) meta.append(el("span", null, t.paso));
        li.append(meta);
        if (t.error) {
          li.append(el("span", "error", t.error));
          const b = el("button", "enlace", "Reintentar"); b.type = "button";
          b.onclick = async () => { try { await api(`/api/trabajos/${t.id}/reintentar`, { method: "POST" }); } catch (e) { toast(e.message); } };
          li.append(b);
        }
        if (t.nota) { const b = el("button", "enlace", "Ver nota"); b.type = "button"; b.onclick = () => abrirNota(t.nota); li.append(b); }
        ul.append(li);
      });
    } catch (err) { console.warn(err); }
  }

  /* ---------- detalle ---------- */
  function pintarDetalle(n) {
    const v = $("#v-detalle"); v.replaceChildren();
    if (!n) {
      v.append(el("h2", null, "Tu memoria"));
      v.append(el("p", "pista", grafo.nodos.length ? `${grafo.nodos.length} conceptos y ${grafo.aristas.length} conexiones. Toca un punto del avatar para ver qué sabe sobre él.` : "Todavía no hay nada en la memoria."));
      return;
    }
    const cab = el("div", "nodo-cab");
    const chip = el("span", "chip"); const i = el("i"); i.style.background = avatar.color(n.categoria); chip.append(i, n.categoria);
    chip.style.justifySelf = "start";
    cab.append(chip, el("h3", null, n.label));
    v.append(cab);
    if (n.desc) v.append(el("p", "nodo-desc", n.desc));
    const rel = grafo.aristas.filter((a) => a.origen === n.id || a.destino === n.id);
    if (rel.length) {
      v.append(el("h2", null, "Conectado con"));
      const caja = el("div", "enlaces");
      rel.slice(0, 40).forEach((a) => {
        const otro = avatar.porId.get(a.origen === n.id ? a.destino : a.origen); if (!otro) return;
        const b = el("button"); b.type = "button";
        const i2 = el("i"); i2.style.background = avatar.color(otro.categoria);
        b.append(i2, otro.label, el("span", "rel", " · " + (a.label || "").replace(/_/g, " ")));
        b.onclick = () => avatar.seleccionar(otro.id);
        caja.append(b);
      });
      v.append(caja);
    }
    const preg = el("button", "boton", `Preguntar por «${n.label}»`); preg.type = "button";
    preg.onclick = () => { $("#pregunta").value = `¿Qué sabes de ${n.label}?`; $("#form-pregunta").requestSubmit(); };
    const todo = el("button", "enlace", "Ver todo el grafo"); todo.type = "button"; todo.onclick = () => avatar.seleccionar(null);
    v.append(preg, todo);
  }

  /* ---------- preguntar ---------- */
  let hablando = false;
  function decir(texto) {
    if (!$("#hablar").checked) return;
    if (nativo) { // la WebView de Android no trae voces: usa el TTS del sistema
      avatar.setEstado("hablando"); enviarEstado("hablando");
      nativo.hablar(texto.replace(/[#*_`>]/g, ""));
      return;
    }
    if (!("speechSynthesis" in window)) return;
    const u = new SpeechSynthesisUtterance(texto.replace(/[#*_`>]/g, ""));
    u.lang = "es-ES";
    const voz = speechSynthesis.getVoices().find((v) => v.lang && v.lang.startsWith("es"));
    if (voz) u.voice = voz;
    u.onstart = () => { hablando = true; avatar.setEstado("hablando"); enviarEstado("hablando"); };
    u.onboundary = () => avatar.pulso();
    u.onend = u.onerror = () => { hablando = false; avatar.setEstado("reposo"); enviarEstado("reposo"); };
    speechSynthesis.cancel(); speechSynthesis.speak(u);
  }
  $("#hablar").checked = guardado.get("hablar", false);
  $("#hablar").onchange = () => guardado.set("hablar", $("#hablar").checked);

  async function preguntar(texto) {
    msg("yo", texto);
    avatar.setEstado("pensando");
    try {
      const r = await api("/api/preguntar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto }) });
      mostrarRespuesta(r);
    } catch (e) { msg("sistema", "No pude responder: " + e.message); avatar.setEstado("reposo"); }
  }
  function mostrarRespuesta(r) {
    msg("cerebro", r.respuesta, r.fuentes && r.fuentes.length ? "Fuentes: " + r.fuentes.join(", ") : null);
    avatar.resaltar(r.nodos || []);
    if (r.nodos && r.nodos.length === 1) avatar.seleccionar(r.nodos[0]);
    decir(r.respuesta);
  }
  $("#form-pregunta").addEventListener("submit", (e) => {
    e.preventDefault();
    const t = $("#pregunta").value.trim(); if (!t) return;
    $("#pregunta").value = ""; preguntar(t);
  });

  /* ---------- micrófono ---------- */
  // En la app Android graba el sistema (servicio en primer plano: sigue con la pantalla apagada)
  const nativo = window.CerebroNativo || null;
  const puedeGrabar = !!nativo || !!(window.isSecureContext && navigator.mediaDevices && window.MediaRecorder);
  if (nativo) {
    document.documentElement.classList.add("app-android");
    window.cerebroNativo = (evento, datos) => {
      if (evento === "subido") toast(`Enviado: ${datos.archivo} → ${datos.receta_nombre || "sin receta"}`);
      else if (evento === "respuesta") { msg("yo", datos.pregunta); mostrarRespuesta(datos); }
      else if (evento === "fin_voz") { avatar.setEstado("reposo"); enviarEstado("reposo"); }
      else if (evento === "error") { toast(String(datos)); avatar.setEstado("reposo"); }
    };
    const b = el("button", "enlace", "Servidor"); b.type = "button"; b.onclick = () => nativo.configurar();
    document.querySelector(".barra-der").prepend(b);
  }
  class GrabadoraNativa {
    async empezar(tipo) {
      if (!nativo.empezar(tipo)) throw new Error("concede el permiso de micrófono y vuelve a pulsar");
      this.inicio = Date.now(); this.tipo = "audio/mp4";
      this.t = setInterval(() => { try { avatar.setNivel(JSON.parse(nativo.estado()).nivel); } catch (e) {} }, 120);
    }
    parar(receta) { clearInterval(this.t); avatar.setNivel(0); nativo.parar(receta || ""); return Promise.resolve(null); }
    segundos() { return Math.floor((Date.now() - this.inicio) / 1000); }
  }
  if (!puedeGrabar) {
    const a = $("#aviso-mic"); a.hidden = false;
    a.textContent = "Para grabar desde aquí abre Cerebro por https (por ejemplo con Tailscale) o usa la app Android. Mientras tanto, los botones abren la grabadora del móvil.";
  }
  function tipoAudio() {
    for (const t of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) if (MediaRecorder.isTypeSupported(t)) return t;
    return "";
  }
  const extension = (t) => (t.includes("mp4") ? ".m4a" : t.includes("ogg") ? ".ogg" : ".webm");

  class Grabadora {
    async empezar() {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      this.tipo = tipoAudio();
      this.rec = new MediaRecorder(this.stream, this.tipo ? { mimeType: this.tipo, audioBitsPerSecond: 48000 } : undefined);
      this.trozos = []; this.rec.ondataavailable = (e) => e.data.size && this.trozos.push(e.data);
      this.rec.start(1000);
      this.inicio = Date.now();
      try { this.ctxAudio = new AudioContext(); const src = this.ctxAudio.createMediaStreamSource(this.stream); this.an = this.ctxAudio.createAnalyser(); this.an.fftSize = 512; src.connect(this.an); this.buf = new Uint8Array(this.an.fftSize); } catch (e) {}
      try { this.bloqueo = await navigator.wakeLock.request("screen"); } catch (e) {}
      this._nivel();
    }
    _nivel() {
      if (!this.rec || this.rec.state !== "recording") return;
      if (this.an) { this.an.getByteTimeDomainData(this.buf); let m = 0; for (const v of this.buf) m = Math.max(m, Math.abs(v - 128)); avatar.setNivel(m / 64); }
      requestAnimationFrame(() => this._nivel());
    }
    parar() {
      return new Promise((ok) => {
        this.rec.onstop = () => {
          this.stream.getTracks().forEach((t) => t.stop());
          try { this.ctxAudio && this.ctxAudio.close(); } catch (e) {}
          try { this.bloqueo && this.bloqueo.release(); } catch (e) {}
          avatar.setNivel(0);
          ok(new Blob(this.trozos, { type: this.tipo || "audio/webm" }));
        };
        this.rec.stop();
      });
    }
    segundos() { return Math.floor((Date.now() - this.inicio) / 1000); }
  }

  async function subir(blob, nombre, receta) {
    const fd = new FormData(); fd.append("archivo", blob, nombre); if (receta) fd.append("receta", receta);
    try { const t = await api("/api/subir", { method: "POST", body: fd }); toast(`Enviado: ${t.archivo} → ${t.receta_nombre || "sin receta"}`); }
    catch (e) { toast("No se pudo enviar: " + e.message); }
  }

  let grabacion = null, reloj = null, recetaGrabacion = null;
  async function empezarGrabacion(receta, etiqueta) {
    if (!puedeGrabar) { $("#audio-movil").dataset.receta = receta; $("#audio-movil").click(); return; }
    if (grabacion) return;
    try { grabacion = nativo ? new GrabadoraNativa() : new Grabadora(); await grabacion.empezar(receta); }
    catch (e) { grabacion = null; toast("No tengo acceso al micrófono: " + e.message); return; }
    recetaGrabacion = receta;
    $("#grabando").hidden = false;
    avatar.setEstado("escuchando"); enviarEstado("escuchando", etiqueta);
    reloj = setInterval(() => { const s = grabacion.segundos(); $("#grabando-texto").textContent = `${etiqueta} ${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; }, 500);
  }
  async function pararGrabacion() {
    if (!grabacion) return;
    clearInterval(reloj);
    const blob = await grabacion.parar(recetaGrabacion);
    const ext = extension(grabacion.tipo || "");
    grabacion = null; $("#grabando").hidden = true;
    avatar.setEstado("reposo"); enviarEstado("reposo");
    if (!blob) { toast("Enviando grabación…"); return; } // la app Android la sube por su cuenta
    const fecha = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
    await subir(blob, `${recetaGrabacion}_${fecha}${ext}`, recetaGrabacion);
  }
  $("#btn-reunion").onclick = () => empezarGrabacion("reunion", "Grabando reunión");
  $("#btn-nota").onclick = () => (grabacion ? pararGrabacion() : empezarGrabacion("nota_voz", "Nota de voz"));
  $("#btn-parar").onclick = pararGrabacion;
  $("#audio-movil").onchange = (e) => { const f = e.target.files[0]; if (f) subir(f, f.name, e.target.dataset.receta || null); e.target.value = ""; };

  // pregunta por voz: pulsar para empezar, pulsar para enviar
  let grabPregunta = null;
  $("#btn-mic").onclick = async () => {
    if (!puedeGrabar) { toast("El micrófono necesita https o la app Android."); return; }
    if (!grabPregunta) {
      try { grabPregunta = nativo ? new GrabadoraNativa() : new Grabadora(); await grabPregunta.empezar("pregunta"); } catch (e) { grabPregunta = null; toast("No tengo acceso al micrófono."); return; }
      $("#btn-mic").classList.add("activo"); avatar.setEstado("escuchando"); enviarEstado("escuchando", "Te escucho");
      return;
    }
    const blob = await grabPregunta.parar(""); const tipo = grabPregunta.tipo || ""; grabPregunta = null;
    $("#btn-mic").classList.remove("activo"); avatar.setEstado("pensando");
    if (!blob) return; // respuesta llega por window.cerebroNativo("respuesta")
    const fd = new FormData(); fd.append("audio", blob, "pregunta" + extension(tipo));
    try { const r = await api("/api/preguntar_audio", { method: "POST", body: fd }); msg("yo", r.pregunta); mostrarRespuesta(r); }
    catch (e) { msg("sistema", e.message); avatar.setEstado("reposo"); }
  };

  /* ---------- archivos y texto ---------- */
  $("#archivos").onchange = async (e) => { for (const f of e.target.files) await subir(f, f.name, null); e.target.value = ""; };
  $("#btn-texto").onclick = () => { $("#form-texto").hidden = false; $("#texto-pegado").focus(); };
  $("#cancelar-texto").onclick = () => { $("#form-texto").hidden = true; };
  $("#form-texto").addEventListener("submit", async (e) => {
    e.preventDefault();
    const texto = $("#texto-pegado").value.trim(); if (!texto) return;
    try { const t = await api("/api/texto", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto }) }); toast("Guardado: " + t.archivo); $("#texto-pegado").value = ""; $("#form-texto").hidden = true; }
    catch (err) { toast(err.message); }
  });
  // Compartir desde otras apps (PWA instalada o app Android): ?texto=...
  const params = new URLSearchParams(location.search);
  const compartido = [params.get("title"), params.get("text"), params.get("url")].filter(Boolean).join("\n");
  if (compartido) { $("#form-texto").hidden = false; $("#texto-pegado").value = compartido; history.replaceState(null, "", "/"); }
  $("#btn-aprender").onclick = async () => { try { const r = await api("/api/memoria/aprender", { method: "POST" }); toast(r.mensaje); } catch (e) { toast(e.message); } };

  /* ---------- pestañas ---------- */
  document.querySelectorAll(".pestana").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".pestana").forEach((x) => x.classList.toggle("activa", x === b));
    document.querySelectorAll(".vista").forEach((v) => (v.hidden = v.id !== "v-" + b.dataset.p));
    guardado.set("pestana", b.dataset.p);
  }));
  const pest = guardado.get("pestana", "detalle"); const bp = document.querySelector(`.pestana[data-p="${pest}"]`); if (bp) bp.click();

  /* ---------- recetas ---------- */
  let recetas = [];
  async function cargarRecetas() {
    try {
      recetas = await api("/api/recetas");
      const sel = $("#sel-receta"); const actual = sel.value;
      sel.replaceChildren(...recetas.map((r) => { const o = el("option", null, r.nombre + (r.valida ? "" : " (con errores)")); o.value = r.id; return o; }));
      if (actual && recetas.some((r) => r.id === actual)) sel.value = actual;
      if (sel.value) abrirReceta(sel.value, true);
    } catch (e) { console.warn(e); }
  }
  async function abrirReceta(id, suave) {
    const r = recetas.find((x) => x.id === id);
    $("#desc-receta").textContent = r ? (r.valida ? `${r.descripcion} · Se aplica a: ${r.extensiones.join(" ")}` : r.error) : "";
    if (suave && $("#editor-receta").dataset.id === id && $("#editor-receta").dataset.sucio === "1") return;
    try { $("#editor-receta").value = await api(`/api/recetas/${id}`); $("#editor-receta").dataset.id = id; $("#editor-receta").dataset.sucio = "0"; } catch (e) { toast(e.message); }
  }
  $("#sel-receta").onchange = (e) => abrirReceta(e.target.value);
  $("#editor-receta").oninput = () => ($("#editor-receta").dataset.sucio = "1");
  $("#editor-receta").addEventListener("keydown", (e) => {
    if (e.key === "Tab") { e.preventDefault(); const t = e.target, i = t.selectionStart; t.setRangeText("  ", i, t.selectionEnd, "end"); }
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); $("#guardar-receta").click(); }
  });
  $("#guardar-receta").onclick = async () => {
    const id = $("#editor-receta").dataset.id; const res = $("#resultado-receta");
    if (!id) return;
    try { await api(`/api/recetas/${id}`, { method: "PUT", headers: { "Content-Type": "text/plain" }, body: $("#editor-receta").value }); res.className = "resultado ok"; res.textContent = "Guardada"; $("#editor-receta").dataset.sucio = "0"; }
    catch (e) { res.className = "resultado mal"; res.textContent = e.message; }
  };
  $("#nueva-receta").onclick = () => {
    const form = el("div", "fila"); const inp = el("input"); inp.placeholder = "nombre corto, p. ej. ticket"; inp.id = "id-nueva";
    inp.style.cssText = "flex:1;min-width:0;padding:7px 10px;border-radius:10px;border:1px solid var(--line);background:var(--surface-2)";
    const ok = el("button", "boton primario", "Crear"); ok.type = "button";
    ok.onclick = () => {
      const id = inp.value.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "_"); if (!id) return;
      $("#editor-receta").dataset.id = id; $("#editor-receta").dataset.sucio = "1";
      $("#editor-receta").value = `nombre: ${inp.value.trim()}\ndescripcion: Qué hace esta receta\ncuando:\n  extensiones: [.pdf]\nprioridad: 30\n\npasos:\n  - preguntar_llm:\n      perfil: rapido\n      entrada: contenido\n      trocear: 2500\n      guardar_como: resumen\n      prompt: |\n        Resume en español en 5 viñetas:\n        {contenido}\n\n  - guardar_nota:\n      titulo: "{nombre}"\n      contenido: "{resumen}"\n\n  - recordar:\n      contenido: "{nota}"\n      de_noche: true\n`;
      $("#desc-receta").textContent = `Nueva receta: recetas/${id}.yaml. Pulsa Guardar receta para crearla.`;
      form.remove();
    };
    form.append(inp, ok); $("#v-recetas").insertBefore(form, $("#desc-receta")); inp.focus();
  };

  /* ---------- notas ---------- */
  async function cargarNotas() {
    try {
      const lista = await api("/api/notas"); const ul = $("#lista-notas"); ul.replaceChildren();
      if (!lista.length) ul.append(el("li", "pista", "Aún no hay notas."));
      lista.forEach((n) => { const li = el("li"); const b = el("button"); b.type = "button"; b.append(el("span", null, n.titulo), el("small", null, n.fecha.replace("T", " "))); b.onclick = () => abrirNota(n.ruta); li.append(b); ul.append(li); });
    } catch (e) { console.warn(e); }
  }
  async function abrirNota(ruta) {
    document.querySelector('.pestana[data-p="notas"]').click();
    try { const t = await api("/api/notas/" + ruta.split("/").map(encodeURIComponent).join("/")); const p = $("#nota-abierta"); p.textContent = t; p.hidden = false; p.scrollIntoView({ block: "nearest" }); } catch (e) { toast(e.message); }
  }
  setInterval(cargarNotas, 60000);

  msg("sistema", "Pregúntame lo que quieras sobre tus reuniones, notas y capturas.");
  conectar();
  if ("serviceWorker" in navigator) { /* sin service worker: siempre muestra lo último del PC */ }
})();
