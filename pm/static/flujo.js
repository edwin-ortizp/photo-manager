// Las acciones se limitan a la selección capturada al abrir el diálogo.
let flujoModo = "auditoria", flujoIds = [], flujoPreview = null, flujoBusy = false;
let auditoriaFotos = [], flujoTimer = null, ultimoTrabajo = "", auditoriaLimite = 200;
const NOMBRES_PENDIENTES = {
  "sin-fecha": "Sin fecha", "sin-tipo": "Sin tipo", "sin-clasificar": "Sin clasificar",
  "personas-pendientes": "Personas pendientes", "ano-incoherente": "Año de carpeta incoherente",
  "sin-avif": "Sin convertir a AVIF", dimensiones: "Supera 3840 px", profundidad: "Profundidad distinta de 8 bits",
  muestreo: "Muestreo distinto de 4:2:0", "multiples-cuadros": "Múltiples cuadros: conversión bloqueada",
  ilegible: "Imagen ilegible o herramienta no disponible", "extension-incoherente": "Extensión y formato diferentes",
  "conversion-por-revisar": "Conversión por revisar", "avif-por-auditar": "AVIF por auditar",
};
function nombrePendiente(s) { return NOMBRES_PENDIENTES[s] || s; }
function invalidarFlujo() {
  flujoPreview = null; $("#flujo-preview").hidden = true; $("#flujo-confirmar").disabled = true;
  $("#flujo-texto").value = "";
}
async function accionFlujo(fn) {
  if (flujoBusy) return;
  flujoBusy = true;
  $("#flujo-revisar").disabled = true;
  $("#flujo-confirmar").disabled = true;
  $("#flujo").querySelectorAll("#flujo-respaldo, #flujo-destinos input, #flujo-elegir").forEach(e => e.disabled = true);
  $("#flujo-mensaje").textContent = "Procesando…";
  try { await fn(); }
  catch (e) { invalidarFlujo(); $("#flujo-mensaje").textContent = e.message; }
  finally {
    flujoBusy = false; $("#flujo-revisar").disabled = false;
    $("#flujo").querySelectorAll("#flujo-respaldo, #flujo-destinos input, #flujo-elegir").forEach(e => e.disabled = false);
  }
}
async function abrirFlujo(modo) {
  flujoModo = modo; flujoIds = [...estado.sel]; invalidarFlujo();
  if (modo !== "auditoria" && !flujoIds.length) return;
  $("#flujo-titulo").textContent = {auditoria: "Auditoría y trabajos", convertir: "Convertir / corregir AVIF", organizar: "Organizar selección"}[modo];
  $("#flujo-alcance").textContent = modo === "auditoria" ? "La auditoría no modifica las fotos. Actualiza el inventario para detectar archivos nuevos." : `${flujoIds.length} foto(s) seleccionadas. Los filtros no agregan archivos a esta operación.`;
  $("#flujo-conversion").hidden = modo !== "convertir";
  $("#flujo-organizar").hidden = modo !== "organizar";
  $("#flujo-auditoria").hidden = modo !== "auditoria";
  $("#flujo-revisar").hidden = modo === "auditoria";
  $("#flujo-destinos").replaceChildren();
  $("#flujo-mensaje").textContent = "";
  if (!$("#flujo").open) $("#flujo").showModal();
  await accionFlujo(async () => {
    if (modo === "convertir") {
      const c = await api("/api/flujo/config");
      $("#flujo-respaldo").value = c.respaldo;
      $("#flujo-elegir").hidden = !window.pywebview?.api?.elegir_originales;
    }
    if (modo === "organizar") {
      const r = await api("/api/flujo/sugerencias", {ids: flujoIds, operacion: modo});
      for (const a of r.archivos) {
        // El servidor expone también la ruta relativa para evitar inferir raíces.
        const input = el("input", {value: a.carpeta_destino, required: true});
        input.dataset.id = a.id;
        input.oninput = invalidarFlujo;
        $("#flujo-destinos").append(el("label", {textContent: a.ruta + " → carpeta de destino"}, input));
      }
    }
    if (modo === "auditoria") await cargarAuditoria();
    $("#flujo-mensaje").textContent = "";
    await cargarTrabajos();
  });
}
function parametrosFlujo() {
  return {ids: flujoIds, operacion: flujoModo, respaldo: $("#flujo-respaldo").value,
    destinos: Object.fromEntries([...$("#flujo-destinos").querySelectorAll("input")].map(i => [i.dataset.id, i.value]))};
}
$("#flujo-revisar").onclick = () => accionFlujo(async () => {
  const firma = JSON.stringify(parametrosFlujo());
  const r = await api("/api/flujo/preview", parametrosFlujo());
  if (firma !== JSON.stringify(parametrosFlujo())) throw new Error("Las opciones cambiaron; revisa de nuevo.");
  flujoPreview = {...r, firma};
  $("#flujo-lista").replaceChildren(...r.archivos.map(a => el("div", {className: "operacion-foto"},
    el("img", {src: `/api/miniatura/${a.id}`, alt: ""}), el("div", {}, el("strong", {textContent: a.ruta}),
      el("p", {textContent: "Destino: " + a.destino}), ...(a.respaldo ? [el("p", {textContent: "Original: " + a.respaldo})] : [])))));
  if (r.omitidas.length) $("#flujo-lista").append(el("p", {textContent: "Omitidas: " + r.omitidas.map(a => `${a.ruta} (${a.motivo})`).join("; ")}));
  $("#flujo-frase").textContent = r.frase;
  $("#flujo-texto").value = "";
  $("#flujo-preview").hidden = false;
  $("#flujo-mensaje").textContent = r.archivos.length ? "Revisa las rutas y confirma para iniciar." : "No hay cambios que aplicar.";
});
$("#flujo-texto").oninput = () => {
  $("#flujo-confirmar").disabled = flujoBusy || !flujoPreview?.archivos.length || $("#flujo-texto").value !== flujoPreview.frase;
};
$("#flujo-respaldo").oninput = invalidarFlujo;
$("#flujo-elegir").onclick = () => accionFlujo(async () => {
  const ruta = await window.pywebview.api.elegir_originales();
  if (ruta) { $("#flujo-respaldo").value = ruta; invalidarFlujo(); }
  $("#flujo-mensaje").textContent = "";
});
$("#flujo-confirmar").onclick = () => accionFlujo(async () => {
  if (!flujoPreview || flujoPreview.firma !== JSON.stringify(parametrosFlujo())) throw new Error("Revisa de nuevo las opciones.");
  const j = await api("/api/flujo/aplicar", {token: flujoPreview.token, texto: $("#flujo-texto").value});
  invalidarFlujo();
  $("#flujo-mensaje").textContent = "Trabajo iniciado. Puedes cerrar esta ventana y seguir su progreso en Auditoría y trabajos.";
  await cargarTrabajos();
});
async function iniciarAuditoria(ids) {
  await api("/api/flujo/trabajos", {operacion: "auditar", ids});
  $("#flujo-mensaje").textContent = "Auditoría iniciada.";
  await cargarTrabajos();
}
$("#auditar-biblioteca").onclick = () => accionFlujo(() => iniciarAuditoria(null));
$("#auditar-seleccion").onclick = async () => {
  const ids = [...estado.sel]; if (!ids.length) return;
  await abrirFlujo("auditoria"); await accionFlujo(() => iniciarAuditoria(ids));
};
$("#actualizar-inventario").onclick = async () => {
  await abrirFlujo("auditoria");
  await accionFlujo(async () => {
    await api("/api/flujo/trabajos", {operacion: "actualizar"});
    $("#flujo-mensaje").textContent = "Actualizando inventario…";
    await cargarTrabajos();
  });
};
$("#abrir-auditoria").onclick = () => abrirFlujo("auditoria");
$("#convertir-seleccion").onclick = () => abrirFlujo("convertir");
$("#organizar-seleccion").onclick = () => abrirFlujo("organizar");
$("#flujo-cerrar").onclick = $("#flujo-listo").onclick = () => $("#flujo").close();
async function cargarAuditoria() {
  auditoriaFotos = (await api("/api/flujo/auditoria")).fotos;
  pintarAuditoria();
}
function pintarAuditoria() {
  const filtro = $("#auditoria-filtro").value;
  const fotos = auditoriaFotos.filter(f => {
    const t = f.tecnica;
    return filtro === "todos" || (filtro === "organizacion" && f.organizacion.length) ||
      (filtro === "conforme" && t?.conforme) || (filtro === "desconocidos" && (!t || t.desconocidos.length)) ||
      (filtro === "errores" && t?.errores.length) || (filtro === "avisos" && t?.avisos.length);
  });
  const lista = $("#auditoria-resultados");
  lista.replaceChildren(el("p", {textContent: `${fotos.length} de ${auditoriaFotos.length} fotos. Mostrando ${Math.min(fotos.length, auditoriaLimite)}.`}));
  for (const f of fotos.slice(0, auditoriaLimite)) {
    const t = f.tecnica;
    const abrir = el("button", {textContent: "Ver foto"});
    abrir.onclick = () => { $("#flujo").close(); filtrar({q: f.ruta, bandeja: "todas", carpeta: "", etiqueta: ""}); };
    lista.append(el("article", {className: "auditoria-fila"}, el("strong", {textContent: f.ruta}),
      el("p", {textContent: t ? (t.conforme ? "AVIF conforme" : "Pendiente técnico") + (t.ancho ? ` · ${t.ancho} × ${t.alto} · ${t.bits ?? "?"} bits · ${t.chroma ?? "muestreo desconocido"}` : "") : "Sin auditar o archivo modificado"}),
      el("p", {textContent: t ? [...t.errores.map(x => "Error: " + nombrePendiente(x)), ...t.avisos.map(x => "Aviso: " + nombrePendiente(x)), ...t.desconocidos.map(x => "Desconocido: " + x)].join(" · ") : ""}),
      ...(t?.detalle ? [el("p", {textContent: t.detalle})] : []),
      el("p", {textContent: f.organizacion.map(nombrePendiente).join(" · ")}), abrir));
  }
  if (fotos.length > auditoriaLimite) {
    const mas = el("button", {textContent: "Mostrar 200 más"});
    mas.onclick = () => { auditoriaLimite += 200; pintarAuditoria(); };
    lista.append(mas);
  }
}
$("#auditoria-filtro").onchange = () => { auditoriaLimite = 200; pintarAuditoria(); };
async function cargarTrabajos() {
  clearTimeout(flujoTimer);
  const trabajos = (await api("/api/flujo/trabajos")).trabajos;
  $("#flujo-trabajos").replaceChildren(...trabajos.map(j => {
    const nodo = el("article", {className: "auditoria-fila"}, el("strong", {textContent: `${j.operacion}: ${j.estado}`}),
      el("p", {textContent: `${j.procesadas}/${j.total} · ${j.pendientes.length} pendientes`}),
      ...(j.archivo_actual ? [el("p", {textContent: j.archivo_actual})] : []),
      ...j.fallidas.map(e => el("p", {className: "error", textContent: `${e.ruta || ""}: ${e.error}${e.archivo_modificado ? " · El archivo fue modificado; actualiza el inventario antes de continuar." : ""}`})));
    if (["ejecutando", "pendiente"].includes(j.estado)) {
      const cancelar = el("button", {textContent: "Cancelar después del archivo actual"});
      cancelar.onclick = () => accionFlujo(async () => {
        await api(`/api/flujo/trabajos/${j.id}/cancelar`, {});
        $("#flujo-mensaje").textContent = "Cancelación solicitada; se terminará el archivo actual.";
      });
      nodo.append(cancelar);
    }
    if (j.completadas.length || j.pendientes.length) {
      const detalle = el("details", {}, el("summary", {textContent: "Resultados y pendientes"}));
      for (const a of j.completadas) detalle.append(el("p", {textContent: `${a.ruta}${a.destino ? " → " + a.destino : ""}${a.respaldo ? " · Original: " + a.respaldo : ""}${a.advertencias?.length ? " · Advertencia: " + a.advertencias.join("; ") : ""}`}));
      for (const ruta of j.pendientes) detalle.append(el("p", {textContent: "Pendiente: " + ruta}));
      nodo.append(detalle);
    }
    return nodo;
  }));
  if (trabajos.length) {
    const ultimo = trabajos[0], firma = ultimo.id + ":" + ultimo.estado;
    if (firma !== ultimoTrabajo && !["ejecutando", "pendiente"].includes(ultimo.estado)) {
      estado.sel.clear(); await cargarResumen(); await recargar();
      if (flujoModo === "auditoria") await cargarAuditoria();
      $("#flujo-mensaje").textContent = `${ultimo.operacion}: ${ultimo.estado}. ${ultimo.procesadas} archivo(s) procesados.`;
    }
    ultimoTrabajo = firma;
  }
  if (trabajos.some(j => ["ejecutando", "pendiente"].includes(j.estado))) {
    flujoTimer = setTimeout(() => cargarTrabajos().catch(e => { $("#flujo-mensaje").textContent = e.message; }), 1500);
  }
}
