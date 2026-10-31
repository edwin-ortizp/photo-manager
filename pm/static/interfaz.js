// Navegación y superficies: no contiene escrituras de archivos ni reintentos de POST.
const ui = {
  seccion: "fotos", capas: [], aplicando: false, detalle: false, visorId: null,
  filas: [], alto: 0, marco: 0, inicio: -1, fin: -1, columnas: 3,
  revisionSeleccion: 0, ultimaCantidad: 0,
  zoom: 1, x: 0, y: 0, puntos: new Map(), foco: new Map(), scroll: {},
};
const movil = () => matchMedia("(max-width: 767px)").matches;
const compacto = () => matchMedia("(max-width: 1099px)").matches;
const principal = $("main");

function estadoGaleria(texto, error = false) {
  $("#estado-galeria").hidden = !texto;
  $("#estado-galeria").classList.toggle("con-fotos", estado.fotos.length > 0);
  $("#estado-galeria span").textContent = texto;
  $("#reintentar-galeria").hidden = !error;
}
$("#reintentar-galeria").onclick = async () => {
  try { await cargarResumen(); await cargarMas(); }
  catch { estadoGaleria("No se pudo conectar con el PC.", true); }
};
function guardarHistoria() {
  history.replaceState({ ...history.state, pm: true, seccion: ui.seccion, capas: [...ui.capas],
    scroll: principal.scrollTop, seleccion: [...estado.sel], revisionSeleccion: ui.revisionSeleccion, visorId: ui.visorId }, "");
}
function abrirSuperficie(nombre) {
  if (ui.aplicando || ui.capas.includes(nombre)) return;
  guardarHistoria();
  ui.foco.set(nombre, document.activeElement);
  ui.capas.push(nombre);
  history.pushState({ ...history.state, capas: [...ui.capas] }, "");
  aplicarAccesibilidad();
}
function cerrarSuperficie(nombre) {
  if (ui.capas.includes(nombre)) {
    history.go(-(ui.capas.length - ui.capas.indexOf(nombre)));
  } else {
    if (nombre === "detalle") { if (ui.capas.includes("seleccion")) { cerrarSuperficie("seleccion"); return; } ui.detalle = false; estado.sel.clear(); pintarSeleccion(); }
    if (nombre === "visor") { $("#visor").hidden = true; ui.visorId = null; }
    aplicarAccesibilidad();
  }
}
function aplicarAccesibilidad() {
  const visor = !$("#visor").hidden;
  const detalle = !$("#detalle").hidden && (compacto() || visor);
  const dialogo = !!document.querySelector("dialog[open]");
  for (const nodo of [principal, $("#lateral"), $("#navegacion")]) nodo.inert = visor || detalle || dialogo;
  $("#visor").inert = detalle || dialogo;
  $("#detalle").inert = dialogo;
  $("#detalle").setAttribute("role", detalle ? "dialog" : "complementary");
  document.body.classList.toggle("visor-abierto", visor);
  if (detalle) $("#detalle").setAttribute("aria-modal", "true");
  else $("#detalle").removeAttribute("aria-modal");
}
function cambiarSeccion(nombre, historial = true) {
  if (!movil()) nombre = "fotos";
  if (nombre === ui.seccion) return;
  ui.scroll[ui.seccion] = principal.scrollTop;
  if (historial) guardarHistoria();
  ui.seccion = nombre;
  document.body.dataset.seccion = nombre;
  $("#seccion-titulo").textContent = !movil() ? "Fotos" : nombre === "gestionar" ? "Gestionar" : "Explorar";
  for (const b of document.querySelectorAll("#navegacion button")) {
    if (b.dataset.seccion === nombre) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  }
  principal.scrollTop = ui.scroll[nombre] || 0;
  if (historial) history.pushState({ ...history.state, seccion: nombre, scroll: principal.scrollTop }, "");
  programarFilas();
}
for (const b of document.querySelectorAll("#navegacion button")) b.onclick = () => cambiarSeccion(b.dataset.seccion);
$("#navegacion .marca").onclick = e => { e.preventDefault(); cambiarSeccion("fotos"); filtrar({ bandeja: "todas", carpeta: "", etiqueta: "", q: "" }); };
function actualizarColecciones() {
  const q = $("#buscar-carpetas").value.trim().toLocaleLowerCase();
  for (const li of document.querySelectorAll("#carpetas li")) li.hidden = !li.firstChild.textContent.toLocaleLowerCase().includes(q);
}
$("#buscar-carpetas").oninput = actualizarColecciones;

// Mantener los diálogos existentes y sus guardas de ocupado/confirmación.
for (const dialogo of document.querySelectorAll("dialog")) {
  const mostrar = dialogo.showModal.bind(dialogo);
  const cerrar = dialogo.close.bind(dialogo);
  dialogo.showModal = () => {
    mostrar(); abrirSuperficie(dialogo.id); aplicarAccesibilidad();
  };
  dialogo.close = valor => {
    if (!ui.aplicando && ui.capas.includes(dialogo.id)) cerrarSuperficie(dialogo.id);
    else { cerrar(valor); aplicarAccesibilidad(); }
  };
  dialogo.addEventListener("cancel", e => {
    if (!ui.aplicando) queueMicrotask(() => { if (!e.defaultPrevented) cerrarSuperficie(dialogo.id); });
    // El evento nativo cierra el diálogo; su cierre se sincroniza con el historial.
  });
  dialogo.addEventListener("close", () => {
    if (!ui.aplicando && ui.capas.includes(dialogo.id)) cerrarSuperficie(dialogo.id);
    aplicarAccesibilidad();
  });
}
window.addEventListener("popstate", async e => {
  const destino = e.state || { seccion: "fotos", capas: [] };
  const capas = destino.capas || [];
  // Atrás respeta las mismas restricciones que el botón Cerrar mientras hay trabajo.
  for (const d of document.querySelectorAll("dialog[open]")) {
    if (capas.includes(d.id)) continue;
    const cancelar = new Event("cancel", { cancelable: true });
    // No disparar el sincronizador de cancelación mientras se valida la guarda.
    ui.aplicando = true;
    d.dispatchEvent(cancelar);
    ui.aplicando = false;
    if (cancelar.defaultPrevented) { history.forward(); return; }
  }
  ui.aplicando = true;
  const cerradas = ui.capas.filter(c => !capas.includes(c));
  ui.capas = [...capas];
  for (const d of document.querySelectorAll("dialog")) {
    if (d.open && !capas.includes(d.id)) d.close();
    else if (!d.open && capas.includes(d.id)) d.showModal();
  }
  if (!capas.includes("visor")) { $("#visor").hidden = true; ui.visorId = null; }
  ui.detalle = capas.includes("detalle");
  if (!capas.includes("seleccion") && !capas.includes("detalle")) estado.sel.clear();
  cambiarSeccion(destino.seccion || "fotos", false);
  const antes = JSON.stringify(estado.filtro);
  try {
    await leerURL();
    if (antes !== JSON.stringify(estado.filtro)) {
      await recargar(false);
      // Restaurar también posiciones más allá del primer lote.
      while (principal.scrollHeight < (destino.scroll || 0) + principal.clientHeight && estado.fotos.length < estado.total) {
        const antes = estado.fotos.length; await cargarMas(); if (estado.fotos.length === antes) break;
      }
      cargarResumen().catch(() => aviso("No se pudo actualizar el resumen del PC.", true));
    }
    if (capas.includes("seleccion") || capas.includes("detalle")) {
      const ids = (destino.revisionSeleccion || 0) === ui.revisionSeleccion ? destino.seleccion || [...estado.sel] : [];
      estado.sel = new Set(ids.filter(id => estado.fotos.some(f => f.id === id)));
    }
    if (capas.includes("visor") && $("#visor").hidden && destino.visorId) {
      const i = estado.fotos.findIndex(f => f.id === destino.visorId); if (i >= 0) mostrarVisor(i);
    }
    if (!estado.sel.size) {
      ui.capas = ui.capas.filter(c => !["seleccion", "detalle"].includes(c)); ui.detalle = false;
    }
    pintarSeleccion();
    if (typeof destino.scroll === "number") principal.scrollTop = destino.scroll;
  } catch {
    estadoGaleria("No se pudo recuperar la vista. Comprueba la conexión con el PC.", true);
  } finally { ui.aplicando = false; }
  aplicarAccesibilidad(); programarFilas();
  const foco = ui.foco.get(cerradas[0]);
  if (foco?.isConnected && !foco.closest("[hidden]")) foco.focus({ preventScroll: true });
  else if (cerradas.includes("visor")) document.querySelector(`.foto[data-id="${ui.ultimoVisor}"]`)?.focus({ preventScroll: true });
});

function actualizarSeleccionUI(n) {
  if (!n && ui.ultimaCantidad && !ui.aplicando) ui.revisionSeleccion++;
  ui.ultimaCantidad = n;
  if (n && !ui.capas.includes("seleccion") && $("#visor").hidden) abrirSuperficie("seleccion");
  $("#seleccion-barra").hidden = !n || !movil();
  $("#seleccion-cantidad").textContent = `${n} seleccionada${n === 1 ? "" : "s"}`;
  $("#detalle").hidden = !n || ((movil() || !$("#visor").hidden) && !ui.detalle);
  document.body.classList.toggle("con-detalle", n > 0 && !compacto());
  if (!n && ui.capas.includes("seleccion") && !ui.aplicando) {
    ui.capas = ui.capas.filter(c => !["seleccion", "detalle"].includes(c)); guardarHistoria();
  }
  if (!ui.aplicando) guardarHistoria();
  aplicarAccesibilidad();
}
function abrirDetalle() {
  if (!estado.sel.size) return;
  ui.detalle = true; pintarSeleccion(); abrirSuperficie("detalle");
  $("#detalle").hidden = false; aplicarAccesibilidad(); $("#sel-limpiar").focus();
}
$("#seleccion-acciones").onclick = abrirDetalle;
$("#seleccion-cancelar").onclick = () => cerrarSuperficie("seleccion");
$("#detalle-ampliar").onclick = () => $("#detalle").classList.toggle("ampliado");
$("#visor-detalle").onclick = () => {
  estado.sel = new Set([ui.visorId]); pintarSeleccion(); abrirDetalle();
};

// Filas virtualizadas. Cada entrada conserva altura aun estando fuera del DOM.
function reiniciarCronologia() { ui.filas = []; ui.inicio = -1; ui.fin = -1; }
function reconstruirCronologia() {
  if (!principal.clientWidth) return;
  const ancho = $("#rejilla").clientWidth - (movil() ? 8 : 32);
  ui.columnas = movil() ? (innerWidth > innerHeight ? 5 : 3) : Math.max(1, Math.floor((ancho + 4) / (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--tam")) + 4)));
  const altoFoto = (ancho - (ui.columnas - 1) * 4) / ui.columnas + 4;
  ui.filas = []; let dia = null; let fila = null; let y = 0;
  estado.fotos.forEach((f, i) => {
    const fecha = diaDe(f);
    if (fecha !== dia) {
      dia = fecha; fila = null;
      const alto = movil() ? 60 : 42;
      ui.filas.push({ dia, y, alto }); y += alto;
    }
    if (!fila || fila.indices.length === ui.columnas) {
      fila = { indices: [], y, alto: altoFoto }; ui.filas.push(fila); y += altoFoto;
    }
    fila.indices.push(i);
  });
  ui.alto = y; ui.inicio = -1; ui.fin = -1; pintarFilas();
}
function revelarFoto(id) {
  const i = estado.fotos.findIndex(f => f.id === id);
  const fila = ui.filas.find(f => f.indices?.includes(i));
  if (!fila) return;
  if (!document.querySelector(`.foto[data-id="${id}"]`)) {
    principal.scrollTop = fila.y + $("#barra").offsetHeight;
    pintarFilas();
  }
  document.querySelector(`.foto[data-id="${id}"]`)?.scrollIntoView({ block: "nearest" });
}
function programarFilas() {
  if (!ui.marco) ui.marco = requestAnimationFrame(() => { ui.marco = 0; pintarFilas(); });
}
function pintarFilas() {
  if (movil() && ui.seccion !== "fotos") return;
  if (!ui.filas.length) { $("#rejilla").replaceChildren(); return; }
  const rejilla = $("#rejilla");
  const origen = principal.scrollTop + rejilla.getBoundingClientRect().top - principal.getBoundingClientRect().top;
  const desde = Math.max(0, principal.scrollTop - origen - 700);
  const hasta = principal.scrollTop - origen + principal.clientHeight + 700;
  let a = 0, b = ui.filas.length;
  while (a < b) { const m = (a + b) >> 1; if (ui.filas[m].y + ui.filas[m].alto < desde) a = m + 1; else b = m; }
  const inicio = Math.min(a, ui.filas.length - 1);
  let fin = inicio;
  while (fin < ui.filas.length && ui.filas[fin].y < hasta) fin++;
  if (inicio === ui.inicio && fin === ui.fin) return;
  const focoId = document.activeElement?.closest(".foto")?.dataset.id;
  ui.inicio = inicio; ui.fin = fin;
  const espacio = alto => { const d = el("div", { className: "espacio-virtual" }); d.style.height = `${Math.max(0, alto)}px`; d.setAttribute("aria-hidden", "true"); return d; };
  const nodos = [espacio(ui.filas[inicio].y)];
  for (let k = inicio; k < fin; k++) {
    const f = ui.filas[k];
    if (f.dia) {
      const boton = el("button", { textContent: movil() ? "Seleccionar cargadas" : f.dia.length === 10 ? "Seleccionar día" : "Seleccionar grupo", title: "Seleccionar únicamente las fotos cargadas de esta fecha" });
      boton.setAttribute("aria-label", `Seleccionar fotos cargadas: ${formatoDia(f.dia)}`);
      boton.onclick = () => seleccionarDia(f.dia);
      nodos.push(el("div", { className: "dia" }, el("strong", { textContent: formatoDia(f.dia) }), boton));
    } else {
      const grupo = el("div", { className: "grupo fila-virtual" }, ...f.indices.map(i => celda(estado.fotos[i], i)));
      grupo.style.gridTemplateColumns = `repeat(${ui.columnas}, minmax(0, 1fr))`;
      grupo.style.height = `${f.alto}px`; nodos.push(grupo);
    }
  }
  const ultimo = ui.filas[fin - 1];
  nodos.push(espacio(ui.alto - (ultimo ? ultimo.y + ultimo.alto : ui.filas[inicio].y)));
  rejilla.replaceChildren(...nodos);
  if (focoId) rejilla.querySelector(`[data-id="${focoId}"]`)?.focus({ preventScroll: true });
  if (principal.scrollTop + principal.clientHeight > principal.scrollHeight - 900 && !estado.cargando && estado.fotos.length < estado.total) cargarMas();
}
principal.addEventListener("scroll", programarFilas, { passive: true });
let anchoAnterior = 0;
new ResizeObserver(() => {
  const ancho = principal.clientWidth;
  if (ancho !== anchoAnterior) { anchoAnterior = ancho; reconstruirCronologia(); actualizarSeleccionUI(estado.sel.size); }
}).observe(principal);
$("#tamano").addEventListener("input", reconstruirCronologia);
let dispositivoMovil;
function actualizarDispositivo() {
  const esMovil = movil();
  if (esMovil !== dispositivoMovil) {
    dispositivoMovil = esMovil;
    if (!esMovil) {
      cambiarSeccion("fotos", false);
      ui.detalle = false;
      ui.capas = ui.capas.filter(c => c !== "detalle");
    }
    $("#seccion-titulo").textContent = esMovil ? ui.seccion === "gestionar" ? "Gestionar" : "Explorar" : "Fotos";
    $("#visor .cerrar").textContent = esMovil ? "←" : "×";
    $("#visor").classList.remove("sin-controles");
    const fotoAbierta = estado.fotos.find(f => f.id === ui.visorId);
    if (fotoAbierta) pintarInfoVisor(fotoAbierta);
    $("#administrar-etiquetas").textContent = esMovil ? "Administrar etiquetas" : "Administrar";
    $("#lateral > details.solo-explorar").open = esMovil;
    guardarHistoria();
  }
  reconstruirCronologia(); actualizarSeleccionUI(estado.sel.size);
}
window.addEventListener("resize", actualizarDispositivo);
actualizarDispositivo();

function enlazarFoto(nodo, indice) {
  let timer, inicio, consumido = false, tactil = false;
  const cancelar = () => { clearTimeout(timer); timer = null; };
  nodo.addEventListener("pointerdown", e => {
    tactil = movil() && e.pointerType !== "mouse"; consumido = false; ui.suprimirClick = null;
    if (!tactil) return;
    inicio = { x: e.clientX, y: e.clientY };
    timer = setTimeout(() => {
      estado.sel.add(estado.fotos[indice].id); estado.ultimo = indice;
      pintarSeleccion(); consumido = true;
      ui.suprimirClick = { id: estado.fotos[indice].id, hasta: performance.now() + 1000 };
    }, 450);
  });
  nodo.addEventListener("pointermove", e => {
    if (inicio && Math.hypot(e.clientX - inicio.x, e.clientY - inicio.y) > 10) { cancelar(); consumido = true; }
  });
  nodo.addEventListener("pointerup", cancelar);
  nodo.addEventListener("pointercancel", () => { cancelar(); consumido = true; });
  nodo.addEventListener("pointerleave", cancelar);
  nodo.addEventListener("contextmenu", e => { if (tactil) e.preventDefault(); });
  nodo.onclick = e => { if (ui.suprimirClick?.id === estado.fotos[indice].id && performance.now() < ui.suprimirClick.hasta) { ui.suprimirClick = null; return; } if (!consumido) clicFoto(indice, { ctrlKey: e.ctrlKey, metaKey: e.metaKey, shiftKey: e.shiftKey, tactil: movil() && (tactil || e.pointerType === "touch") }); consumido = false; };
}

// Visor: imagen abierta por ID, miniatura inmediata y precarga acotada.
let versionImagen = 0;
function transformarImagen() {
  const superficie = $("#visor-superficie"), img = $("#visor-img");
  const limiteX = Math.max(0, (img.clientWidth * ui.zoom - superficie.clientWidth) / 2);
  const limiteY = Math.max(0, (img.clientHeight * ui.zoom - superficie.clientHeight) / 2);
  ui.x = Math.max(-limiteX, Math.min(limiteX, ui.x)); ui.y = Math.max(-limiteY, Math.min(limiteY, ui.y));
  img.style.transform = `translate(${ui.x}px, ${ui.y}px) scale(${ui.zoom})`;
}
function reiniciarZoom() { ui.zoom = 1; ui.x = ui.y = 0; ui.puntos.clear(); transformarImagen(); }
function mostrarVisor(i) {
  const f = estado.fotos[i]; if (!f) return;
  const nuevo = $("#visor").hidden;
  if (nuevo) ui.detalle = false;
  clearTimeout(toqueTimer); ultimoToque = 0;
  estado.visor = i; ui.visorId = f.id; ui.ultimoVisor = f.id;
  $("#visor").hidden = false; $("#visor").classList.remove("sin-controles");
  actualizarSeleccionUI(estado.sel.size);
  reiniciarZoom(); cargarImagenVisor(f);
  $("#visor-posicion").textContent = `${i + 1} / ${estado.total}`;
  pintarInfoVisor(f);
  $("#visor .ant").disabled = i === 0;
  $("#visor .sig").disabled = i === estado.total - 1;
  if (nuevo) { abrirSuperficie("visor"); $("#visor .cerrar").focus(); }
  if (!ui.aplicando) guardarHistoria();
  aplicarAccesibilidad();
  for (const vecino of [estado.fotos[i - 1], estado.fotos[i + 1]]) {
    if (vecino) { const img = new Image(); img.src = `/api/miniatura/${vecino.id}?lado=1024`; }
  }
  if (i >= estado.fotos.length - 3 && estado.fotos.length < estado.total) cargarMas();
}
function pintarInfoVisor(f) {
  const info = $("#visor-info");
  if (movil()) {
    info.textContent = `${f.ruta.split("/").pop()} · ${formatoFecha(f.fecha || "")} · Biblioteca del PC`;
    return;
  }
  info.textContent = `${f.ruta} · ${f.fecha ? f.fecha.replace("T", " ") : "sin fecha"}${f.camara ? " · " + f.camara : ""}${f.gps ? " · GPS" : ""}`;
  if (f.descripcion) info.append(el("br"), f.descripcion);
  info.append(el("br"));
  for (const etiqueta of f.etiquetas) info.append(el("span", { className: "chip", textContent: etiqueta }));
}
function cargarImagenVisor(f) {
  const version = ++versionImagen, img = $("#visor-img");
  img.alt = f.descripcion || f.ruta.split("/").pop();
  img.src = `/api/miniatura/${f.id}?lado=1024`;
  $("#visor-carga").textContent = "Cargando imagen…"; $("#visor-reintentar").hidden = true;
  const original = new Image();
  original.onload = () => {
    if (version !== versionImagen || ui.visorId !== f.id) return;
    img.src = original.src; $("#visor-carga").textContent = "";
  };
  original.onerror = () => {
    if (version !== versionImagen || ui.visorId !== f.id) return;
    $("#visor-carga").textContent = "No se pudo cargar el original desde el PC."; $("#visor-reintentar").hidden = false;
  };
  original.src = `/api/original/${f.id}`;
}
$("#visor-reintentar").onclick = () => {
  const f = estado.fotos.find(f => f.id === ui.visorId); if (f) cargarImagenVisor(f);
};
async function navegarVisor(d) {
  const actual = ui.visorId; let i = estado.fotos.findIndex(f => f.id === actual);
  if (i < 0) return;
  if (i + d >= estado.fotos.length && estado.fotos.length < estado.total) await cargarMas();
  if (ui.visorId !== actual) return;
  if (estado.fotos[i + d]) mostrarVisor(i + d);
}
const superficie = $("#visor-superficie");
let gesto = null, ultimoToque = 0, toqueTimer;
superficie.addEventListener("pointerdown", e => {
  if (!movil()) return;
  if (e.button && e.pointerType === "mouse") return;
  if (e.isTrusted) superficie.setPointerCapture(e.pointerId);
  ui.puntos.set(e.pointerId, { x: e.clientX, y: e.clientY });
  const puntos = [...ui.puntos.values()];
  if (puntos.length === 1) gesto = { x: e.clientX, y: e.clientY, px: ui.x, py: ui.y, movido: false, pellizco: false };
  else if (puntos.length === 2) {
    clearTimeout(toqueTimer); gesto.pellizco = true;
    gesto.distancia = Math.hypot(puntos[0].x - puntos[1].x, puntos[0].y - puntos[1].y); gesto.zoom = ui.zoom;
  }
});
superficie.addEventListener("pointermove", e => {
  if (!ui.puntos.has(e.pointerId) || !gesto) return;
  ui.puntos.set(e.pointerId, { x: e.clientX, y: e.clientY });
  const puntos = [...ui.puntos.values()];
  if (puntos.length === 2) {
    const distancia = Math.hypot(puntos[0].x - puntos[1].x, puntos[0].y - puntos[1].y);
    ui.zoom = Math.max(1, Math.min(5, gesto.zoom * distancia / Math.max(1, gesto.distancia))); transformarImagen();
  } else if (!gesto.pellizco) {
    const dx = e.clientX - gesto.x, dy = e.clientY - gesto.y;
    if (Math.hypot(dx, dy) > 10) gesto.movido = true;
    if (ui.zoom > 1) { ui.x = gesto.px + dx; ui.y = gesto.py + dy; transformarImagen(); }
  }
});
function terminarGesto(e) {
  if (!ui.puntos.has(e.pointerId)) return;
  ui.puntos.delete(e.pointerId);
  if (!gesto || ui.puntos.size) return;
  if (e.type !== "pointercancel" && !gesto.pellizco) {
    const dx = e.clientX - gesto.x, dy = e.clientY - gesto.y;
    if (gesto.movido && ui.zoom === 1 && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.3) navegarVisor(dx < 0 ? 1 : -1);
    else if (!gesto.movido) {
      const ahora = performance.now();
      if (ahora - ultimoToque < 300) {
        clearTimeout(toqueTimer); ui.zoom = ui.zoom > 1 ? 1 : 2.5; ui.x = ui.y = 0; transformarImagen(); ultimoToque = 0;
      } else {
        ultimoToque = ahora;
        toqueTimer = setTimeout(() => $("#visor").classList.toggle("sin-controles"), 300);
      }
    }
  }
  gesto = null;
}
superficie.addEventListener("pointerup", terminarGesto);
superficie.addEventListener("pointercancel", terminarGesto);
$("#visor").addEventListener("keydown", e => {
  if (e.key === "+" || e.key === "=") { ui.zoom = Math.min(5, ui.zoom + .5); transformarImagen(); }
  if (e.key === "-" || e.key === "0") reiniciarZoom();
});
// Foco atrapado en las superficies no implementadas con <dialog>.
document.addEventListener("keydown", e => {
  if (document.querySelector("dialog[open]")) return;
  const superficie = !$("#detalle").hidden && (compacto() || !$("#visor").hidden) ? $("#detalle") : !$("#visor").hidden ? $("#visor") : null;
  if (e.key === "Escape" && superficie?.id === "detalle") { e.preventDefault(); e.stopImmediatePropagation(); cerrarSuperficie("detalle"); }
  if (e.key !== "Tab" || !superficie) return;
  if (superficie.id === "visor") superficie.classList.remove("sin-controles");
  const controles = [...superficie.querySelectorAll("button, input, select, textarea, [tabindex='0']")].filter(n => !n.disabled && n.getClientRects().length);
  const primero = controles[0], ultimo = controles.at(-1);
  if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo?.focus(); }
  else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero?.focus(); }
}, true);
window.addEventListener("offline", () => aviso("Sin conexión. Las operaciones requieren conexión con el PC.", true));
