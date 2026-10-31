// Panel de fotos: bandejas, rejilla por dia, seleccion masiva y etiquetado.
const $ = (s) => document.querySelector(s);
const estado = {
  filtro: { bandeja: "todas", carpeta: "", etiqueta: "", q: "" },
  fotos: [], total: 0, cargando: false, generacion: 0,
  sel: new Set(), ultimo: null, visor: -1, etiquetas: [],
};
const TIPOS = { foto: "Foto", captura: "Captura", meme: "Meme", documento: "Documento", otro: "Otro" };
const GRUPOS = [
  { rama: "lugar", nombre: "Lugar", entrada: "agregar-lugar", lista: "lugares", limite: 6 },
  { rama: "personas", nombre: "Personas", entrada: "agregar-persona", lista: "personas", limite: 8 },
  ...["mascotas", "vehiculos", "estilo", "momento", "tema"].map((rama, i) => ({
    rama, nombre: ["Mascotas", "Vehículos", "Estilo", "Momento", "Tema"][i], entrada: "agregar-" + rama, lista: rama, limite: 6,
  })),
];

// Solo se crean los controles; las etiquetas pertenecen al catálogo del usuario.
$("#grupos-etiquetas").replaceChildren(...GRUPOS.map(g => {
  const input = el("input", { id: g.entrada, placeholder: "Buscar o agregar…" });
  input.setAttribute("list", "lista-" + g.lista);
  input.setAttribute("aria-label", "Buscar o agregar: " + g.nombre);
  const asignar = el("button", { type: "button", textContent: "+", title: "Asignar etiqueta de " + g.nombre });
  asignar.setAttribute("aria-label", "Asignar etiqueta de " + g.nombre);
  asignar.onclick = () => agregarEnGrupo(g);
  return el("section", { className: "grupo-etiquetas", id: "grupo-" + g.rama },
    el("h2", { textContent: g.nombre }), el("div", { id: "chips-" + g.rama, className: "chips" }),
    el("div", { className: "entrada-grupo" }, input, asignar), el("datalist", { id: "lista-" + g.lista }),
    el("div", { id: "frecuentes-" + g.rama, className: "frecuentes" }),
    ...(g.rama === "personas" ? [el("p", { id: "conteo-personas" })] : []));
}));

async function api(url, datos) {
  const r = await fetch(url, datos ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos),
  } : undefined);
  if (!r.ok) {
    const texto = await r.text();
    let mensaje = texto;
    try { const datos = JSON.parse(texto); if (typeof datos.detail === "string") mensaje = datos.detail; } catch {}
    throw new Error(mensaje);
  }
  return r.json();
}

function aviso(texto, error = false) {
  const a = $("#aviso");
  a.textContent = texto; a.className = error ? "error" : ""; a.hidden = false;
  clearTimeout(aviso.t); aviso.t = setTimeout(() => (a.hidden = true), 2500);
}

// ---------- lateral ----------

async function cargarResumen() {
  const r = await api("/api/resumen");
  estado.etiquetas = r.etiquetas;
  const f = estado.filtro;
  const li = (texto, n, activo, clic, clase = "") => {
    const el = document.createElement("li");
    el.className = `${activo ? "activo" : ""} ${clase} ${n === 0 ? "cero" : ""}`;
    el.innerHTML = `<span></span><span class="n">${n}</span>`;
    el.firstChild.textContent = texto;
    el.tabIndex = 0; el.setAttribute("role", "button");
    el.onclick = clic;
    el.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); clic(); } };
    return el;
  };
  $("#bandejas").replaceChildren(...r.bandejas.map((b) =>
    li(b.nombre, b.total, f.bandeja === b.id && !f.carpeta && !f.etiqueta, () => filtrar({ bandeja: b.id, carpeta: "", etiqueta: "" }))));
  $("#carpetas").replaceChildren(...r.carpetas.map((c) =>
    li(c.id, c.total, f.carpeta === c.id, () => filtrar({ bandeja: "todas", carpeta: c.id, etiqueta: "" }))));
  pintarEtiquetas();
  $("#lista-etiquetas").replaceChildren(...r.etiquetas.map((t) => Object.assign(document.createElement("option"), { value: t.id })));
  pintarSugerencias();
  if (window.actualizarColecciones) actualizarColecciones();
}

function pintarEtiquetas() {
  const texto = $("#filtro-etiquetas").value.toLowerCase().trim();
  const abiertos = new Set([...document.querySelectorAll(".etiqueta-grupo[open]")].map(x => x.dataset.ruta));
  const ramas = new Map();
  for (const t of estado.etiquetas) {
    const padre = t.id.includes("|") ? t.id.slice(0, t.id.lastIndexOf("|")) : "";
    if (!ramas.has(padre)) ramas.set(padre, []);
    ramas.get(padre).push(t);
  }
  const pintar = t => {
    const boton = el("button", { className: "etiqueta-filtro" + (estado.filtro.etiqueta === t.id ? " activo" : ""), title: t.id },
      el("span", { textContent: t.id.split("|").pop().replaceAll("-", " ") }), el("span", { className: "n", textContent: t.total }));
    boton.onclick = () => filtrar({ bandeja: "todas", carpeta: "", etiqueta: t.id });
    boton.setAttribute("aria-pressed", String(estado.filtro.etiqueta === t.id));
    const hijos = (ramas.get(t.id) || []).filter(h => coincide(h.id));
    if (!hijos.length) return boton;
    const grupo = el("details", { className: "etiqueta-grupo", open: !!texto || abiertos.has(t.id) || estado.filtro.etiqueta.startsWith(t.id + "|") });
    grupo.dataset.ruta = t.id;
    const summary = el("summary", {}, el("span", { textContent: "▸", className: "desplegar", title: "Desplegar grupo" }), boton);
    boton.onclick = ev => { ev.preventDefault(); filtrar({ bandeja: "todas", carpeta: "", etiqueta: t.id }); };
    grupo.append(summary, el("div", { className: "etiqueta-hijos" }, ...hijos.map(pintar)));
    return grupo;
  };
  const coincide = id => id.includes(texto) || estado.etiquetas.some(t => t.id.startsWith(id + "|") && t.id.includes(texto));
  const raices = (ramas.get("") || []).filter(t => coincide(t.id));
  $("#etiquetas").replaceChildren(...raices.filter(t => !t.id.startsWith("_")).map(pintar));
  $("#etiquetas-internas").replaceChildren(...raices.filter(t => t.id.startsWith("_")).map(pintar));
  if (texto) $("#internas").open = true;
}

// ---------- administrador ----------
let previewEtiqueta = null;
let adminOcupado = false;
function invalidarPreview() {
  previewEtiqueta = null;
  $("#admin-preview").hidden = true;
}
function pintarAdministrador() {
  const q = $("#admin-buscar").value.trim().toLowerCase();
  const etiquetas = estado.etiquetas.filter(t => t.id.includes(q));
  $("#admin-lista").replaceChildren(...etiquetas.map(t => {
    const editar = el("button", { textContent: "Renombrar", disabled: adminOcupado });
    editar.onclick = () => {
      invalidarPreview();
      $("#renombrar-etiqueta").hidden = false;
      $("#renombrar-origen").value = t.id;
      $("#renombrar-destino").value = t.id;
      $("#renombrar-destino").focus();
    };
    return el("div", { className: "admin-fila" }, el("span", { textContent: t.id.replaceAll("|", " › ") }),
      el("small", { textContent: `${t.total} fotos` }), editar);
  }));
  if (!etiquetas.length) $("#admin-lista").textContent = "No hay etiquetas que coincidan.";
}
async function accionAdministrador(fn) {
  if (adminOcupado) return;
  adminOcupado = true;
  $("#admin-mensaje").textContent = "Procesando…";
  $("#administrador").querySelectorAll("button, input").forEach(x => x.disabled = true);
  try { await fn(); }
  catch (e) { $("#admin-mensaje").textContent = "Error: " + e.message; invalidarPreview(); }
  finally {
    adminOcupado = false;
    $("#administrador").querySelectorAll("button, input").forEach(x => x.disabled = false);
    pintarAdministrador();
  }
}
$("#administrar-etiquetas").onclick = () => {
  pintarAdministrador();
  $("#administrador").showModal();
};
$("#admin-cerrar").onclick = $("#admin-listo").onclick = () => $("#administrador").close();
$("#administrador").addEventListener("cancel", e => { if (adminOcupado) e.preventDefault(); });
$("#admin-buscar").oninput = pintarAdministrador;
$("#renombrar-destino").oninput = invalidarPreview;
$("#admin-cancelar").onclick = invalidarPreview;
$("#crear-etiqueta").onsubmit = e => {
  e.preventDefault();
  accionAdministrador(async () => {
    const r = await api("/api/etiquetas/crear", { nombre: $("#crear-nombre").value });
    invalidarPreview();
    await cargarResumen();
    $("#crear-nombre").value = "";
    $("#admin-mensaje").textContent = `Etiqueta creada: ${r.nombre}`;
  });
};
$("#renombrar-etiqueta").onsubmit = e => {
  e.preventDefault();
  accionAdministrador(async () => {
    previewEtiqueta = await api("/api/etiquetas/renombrar/preview", {
      origen: $("#renombrar-origen").value, destino: $("#renombrar-destino").value,
    });
    $("#admin-impacto").textContent = `${previewEtiqueta.origen} → ${previewEtiqueta.destino}. Se actualizarán los metadatos de ${previewEtiqueta.fotos} fotos, incluidas las subetiquetas.`;
    $("#admin-preview").hidden = false;
    $("#admin-mensaje").textContent = "Revisa el cambio y confirma para aplicarlo.";
  });
};
$("#admin-confirmar").onclick = () => accionAdministrador(async () => {
  if (!previewEtiqueta) return;
  const r = await api("/api/etiquetas/renombrar", previewEtiqueta);
  const filtro = estado.filtro.etiqueta;
  if (filtro === r.origen || filtro.startsWith(r.origen + "|")) {
    estado.filtro.etiqueta = r.destino + filtro.slice(r.origen.length);
    escribirURL();
  }
  invalidarPreview();
  $("#renombrar-etiqueta").hidden = true;
  estado.sel.clear();
  await cargarResumen();
  await recargar();
  $("#admin-mensaje").textContent = `Renombrado completado: ${r.actualizadas} fotos actualizadas.`;
});

// ---------- rejilla ----------

function filtrar(cambios, historial = true) {
  if (window.cambiarSeccion) { guardarHistoria(); cambiarSeccion("fotos", false); }
  Object.assign(estado.filtro, cambios);
  estado.sel.clear(); estado.ultimo = null;
  if (historial) escribirURL();
  recargar(false);
  cargarResumen().catch(() => aviso("No se pudo actualizar el resumen del PC.", true));
}

// ---------- URL ----------
// ?bandeja=sin-etiquetas  ?year=2022  ?carpeta=capturas  ?tag=personas|yo (o ?tag=yo)  &q=texto

function escribirURL() {
  const f = estado.filtro, p = new URLSearchParams();
  if (f.bandeja && f.bandeja !== "todas") p.set("bandeja", f.bandeja);
  if (f.carpeta) p.set(/^\d{4}$/.test(f.carpeta) ? "year" : "carpeta", f.carpeta);
  if (f.etiqueta) p.set("tag", f.etiqueta);
  if (f.q) p.set("q", f.q);
  const url = p.toString() ? `?${p.toString().replaceAll("%7C", "|")}` : location.pathname;
  if (url !== (location.search || location.pathname)) { guardarHistoria(); history.pushState({ pm: true, seccion: "fotos", capas: [], scroll: 0 }, "", url); ui.capas = []; ui.detalle = false; }
}

async function leerURL() {
  const p = new URLSearchParams(location.search);
  let tag = p.get("tag") || "";
  if (tag && !tag.includes("|")) {
    // ?tag=yo -> personas|yo si es la unica etiqueta con esa hoja
    const r = await api("/api/resumen");
    const hoja = r.etiquetas.map((t) => t.id).filter((t) => t === tag || t.endsWith("|" + tag));
    if (hoja.length === 1) tag = hoja[0];
  }
  estado.filtro = {
    bandeja: p.get("bandeja") || "todas",
    carpeta: p.get("year") || p.get("carpeta") || "",
    etiqueta: tag,
    q: p.get("q") || "",
  };
  $("#buscar").value = estado.filtro.q;
}

async function recargar(preservar = true) {
  const posicion = preservar ? $("main").scrollTop : 0;
  const ids = preservar ? new Set(estado.sel) : new Set();
  const filas = preservar && typeof ui !== "undefined" ? ui.filas : [];
  const ancla = filas.find(f => f.indices && f.y >= posicion)?.indices[0];
  const anclaId = ancla !== undefined ? estado.fotos[ancla]?.id : null;
  if (window.reiniciarCronologia) reiniciarCronologia();
  estado.generacion++;
  const generacion = estado.generacion;
  estado.cargando = false;
  estado.fotos = []; estado.total = 0;
  $("#rejilla").replaceChildren();
  $("main").scrollTop = 0;
  await cargarMas();
  if (generacion !== estado.generacion) return;
  while (preservar && estado.fotos.length < estado.total &&
    ((anclaId && !estado.fotos.some(f => f.id === anclaId)) || [...ids].some(id => !estado.fotos.some(f => f.id === id)))) {
    const antes = estado.fotos.length;
    await cargarMas();
    if (generacion !== estado.generacion) return;
    if (estado.fotos.length === antes) break;
  }
  if (generacion !== estado.generacion) return;
  const disponibles = new Set(estado.fotos.map(f => f.id));
  estado.sel = new Set([...estado.sel].filter(id => disponibles.has(id)));
  pintarSeleccion();
  if (preservar) $("main").scrollTop = posicion;
}

function cargarMas() {
  if (estado.cargando && estado.peticion) return estado.peticion;
  estado.peticion = ejecutarCargaMas();
  return estado.peticion;
}

async function ejecutarCargaMas() {
  if (estado.cargando || (estado.fotos.length && estado.fotos.length >= estado.total)) return;
  estado.cargando = true;
  if (window.estadoGaleria) estadoGaleria("Cargando fotos…");
  const generacion = estado.generacion;
  const p = new URLSearchParams({ ...estado.filtro, offset: estado.fotos.length, limite: 300 });
  try {
    const r = await api(`/api/fotos?${p}`);
    if (generacion !== estado.generacion) return;
    const inicio = estado.fotos.length;
    estado.fotos.push(...r.fotos);
    estado.total = r.total;
    pintarDesde(inicio);
    if (window.estadoGaleria) estadoGaleria(r.total ? "" : "No hay fotos que coincidan con esta búsqueda.");
    const f = estado.filtro;
    $("#titulo").textContent = `${f.etiqueta || f.carpeta || $("#bandejas .activo span")?.textContent || "Todas"} · ${r.total}`;
  } catch (e) {
    if (generacion === estado.generacion && window.estadoGaleria) estadoGaleria("No se pudieron cargar las fotos. Comprueba la conexión con el PC.", true);
  } finally {
    if (generacion === estado.generacion) estado.cargando = false;
  }
}

const diaDe = (foto) => (foto.fecha ? foto.fecha.slice(0, 10) : "sin fecha");

function pintarDesde(inicio) {
  reconstruirCronologia();
}

function formatoDia(dia) {
  if (dia === "sin fecha") return "Sin fecha";
  if (dia.length === 4) return dia + " · año conocido";
  if (dia.length === 7) return new Date(dia + "-01T12:00").toLocaleDateString("es-CO", { month: "long", year: "numeric" }) + " · día desconocido";
  return new Date(dia + "T12:00").toLocaleDateString("es-CO", { weekday: "short", day: "numeric", month: "long", year: "numeric" });
}

function celda(foto, i) {
  const el = document.createElement("div");
  el.className = "foto" + (estado.sel.has(foto.id) ? " sel" : "");
  el.dataset.id = foto.id;
  el.tabIndex = 0; el.setAttribute("role", "button");
  el.setAttribute("aria-label", foto.ruta.split("/").pop() + " · " + formatoDia(diaDe(foto)));
  el.setAttribute("aria-pressed", String(estado.sel.has(foto.id)));
  el.onkeydown = ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); clicFoto(i, ev); } };
  el.innerHTML = `<img alt="" loading="lazy" src="/api/miniatura/${foto.id}"><div class="marcas"></div>`;
  const img = el.querySelector("img");
  let intentos = 0;
  img.onerror = () => {
    // La miniatura puede estar generandose: reintentar antes de darla por rota
    if (intentos < 2) {
      const espera = ++intentos === 1 ? 1500 : 4000;
      setTimeout(() => (img.src = `/api/miniatura/${foto.id}?r=${intentos}`), espera);
    } else {
      img.remove();
      el.classList.add("roto");
      el.prepend("⚠");
    }
  };
  el.querySelector(".marcas").textContent = foto.etiquetas.filter((e) => !e.startsWith("_")).join(" · ");
  el.title = `${foto.ruta}\n${foto.etiquetas.join("\n")}`;
  if (foto.ruta.startsWith("entrada/") && foto.pendientes?.length) {
    const pendientes = document.createElement("span");
    pendientes.className = "pendientes-foto";
    pendientes.textContent = foto.pendientes.map(x => typeof nombrePendiente === "function" ? nombrePendiente(x) : x).join(" · ");
    pendientes.title = pendientes.textContent;
    el.append(pendientes);
  }
  enlazarFoto(el, i);
  el.ondblclick = () => abrirVisor(i);
  return el;
}

// ---------- seleccion ----------

function clicFoto(i, ev) {
  if (ev.pointerType === "touch" || ev.pointerType === "pen" || ev.tactil) {
    if (!estado.sel.size) { abrirVisor(i); return; }
    const id = estado.fotos[i].id;
    estado.sel.has(id) ? estado.sel.delete(id) : estado.sel.add(id);
    pintarSeleccion(); return;
  }
  const id = estado.fotos[i].id;
  // Clic: solo esta · Ctrl+clic: agregar/quitar · Shift+clic: rango
  if (ev.shiftKey && estado.ultimo !== null) {
    const [a, b] = [Math.min(estado.ultimo, i), Math.max(estado.ultimo, i)];
    for (let k = a; k <= b; k++) estado.sel.add(estado.fotos[k].id);
  } else if (ev.ctrlKey || ev.metaKey) {
    estado.sel.has(id) ? estado.sel.delete(id) : estado.sel.add(id);
  } else {
    const yaSola = estado.sel.size === 1 && estado.sel.has(id);
    estado.sel.clear();
    if (!yaSola) estado.sel.add(id);
  }
  estado.ultimo = i;
  pintarSeleccion();
}

function seleccionarDia(dia) {
  const ids = estado.fotos.filter((f) => diaDe(f) === dia).map((f) => f.id);
  const todas = ids.every((id) => estado.sel.has(id));
  ids.forEach((id) => (todas ? estado.sel.delete(id) : estado.sel.add(id)));
  pintarSeleccion();
}

// ---------- panel de detalle ----------

function el(tag, props = {}, ...hijos) {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...hijos);
  return e;
}

function pintarSeleccion() {
  if (document.querySelector("#operaciones").open && operacionSeleccion !== firmaSeleccion()) invalidarOperacion();
  document.querySelectorAll(".foto").forEach((x) => { x.classList.toggle("sel", estado.sel.has(+x.dataset.id)); x.setAttribute("aria-pressed", String(estado.sel.has(+x.dataset.id))); });
  const n = estado.sel.size;
  actualizarSeleccionUI(n);
  if (!n) return;
  const fotos = estado.fotos.filter((f) => estado.sel.has(f.id));
  $("#sel-total").textContent = n === 1 ? fotos[0]?.ruta.split("/").pop() : `${n} seleccionadas`;
  const tipos = new Set(fotos.map(f => f.etiquetas.filter(t => t.startsWith("tipo|")).join(",")));
  const tipo = tipos.size === 1 ? [...tipos][0].replace("tipo|", "") : "";
  const opciones = [el("option", { value: "", textContent: tipos.size > 1 ? "Tipos diferentes" : TIPOS[tipo] ? "Seleccionar tipo" : "Sin tipo o con conflicto" }),
    ...Object.entries(TIPOS).map(([value, textContent]) => el("option", { value, textContent }))];
  $("#tipo-principal").replaceChildren(...opciones);
  $("#tipo-principal").value = TIPOS[tipo] ? tipo : "";
  const pendientes = fotos.filter(f => !f.etiquetas.some(t => t.startsWith("tipo|"))).length;
  $("#tipo-pendiente").textContent = pendientes ? `${pendientes} foto(s) sin tipo` : "";
  const fechas = new Set(fotos.map(f => f.fecha || ""));
  $("#fecha-resumen").textContent = fechas.size === 1 ? formatoFecha([...fechas][0]) : "Fechas diferentes";

  // Vista previa
  if (n === 1) {
    const img = el("img", { className: "grande", src: `/api/miniatura/${fotos[0].id}?lado=1024`, title: "Abrir en grande" });
    img.onclick = () => abrirVisor(estado.fotos.indexOf(fotos[0]));
    $("#vista").replaceChildren(img);
  } else {
    const mosaico = el("div", { className: "mosaico" },
      ...fotos.slice(0, 9).map((f) => el("img", { src: `/api/miniatura/${f.id}` })));
    $("#vista").replaceChildren(mosaico, ...(n > 9 ? [el("div", { className: "mas", textContent: `y ${n - 9} más` })] : []));
  }

  pintarChips(fotos);
  pintarSugerencias();
  pintarPersonas(fotos);
  if (n === 1) pintarDatos(fotos[0].id).catch(() => {
    if (!estado.sel.has(fotos[0].id)) return;
    const reintentar = el("button", { textContent: "Reintentar información" });
    reintentar.onclick = () => pintarSeleccion();
    $("#datos").replaceChildren(el("p", { textContent: "No se pudo consultar la información del PC." }), reintentar);
  });
  else $("#datos").replaceChildren();
}

// Etiquetas de la seleccion agrupadas por rama, con cuantas fotos las tienen
function pintarChips(fotos) {
  const conteo = new Map();
  fotos.forEach((f) => f.etiquetas.forEach((e) => conteo.set(e, (conteo.get(e) || 0) + 1)));
  const ramas = new Map();
  for (const { rama } of GRUPOS) {
    $(`#chips-${rama}`).replaceChildren(...[...conteo].filter(([t]) => t === rama || t.startsWith(rama + "|")).sort().map(([t, c]) => chip(t, c, fotos.length)));
  }
  const otras = [...conteo].sort().filter(([t]) => t !== "tipo" && !t.startsWith("tipo|") && !GRUPOS.some(g => t === g.rama || t.startsWith(g.rama + "|")));
  otras.forEach(([t, c]) => {
    const rama = t.includes("|") ? t.split("|")[0] : "otras";
    if (!ramas.has(rama)) ramas.set(rama, []);
    ramas.get(rama).push(chip(t, c, fotos.length));
  });
  const orden = (r) => (r.startsWith("_") ? 1 : 0);
  $("#sel-etiquetas").replaceChildren(...[...ramas].sort((a, b) => orden(a[0]) - orden(b[0]))
    .map(([rama, chips]) => el("div", { className: "rama" }, el("small", { textContent: rama }), ...chips)));
  if (!otras.length) $("#sel-etiquetas").append(el("small", { textContent: "Sin otras etiquetas" }));
}

function chip(t, c, total) {
    const chip = document.createElement("span");
    chip.className = "chip" + (t.startsWith("_") ? " interna" : "");
    chip.title = t;
    chip.innerHTML = `<span></span><span class="n">${total > 1 ? c : ""}</span>`;
    chip.firstChild.textContent = t.includes("|") ? t.split("|").slice(1).join(" › ") : t;
    if (t.startsWith("_sugerencias|")) {
      const ok = document.createElement("button");
      ok.className = "confirmar"; ok.textContent = "✓"; ok.title = "Confirmar como escena";
      ok.onclick = () => etiquetar({ agregar: ["escena|" + t.split("|").pop()], quitar: [t] });
      chip.append(ok);
    }
    const x = document.createElement("button");
    x.textContent = "×"; x.title = total > 1 ? "Quitar de todas las seleccionadas" : "Quitar";
    x.onclick = () => etiquetar({ quitar: [t] });
    chip.append(x);
    return chip;
}

function pintarPersonas(fotos) {
  const p = $("#conteo-personas");
  if (fotos.length !== 1) { p.textContent = ""; return; }
  const e = fotos[0].etiquetas;
  const esperadas = +(e.find((x) => x.startsWith("_ia|personas|"))?.split("|")[2] || 0);
  const nombradas = e.filter((x) => x.startsWith("personas|")).length;
  if (!esperadas && !nombradas) { p.textContent = ""; return; }
  p.textContent = esperadas
    ? `Personas: ${nombradas} de ${esperadas} nombradas`
    : `Personas nombradas: ${nombradas}`;
  p.className = esperadas && nombradas < esperadas ? "pendiente" : "completo";
}

async function pintarDatos(id) {
  const d = await api(`/api/foto/${id}`);
  if (!(estado.sel.size === 1 && estado.sel.has(id))) return; // cambio la seleccion mientras cargaba
  const x = d.exif || {};
  const filas = [
    ["Carpeta", d.carpeta],
    ["Fecha", formatoFecha(d.fecha)],
    ["Cámara", [x.Make, x.Model].filter(Boolean).join(" ")],
    ["Lente", x.LensModel],
    ["Exposición", [x.ExposureTime && (x.ExposureTime < 1 ? `1/${Math.round(1 / x.ExposureTime)} s` : `${x.ExposureTime} s`),
      x.FNumber && `f/${x.FNumber}`, x.ISO && `ISO ${x.ISO}`, x.FocalLength && `${x.FocalLength} mm`].filter(Boolean).join(" · ")],
    ["Tamaño", [d.ancho && `${d.ancho} × ${d.alto} px`, x.FileSize && `${(x.FileSize / 1048576).toFixed(1)} MB`].filter(Boolean).join(" · ")],
    ["Software", x.Software],
    ["Caras", d.caras.join(", ")],
  ].filter(([, v]) => v);
  const dl = el("dl", {}, ...filas.flatMap(([k, v]) => [el("dt", { textContent: k }), el("dd", { textContent: v })]));
  if (d.lat != null) {
    const a = el("a", { href: `https://www.openstreetmap.org/?mlat=${d.lat}&mlon=${d.lon}#map=16/${d.lat}/${d.lon}`,
      target: "_blank", textContent: `${(+d.lat).toFixed(5)}, ${(+d.lon).toFixed(5)}` });
    dl.append(el("dt", { textContent: "Ubicación" }), el("dd", {}, a));
  }
  $("#datos").replaceChildren(
    el("h2", { textContent: "Información" }),
    ...(d.descripcion ? [el("p", { className: "descripcion", textContent: d.descripcion })] : []),
    dl,
  );
}

function moverSeleccion(d) {
  const i = estado.fotos.findIndex((f) => estado.sel.has(f.id)) + d;
  if (i < 0 || i >= estado.fotos.length) return;
  estado.sel.clear();
  estado.sel.add(estado.fotos[i].id);
  estado.ultimo = i;
  pintarSeleccion();
  revelarFoto(estado.fotos[i].id);
}

async function etiquetar({ agregar = [], quitar = [] }) {
  const ids = [...estado.sel];
  let resultado;
  try {
    resultado = await api("/api/etiquetar", { ids, agregar, quitar });
  } catch (e) {
    return aviso("Error: " + e.message, true);
  }
  aviso(resultado.ok ? `${resultado.actualizadas} foto(s) actualizadas` : `${resultado.actualizadas} actualizadas. Errores: ${resultado.fallidas.map(f => f.ruta + ": " + f.error).join("; ")}`, !resultado.ok);
  // Refresca solo las fotos tocadas sin perder la posicion
  const p = new URLSearchParams({ ...estado.filtro, offset: 0, limite: 100000 });
  const r = await api(`/api/fotos?${p}`);
  const porId = new Map(r.fotos.map((f) => [f.id, f]));
  estado.fotos.forEach((f, i) => {
    const nueva = porId.get(f.id);
    if (nueva) estado.fotos[i] = nueva;
    const el = document.querySelector(`.foto[data-id="${f.id}"]`);
    if (el && ids.includes(f.id)) {
      el.style.opacity = nueva ? 1 : 0.35; // salio de la bandeja actual
      if (nueva) el.replaceWith(celda(nueva, i));
    }
  });
  pintarSeleccion();
  await cargarResumen();
}

// ---------- visor ----------

function abrirVisor(i) { mostrarVisor(i); }
async function moverVisor(d) { await navegarVisor(d); }

// ---------- eventos ----------

$("#visor .cerrar").onclick = () => cerrarSuperficie("visor");
$("#visor .ant").onclick = () => moverVisor(-1);
$("#visor .sig").onclick = () => moverVisor(1);
$("#sel-limpiar").onclick = () => cerrarSuperficie("detalle");
$("#filtro-etiquetas").oninput = pintarEtiquetas;
$("#tamano").oninput = (e) => document.documentElement.style.setProperty("--tam", e.target.value + "px");
let tBuscar;
$("#buscar").oninput = (e) => { const q = e.target.value; clearTimeout(tBuscar); tBuscar = setTimeout(() => filtrar({ q }), 300); };
$("#nueva-etiqueta").onkeydown = (e) => {
  if (e.key === "Enter" && e.target.value.trim()) {
    etiquetar({ agregar: [e.target.value.trim()] });
    e.target.value = "";
  }
};
document.addEventListener("keydown", (e) => {
  if (document.querySelector("dialog[open]")) return;
  const enInput = ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(e.target.tagName);
  if (!$("#visor").hidden) {
    if (e.key === "Escape") { e.preventDefault(); cerrarSuperficie("visor"); }
    if (e.key === "ArrowLeft") moverVisor(-1);
    if (e.key === "ArrowRight") moverVisor(1);
    return;
  }
  if (e.key === "Escape" && !enInput && estado.sel.size) cerrarSuperficie("seleccion");
  if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !enInput && estado.sel.size === 1) {
    e.preventDefault();
    moverSeleccion(e.key === "ArrowLeft" ? -1 : 1);
  }
  if (e.key === "a" && (e.ctrlKey || e.metaKey) && !enInput) {
    e.preventDefault();
    estado.fotos.forEach((f) => estado.sel.add(f.id));
    pintarSeleccion();
  }
});
new IntersectionObserver((entradas) => entradas[0].isIntersecting && cargarMas(), { root: $("main"), rootMargin: "800px" })
  .observe($("#centinela"));

document.addEventListener("DOMContentLoaded", () => leerURL().then(async () => {
  history.replaceState({ pm: true, seccion: "fotos", capas: [] }, "", location.search || location.pathname);
  await cargarResumen();
  await recargar(false);
}).catch(() => estadoGaleria("No se pudo conectar con el PC.", true)));

function formatoFecha(fecha) {
  if (!fecha) return "Sin fecha";
  if (fecha.length <= 10) return formatoDia(fecha);
  return formatoDia(fecha.slice(0, 10)) + " · " + fecha.slice(11);
}

function pintarSugerencias() {
  const fotos = estado.fotos.filter(f => estado.sel.has(f.id));
  for (const { rama, limite, lista } of GRUPOS) {
    const todas = estado.etiquetas.filter(t => t.id.startsWith(rama + "|"));
    $(`#lista-${lista}`).replaceChildren(...todas.map(t => el("option", { value: t.id.slice(rama.length + 1) })));
    const frecuentes = todas.filter(t => !(rama === "personas" && ["desconocido", "desconocida", "sin-nombre"].includes(t.id.split("|").pop())))
      .sort((a, b) => b.total - a.total || a.id.localeCompare(b.id)).slice(0, limite);
    $(`#frecuentes-${rama}`).replaceChildren(...frecuentes.map(t => {
      const asignada = fotos.length > 0 && fotos.every(f => f.etiquetas.includes(t.id));
      const b = el("button", { textContent: `${asignada ? "✓" : "+"} ${t.id.slice(rama.length + 1).replaceAll("-", " ").replaceAll("|", " › ")} · ${t.total}`, disabled: asignada, title: `${t.total} fotos en la biblioteca` });
      b.onclick = () => etiquetar({ agregar: [t.id] });
      return b;
    }));
    if (!todas.length) $(`#frecuentes-${rama}`).append(el("small", { textContent: "Todavía no hay etiquetas en este grupo. Puedes crearlas en Administrar." }));
  }
}

$("#tipo-principal").onchange = e => { if (e.target.value) etiquetar({ agregar: ["tipo|" + e.target.value] }); };
async function agregarEnGrupo(g) {
  const input = $("#" + g.entrada), valor = input.value.trim();
  if (!valor || !estado.sel.size) return;
  await etiquetar({ agregar: [valor.startsWith(g.rama + "|") ? valor : g.rama + "|" + valor] });
  if (input.value.trim() === valor) input.value = "";
}
for (const g of GRUPOS) {
  $("#" + g.entrada).onkeydown = async e => {
    if (e.key !== "Enter" || !e.target.value.trim()) return;
    e.preventDefault();
    await agregarEnGrupo(g);
  };
}

async function cargarConexion() {
  try {
    const r = await api("/api/conexion");
    const contenido = [el("p", { textContent: r.habilitada ? "Conecta el celular a la misma red Wi-Fi." : "Acceso local. Reinicia sin --host 127.0.0.1 para habilitar la red." })];
    for (const url of r.urls) {
      const copiar = el("button", { textContent: "Copiar", title: "Copiar dirección" });
      copiar.onclick = async () => {
        try {
          if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(url);
          else {
            const texto = el("textarea", { value: url }); document.body.append(texto); texto.select();
            const ok = document.execCommand("copy"); texto.remove(); if (!ok) throw new Error("copy");
          }
          aviso("Dirección copiada");
        } catch { aviso("Copia manualmente la dirección mostrada", true); }
      };
      contenido.push(el("div", { className: "direccion-red" }, el("a", { href: url, textContent: url }), copiar));
    }
    if (r.habilitada && !r.urls.length) contenido.push(el("p", { textContent: "No se detectó una dirección de red. Revisa la conexión del PC." }));
    $("#conexion-direcciones").replaceChildren(...contenido);
  } catch { $("#conexion-direcciones").textContent = "No se pudo consultar el acceso de red."; }
}
cargarConexion();

let datosPreview = null, datosIds = [], datosOcupado = false;
function invalidarDatos() { datosPreview = null; $("#datos-preview").hidden = true; }
$("#editar-datos").onclick = () => {
  datosIds = [...estado.sel]; invalidarDatos();
  $("#form-datos").reset();
  $("#campos-fecha").disabled = $("#campos-lugar").disabled = true;
  cambiarPrecision();
  const fotos = estado.fotos.filter(f => estado.sel.has(f.id));
  if (fotos.length === 1 && fotos[0].fecha) {
    $("#fecha-precision").value = fotos[0].fecha_precision || ({4:"ano",7:"mes",10:"dia"}[fotos[0].fecha.length] || "hora");
    cambiarPrecision(); $("#fecha-valor").value = fotos[0].fecha;
  }
  $("#editor-seleccion").textContent = `${datosIds.length} foto(s) seleccionadas. Activa únicamente los campos que deseas cambiar.`;
  $("#datos-resultado").replaceChildren();
  $("#editor-datos").showModal();
};
function cambiarPrecision() {
  const input = $("#fecha-valor"), precision = $("#fecha-precision").value;
  input.type = { ano: "number", mes: "month", dia: "date", hora: "datetime-local" }[precision];
  input.removeAttribute("min"); input.removeAttribute("max"); input.removeAttribute("step");
  if (precision === "ano") { input.min = "1"; input.max = "9999"; input.step = "1"; input.placeholder = "2020"; }
  if (precision === "hora") input.step = "1";
  invalidarDatos();
}
$("#fecha-precision").onchange = cambiarPrecision;
$("#modificar-fecha").onchange = e => { $("#campos-fecha").disabled = !e.target.checked; invalidarDatos(); };
$("#modificar-lugar").onchange = e => { $("#campos-lugar").disabled = !e.target.checked; invalidarDatos(); };
$("#form-datos").addEventListener("input", invalidarDatos);
$("#editor-cerrar").onclick = $("#editor-listo").onclick = () => { if (!datosOcupado) $("#editor-datos").close(); };
$("#editor-datos").addEventListener("cancel", e => { if (datosOcupado) e.preventDefault(); });
async function accionDatos(fn) {
  if (datosOcupado) return;
  datosOcupado = true;
  const controles = [...$("#editor-datos").querySelectorAll("button, input, select")];
  const anteriores = controles.map(x => x.disabled);
  controles.forEach(x => x.disabled = true);
  try { await fn(); }
  catch (e) { $("#datos-resultado").textContent = "Error: " + e.message; invalidarDatos(); }
  finally { controles.forEach((x, i) => x.disabled = anteriores[i]); datosOcupado = false; }
}
$("#form-datos").onsubmit = e => {
  e.preventDefault();
  const cambio = { ids: datosIds };
  if ($("#modificar-fecha").checked) cambio.fecha = $("#fecha-valor").value;
  if ($("#modificar-lugar").checked) cambio.lugar = $("#lugar-valor").value;
  accionDatos(async () => {
    datosPreview = await api("/api/metadatos/preview", cambio);
    $("#datos-impacto").textContent = `${datosPreview.fotos} foto(s). ${datosPreview.fecha ? "Fecha: " + formatoFecha(datosPreview.fecha) + ". Se reemplazan " + datosPreview.fechas_existentes + " fechas existentes. " : ""}${datosPreview.lugar ? "Agregar lugar: " + datosPreview.lugar + ". " : ""}Los demás campos se conservan.`;
    $("#datos-preview").hidden = false;
    $("#datos-resultado").textContent = "Revisa los cambios antes de guardar.";
  });
};
$("#datos-confirmar").onclick = () => accionDatos(async () => {
  if (!datosPreview) return;
  const r = await api("/api/metadatos/aplicar", datosPreview);
  invalidarDatos();
  $("#datos-resultado").replaceChildren(el("p", { textContent: `${r.completadas.length} foto(s) completadas; ${r.fallidas.length} con errores.` }),
    ...r.completadas.map(f => el("p", { textContent: "✓ " + f.ruta })),
    ...r.fallidas.map(f => el("p", { textContent: `Error en ${f.ruta}: ${f.error}` })));
  estado.sel.clear();
  estado.ultimo = null;
  await cargarResumen(); await recargar();
});

// ---------- mover y enviar a la papelera ----------
let operacionPreview = null, operacionTipo = "", operacionSeleccion = "", operacionOcupada = false;
let operacionGeneracion = 0, operacionCaducidad;
function firmaSeleccion() { return [...estado.sel].sort((a, b) => a - b).join(","); }
function invalidarOperacion() {
  operacionGeneracion++; operacionPreview = null;
  clearTimeout(operacionCaducidad);
  $("#operaciones-preview").hidden = true;
  $("#operaciones-texto").value = "";
  $("#operaciones-confirmar").disabled = true;
}
function controlesOperacion() {
  $("#operaciones").querySelectorAll("button, input, select").forEach(x => x.disabled = operacionOcupada);
  $("#operaciones-confirmar").disabled = operacionOcupada || !operacionPreview || $("#operaciones-texto").value !== operacionPreview.frase;
}
async function abrirOperacion(tipo) {
  if (!estado.sel.size || operacionOcupada) return;
  invalidarOperacion(); operacionTipo = tipo; operacionSeleccion = firmaSeleccion();
  $("#operaciones-titulo").textContent = tipo === "mover" ? "Mover de carpeta" : "Enviar a la papelera";
  $("#operaciones-alcance").textContent = `${estado.sel.size} foto(s) seleccionadas explícitamente. Los filtros no agregan otras fotos a esta operación.`;
  $("#operaciones-carpeta").hidden = tipo !== "mover";
  $("#operaciones-papelera").hidden = tipo !== "papelera";
  $("#operaciones-resultado").replaceChildren();
  $("#operaciones-destino").replaceChildren(el("option", {value: "__elegir__", textContent: "Cargando…"}));
  $("#operaciones").showModal();
  if (tipo === "mover") {
    operacionOcupada = true; controlesOperacion();
    try {
      const r = await api("/api/operaciones/carpetas");
      $("#operaciones-destino").replaceChildren(el("option", {value: "__elegir__", textContent: "Elige una carpeta…"}),
        ...r.carpetas.map(c => el("option", {value: c.ruta, textContent: c.absoluta})));
    } catch(e) { $("#operaciones-resultado").textContent = e.message; }
    finally { operacionOcupada = false; controlesOperacion(); }
  } else controlesOperacion();
}
$("#mover-fotos").onclick = () => abrirOperacion("mover");
$("#papelera-fotos").onclick = () => abrirOperacion("papelera");
$("#operaciones-destino").onchange = () => { invalidarOperacion(); controlesOperacion(); };
$("#operaciones-texto").oninput = controlesOperacion;
$("#operaciones-texto").onfocus = e => e.target.scrollIntoView({block: "center"});
function cerrarOperacion() { if (!operacionOcupada) { invalidarOperacion(); $("#operaciones").close(); } }
$("#operaciones-cerrar").onclick = $("#operaciones-cancelar").onclick = cerrarOperacion;
$("#operaciones").addEventListener("cancel", e => { if (operacionOcupada) e.preventDefault(); else invalidarOperacion(); });
$("#operaciones-revisar").onclick = async () => {
  if (operacionOcupada) return;
  invalidarOperacion();
  if (operacionTipo === "mover" && $("#operaciones-destino").value === "__elegir__") {
    $("#operaciones-resultado").textContent = "Elige una carpeta de destino."; return;
  }
  operacionSeleccion = firmaSeleccion();
  const generacion = operacionGeneracion;
  operacionOcupada = true; controlesOperacion();
  try {
    const r = await api("/api/operaciones/preview", {ids: [...estado.sel], operacion: operacionTipo,
      destino: operacionTipo === "mover" ? $("#operaciones-destino").value : ""});
    if (generacion !== operacionGeneracion || operacionSeleccion !== firmaSeleccion()) return;
    operacionPreview = r;
    $("#operaciones-impacto").textContent = `${r.fotos} foto(s). Biblioteca: ${r.biblioteca}. Destino: ${r.destino || "Papelera de Windows del PC del gestor"}.`;
    const grupos = new Map();
    r.archivos.forEach(f => { if (!grupos.has(f.carpeta)) grupos.set(f.carpeta, []); grupos.get(f.carpeta).push(f); });
    $("#operaciones-lista").replaceChildren(...[...grupos].map(([carpeta, archivos]) =>
      el("section", {}, el("h3", {textContent: `${carpeta} · ${archivos.length} foto(s)`}),
        ...archivos.map(f => el("div", {className: "operacion-foto"},
          el("img", {src: `/api/miniatura/${f.id}`, loading: "lazy", alt: ""}),
          el("div", {}, el("strong", {textContent: f.nombre}), el("p", {textContent: f.origen}),
            ...(f.destino ? [el("p", {textContent: "→ " + f.destino})] : [])))))));
    $("#operaciones-frase").textContent = r.frase;
    $("#operaciones-preview").hidden = false;
    $("#operaciones-resultado").textContent = "Revisa todos los archivos y escribe la frase para continuar.";
    operacionCaducidad = setTimeout(() => { invalidarOperacion(); $("#operaciones-resultado").textContent = "La revisión venció. Revisa nuevamente."; }, r.vigencia_segundos * 1000);
  } catch(e) { $("#operaciones-resultado").textContent = "Error: " + e.message; }
  finally { operacionOcupada = false; controlesOperacion(); }
};
$("#operaciones-confirmar").onclick = async () => {
  if (operacionOcupada || !operacionPreview || $("#operaciones-texto").value !== operacionPreview.frase) return;
  if (operacionSeleccion !== firmaSeleccion()) { invalidarOperacion(); return; }
  const cambio = {token: operacionPreview.token, texto: $("#operaciones-texto").value};
  operacionOcupada = true; invalidarOperacion(); controlesOperacion();
  try {
    const r = await api("/api/operaciones/aplicar", cambio);
    $("#operaciones-resultado").replaceChildren(
      el("p", {textContent: `${r.completadas.length} completadas; ${r.fallidas.length} con errores; ${r.pendientes.length} pendientes. Bitácora: ${r.bitacora}`}),
      ...r.completadas.map(f => el("p", {textContent: "✓ " + f.ruta + (f.destino ? " → " + f.destino : " → Papelera de Windows")})),
      ...r.fallidas.map(f => el("p", {textContent: `Error en ${f.ruta}: ${f.error}${f.archivo_modificado ? " El archivo fue modificado; revisa el disco y vuelve a indexar antes de continuar." : ""}`})),
      ...r.pendientes.map(f => el("p", {textContent: "Pendiente: " + f.ruta})));
  } catch(e) { $("#operaciones-resultado").textContent = "Error: " + e.message + ". Revisa el resultado antes de intentar otra operación."; }
  finally {
    estado.sel.clear(); estado.ultimo = null;
    try { await cargarResumen(); await recargar(); }
    catch(e) { $("#operaciones-resultado").append(el("p", {textContent: "No se pudo refrescar la galería: " + e.message})); }
    operacionOcupada = false; controlesOperacion();
  }
};
