"""Panel web local: se abre con `python fotos.py panel` y se cierra al terminar."""
import json
import hashlib
import threading
from collections import Counter
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import indice, catalogo, fechas, red
from .config import BIBLIOTECA, CARPETAS_TIPO, DATOS
from .etiquetas import asignaciones, hojas, normalizar
from .exif import ExifTool

ESTATICOS = Path(__file__).parent / "static"
CARPETAS_NO_FOTO = {p.name for p in CARPETAS_TIPO.values()}

app = FastAPI(title="Gestor de fotos")
db = indice.conectar()
et = ExifTool()
_escritura = threading.RLock()
CATALOGO = DATOS / "etiquetas.json"
TIPOS = {"foto", "captura", "meme", "documento", "otro"}


@app.get("/api/conexion")
def conexion():
    return red.conexion(getattr(app.state, "host", "127.0.0.1"), getattr(app.state, "puerto", 8642))


# ---------- bandejas ----------

def _personas_esperadas(etqs) -> int:
    for e in etqs:
        if e.startswith("_ia|personas|"):
            try:
                return int(e.rsplit("|", 1)[1])
            except ValueError:
                pass
    return 0


def _nombradas(etqs) -> int:
    return sum(1 for e in etqs if e.startswith("personas|"))


BANDEJAS = {
    "todas": ("Todas", lambda f, e: True),
    "entrada": ("Entrada", lambda f, e: f["ruta"].startswith("entrada/")),
    "sin-clasificar": ("Sin clasificar (IA)", lambda f, e: not any(x.startswith("_ia|") for x in e)),
    "sin-tipo": ("Sin tipo", lambda f, e: not any(x.startswith("tipo|") for x in e)),
    "sin-etiquetas": ("Sin etiquetas", lambda f, e: not any(not x.startswith(("_", "tipo|")) for x in e)),
    "personas-sin-nombre": ("Personas sin nombre", lambda f, e: _personas_esperadas(e) > _nombradas(e)),
    "sugerencias": ("Sugerencias por confirmar", lambda f, e: any(x.startswith("_sugerencias|") for x in e)),
    "sin-fecha": ("Sin fecha", lambda f, e: not f["fecha"]),
    "sin-lugar": ("Sin lugar", lambda f, e: f["lat"] is None and not any(x.startswith("lugar|") for x in e)),
    "sin-estilo": ("Sin estilo", lambda f, e: not any(x.startswith("estilo|") for x in e)),
    "sin-momento": ("Sin momento", lambda f, e: not any(x.startswith("momento|") for x in e)),
    "sin-tema": ("Sin tema", lambda f, e: not any(x.startswith("tema|") for x in e)),
    "sin-persona": ("Sin persona", lambda f, e: not any(x.startswith("personas|") for x in e)),
}


def _todas():
    with _escritura:
        filas = db.execute("SELECT * FROM fotos ORDER BY fecha DESC, ruta").fetchall()
    return [(dict(f), json.loads(f["etiquetas"])) for f in filas]


@app.get("/api/resumen")
def resumen():
    fotos = _todas()
    bandejas = [{"id": k, "nombre": n, "total": sum(1 for f, e in fotos if fn(f, e))}
                for k, (n, fn) in BANDEJAS.items()]
    carpetas = Counter(f["carpeta"] for f, _ in fotos)
    return {"bandejas": bandejas,
            "carpetas": sorted(({"id": c, "total": n} for c, n in carpetas.items()),
                               key=lambda c: (not c["id"].isdigit(), c["id"]), reverse=False),
            "etiquetas": catalogo.resumen(fotos, catalogo.leer(CATALOGO))}


class NombreEtiqueta(BaseModel):
    nombre: str


class RenombrarEtiqueta(BaseModel):
    origen: str
    destino: str
    confirmacion: str = ""


def _nombre(texto):
    nombre = normalizar(texto)
    if not nombre or len(nombre) > 200:
        raise HTTPException(400, "Escribe una etiqueta de hasta 200 caracteres.")
    return nombre


@app.post("/api/etiquetas/crear")
def crear_etiqueta(cambio: NombreEtiqueta):
    nombre = _nombre(cambio.nombre)
    with _escritura:
        existentes = catalogo.resumen(_todas(), catalogo.leer(CATALOGO))
        if any(t["id"] == nombre for t in existentes):
            raise HTTPException(409, "La etiqueta ya existe.")
        catalogo.guardar(CATALOGO, catalogo.leer(CATALOGO) | {nombre})
    return {"nombre": nombre}


def _plan_renombrar(cambio):
    origen, destino = _nombre(cambio.origen), _nombre(cambio.destino)
    fotos = _todas()
    guardadas = catalogo.leer(CATALOGO)
    existentes = {t["id"] for t in catalogo.resumen(fotos, guardadas)}
    if origen not in existentes:
        raise HTTPException(404, "La etiqueta ya no existe.")
    if origen == destino or catalogo.pertenece(destino, origen):
        raise HTTPException(400, "Elige otro nombre fuera de la propia rama.")
    destinos = {destino + t[len(origen):] for t in existentes if catalogo.pertenece(t, origen)}
    if destinos & (existentes - {t for t in existentes if catalogo.pertenece(t, origen)}):
        raise HTTPException(409, "El destino ya existe; no se fusionan etiquetas al renombrar.")
    afectadas = [(f, e) for f, e in fotos if any(catalogo.pertenece(t, origen) for t in e)]
    for _, etiquetas in afectadas:
        nuevas = catalogo.renombradas(etiquetas, origen, destino)
        if {t for t in nuevas if t.startswith("tipo|")} != {t for t in etiquetas if t.startswith("tipo|")}:
            _tipos_validos([t for t in nuevas if t.startswith("tipo|")])
    firma = hashlib.sha256(json.dumps([origen, destino, sorted(guardadas),
        [(f["ruta"], f["firma"], e) for f, e in afectadas]], sort_keys=True).encode()).hexdigest()
    return origen, destino, guardadas, afectadas, firma


@app.post("/api/etiquetas/renombrar/preview")
def preview_renombrar(cambio: RenombrarEtiqueta):
    with _escritura:
        origen, destino, _, afectadas, firma = _plan_renombrar(cambio)
    return {"origen": origen, "destino": destino, "fotos": len(afectadas), "confirmacion": firma}


@app.post("/api/etiquetas/renombrar")
def renombrar_etiqueta(cambio: RenombrarEtiqueta):
    with _escritura:
        origen, destino, guardadas, afectadas, firma = _plan_renombrar(cambio)
        flujo.comprobar_libre()
        if cambio.confirmacion != firma:
            raise HTTPException(409, "Revisa de nuevo las fotos afectadas antes de confirmar.")
        actualizadas = []
        try:
            for f, etiquetas in afectadas:
                ruta = BIBLIOTECA / f["ruta"]
                meta = et.leer([ruta], "-XMP-lr:HierarchicalSubject")
                actuales = meta[0].get("HierarchicalSubject", []) if meta else None
                if isinstance(actuales, str):
                    actuales = [actuales]
                if actuales is None or hojas(actuales) != hojas(etiquetas):
                    raise RuntimeError("Los metadatos cambiaron; vuelve a indexar la biblioteca.")
                nuevas = catalogo.renombradas(actuales, origen, destino)
                et.escribir(ruta, *asignaciones(nuevas))
                actualizadas.append(f["ruta"])
                comprobacion = et.leer([ruta], "-XMP-lr:HierarchicalSubject")
                valor = comprobacion[0].get("HierarchicalSubject", []) if comprobacion else []
                if hojas([valor] if isinstance(valor, str) else valor) != nuevas:
                    raise RuntimeError("No se pudo verificar la escritura de metadatos.")
            catalogo.guardar(CATALOGO, set(catalogo.renombradas(guardadas, origen, destino)) | {destino})
        except Exception as exc:
            raise HTTPException(500, f"Renombrado interrumpido tras {len(actualizadas)} fotos. {exc}") from exc
        finally:
            if actualizadas:
                indice.releer(db, et, actualizadas)
    return {"origen": origen, "destino": destino, "actualizadas": len(actualizadas)}


@app.get("/api/fotos")
def fotos(bandeja: str = "todas", carpeta: str = "", etiqueta: str = "", q: str = "",
          offset: int = 0, limite: int = 300):
    filtro = BANDEJAS.get(bandeja, BANDEJAS["todas"])[1]
    q = q.lower().strip()
    salida = []
    for f, e in _todas():
        if not filtro(f, e):
            continue
        if carpeta and f["carpeta"] != carpeta:
            continue
        if etiqueta and not any(x == etiqueta or x.startswith(etiqueta + "|") for x in e):
            continue
        if q and q not in (f["ruta"] + " " + " ".join(e) + " " + (f["descripcion"] or "")).lower():
            continue
        salida.append({"id": f["id"], "ruta": f["ruta"], "fecha": f["fecha"], "fecha_precision": fechas.precision(f["fecha"]), "etiquetas": e,
                       "pendientes": flujo.pendientes(f),
                       "caras": json.loads(f["caras"]), "descripcion": f["descripcion"],
                       "gps": f["lat"] is not None, "camara": f["camara"]})
    return {"total": len(salida), "fotos": salida[offset:offset + limite]}


def _ruta(foto_id: int) -> str:
    with _escritura:
        fila = db.execute("SELECT ruta FROM fotos WHERE id = ?", (foto_id,)).fetchone()
    if not fila:
        raise HTTPException(404)
    return fila["ruta"]


@app.get("/api/miniatura/{foto_id}")
def miniatura(foto_id: int, lado: int = 360):
    if lado not in (360, 1024):
        raise HTTPException(400, "lado debe ser 360 o 1024")
    return FileResponse(indice.miniatura(_ruta(foto_id), lado), headers={"Cache-Control": "max-age=86400"})


_CAMPOS_DETALLE = ["-Make", "-Model", "-LensModel", "-ISO", "-ExposureTime", "-FNumber",
                   "-FocalLength", "-FileSize", "-Software"]


@app.get("/api/foto/{foto_id}")
def detalle(foto_id: int):
    with _escritura:
        fila = db.execute("SELECT * FROM fotos WHERE id = ?", (foto_id,)).fetchone()
    if not fila:
        raise HTTPException(404)
    with _escritura:
        exif = (et.leer([BIBLIOTECA / fila["ruta"]], *_CAMPOS_DETALLE) or [{}])[0]
    exif.pop("SourceFile", None)
    foto = dict(fila)
    foto["etiquetas"] = json.loads(foto["etiquetas"])
    foto["caras"] = json.loads(foto["caras"])
    return {**foto, "fecha_precision": fechas.precision(foto["fecha"]), "exif": exif}


@app.get("/api/original/{foto_id}")
def original(foto_id: int):
    return FileResponse(BIBLIOTECA / _ruta(foto_id))


class Etiquetado(BaseModel):
    ids: list[int]
    agregar: list[str] = []
    quitar: list[str] = []


def _tipos_validos(agregar):
    tipos = [t for t in agregar if t.startswith("tipo|")]
    if len(set(tipos)) > 1 or any(t not in {"tipo|" + v for v in TIPOS} for t in tipos):
        raise HTTPException(400, "Elige un solo tipo: foto, captura, meme, documento u otro.")
    return tipos


class DatosFotos(BaseModel):
    ids: list[int]
    fecha: str | None = None
    lugar: str | None = None
    confirmacion: str = ""


def _plan_datos(cambio):
    if not cambio.ids or (cambio.fecha is None and cambio.lugar is None):
        raise HTTPException(400, "Selecciona fotos y al menos un campo para modificar.")
    try:
        fecha = fechas.normalizar(cambio.fecha) if cambio.fecha is not None else None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    lugar = None
    if cambio.lugar is not None:
        texto = cambio.lugar.strip()
        if texto.lower().startswith("lugar|"):
            texto = texto.split("|", 1)[1]
        if not normalizar(texto):
            raise HTTPException(400, "Escribe el nombre del lugar.")
        lugar = "lugar|" + _nombre(texto)
        if len(lugar) > 200:
            raise HTTPException(400, "El lugar es demasiado largo.")
    filas = []
    for foto_id in sorted(set(cambio.ids)):
        fila = db.execute("SELECT * FROM fotos WHERE id = ?", (foto_id,)).fetchone()
        if not fila:
            raise HTTPException(404, "Una foto de la selección ya no existe.")
        filas.append(dict(fila))
    firma = hashlib.sha256(json.dumps([fecha, lugar, [(f["id"], f["ruta"], f["fecha"], f["etiquetas"],
        (BIBLIOTECA / f["ruta"]).stat().st_size, (BIBLIOTECA / f["ruta"]).stat().st_mtime_ns) for f in filas]], sort_keys=True).encode()).hexdigest()
    return fecha, lugar, filas, firma


@app.post("/api/metadatos/preview")
def preview_metadatos(cambio: DatosFotos):
    with _escritura:
        fecha, lugar, filas, firma = _plan_datos(cambio)
    return {"ids": [f["id"] for f in filas], "fecha": fecha, "fecha_precision": fechas.precision(fecha),
            "lugar": lugar, "fotos": len(filas), "fechas_existentes": sum(bool(f["fecha"]) for f in filas) if fecha else 0,
            "confirmacion": firma}


@app.post("/api/metadatos/aplicar")
def aplicar_metadatos(cambio: DatosFotos):
    with _escritura:
        flujo.comprobar_libre()
        fecha, lugar, filas, firma = _plan_datos(cambio)
        if cambio.confirmacion != firma:
            raise HTTPException(409, "La selección cambió. Revisa de nuevo los cambios antes de confirmar.")
        completadas, fallidas = [], []
        for f in filas:
            ruta = BIBLIOTECA / f["ruta"]
            try:
                meta = (et.leer([ruta], "-XMP-lr:HierarchicalSubject") or [None])[0]
                if meta is None:
                    raise RuntimeError("No se pudieron leer los metadatos.")
                args = []
                nuevas = None
                if lugar:
                    valor = meta.get("HierarchicalSubject") or []
                    actuales = [valor] if isinstance(valor, str) else valor
                    nuevas = hojas([*actuales, lugar])
                    args.extend(asignaciones(nuevas))
                if fecha:
                    args.append("-XMP-photoshop:DateCreated=" + fecha.replace("T", " "))
                et.escribir(ruta, *args)
                verificacion = (et.leer([ruta], "-XMP-photoshop:DateCreated", "-XMP-lr:HierarchicalSubject") or [{}])[0]
                if fecha and fechas.normalizar(verificacion.get("DateCreated")) != fecha:
                    raise RuntimeError("No se verificó la fecha escrita.")
                valor = verificacion.get("HierarchicalSubject") or []
                if nuevas is not None and hojas([valor] if isinstance(valor, str) else valor) != nuevas:
                    raise RuntimeError("No se verificaron las etiquetas escritas.")
                completadas.append({"id": f["id"], "ruta": f["ruta"]})
            except Exception as exc:
                fallidas.append({"id": f["id"], "ruta": f["ruta"], "error": str(exc)})
            finally:
                try:
                    indice.releer(db, et, [f["ruta"]])
                except Exception as exc:
                    completadas = [x for x in completadas if x["id"] != f["id"]]
                    fallidas.append({"id": f["id"], "ruta": f["ruta"], "error": "No se actualizó el índice: " + str(exc)})
        return {"ok": not fallidas, "completadas": completadas, "fallidas": fallidas}


@app.post("/api/etiquetar")
def etiquetar(cambio: Etiquetado):
    agregar = [normalizar(t) for t in cambio.agregar if normalizar(t)]
    quitar = [normalizar(t) for t in cambio.quitar if normalizar(t)]
    tipos = _tipos_validos(agregar)
    rutas = list(dict.fromkeys(_ruta(i) for i in cambio.ids))
    completadas, fallidas = [], []
    with _escritura:
        flujo.comprobar_libre()
        metas = et.leer([BIBLIOTECA / r for r in rutas], "-XMP-lr:HierarchicalSubject")
        por_ruta = {Path(m["SourceFile"]).resolve(): m for m in metas}
        for ruta in rutas:
            try:
                meta = por_ruta.get((BIBLIOTECA / ruta).resolve())
                if meta is None:
                    raise RuntimeError("No se pudieron leer los metadatos.")
                actuales = meta.get("HierarchicalSubject") or []
                actuales = set(hojas(actuales if isinstance(actuales, list) else [actuales]))
                nuevas = {t for t in actuales if not (tipos and t.startswith("tipo|"))
                          and not any(t == q or t.startswith(q + "|") for q in quitar)}
                nuevas = set(hojas(nuevas | set(agregar)))
                if nuevas != actuales:
                    et.escribir(meta["SourceFile"], *asignaciones(nuevas))
                    verificacion = et.leer([BIBLIOTECA / ruta], "-XMP-lr:HierarchicalSubject")
                    valor = (verificacion[0].get("HierarchicalSubject") or []) if verificacion else []
                    if set(hojas([valor] if isinstance(valor, str) else valor)) != nuevas:
                        raise RuntimeError("No se verificaron las etiquetas escritas.")
                indice.releer(db, et, [ruta])
                completadas.append(ruta)
            except Exception as exc:
                fallidas.append({"ruta": ruta, "error": str(exc)})
                try:
                    indice.releer(db, et, [ruta])
                except Exception as error_indice:
                    fallidas[-1]["error"] += "; No se actualizó el índice: " + str(error_indice)
    return {"ok": not fallidas, "actualizadas": len(completadas), "fallidas": fallidas}


# ---------- operaciones de archivos ----------
from .operaciones import Operaciones

operaciones = Operaciones(BIBLIOTECA, DATOS, db, _escritura)


class OperacionPreview(BaseModel):
    ids: list[int]
    operacion: str
    destino: str = ""


class OperacionConfirmar(BaseModel):
    token: str
    texto: str


@app.get("/api/operaciones/carpetas")
def carpetas_operaciones():
    with _escritura:
        return {"carpetas": operaciones.carpetas()}


@app.post("/api/operaciones/preview")
def preview_operacion(cambio: OperacionPreview):
    return operaciones.preview(cambio.ids, cambio.operacion, cambio.destino)


@app.post("/api/operaciones/aplicar")
def aplicar_operacion(cambio: OperacionConfirmar):
    with _escritura:
        flujo.comprobar_libre()
        return operaciones.aplicar(cambio.token, cambio.texto)


# ---------- entrada, auditoría y trabajos ----------
from .flujo import Flujo, PERFIL, organizacion

flujo = Flujo(BIBLIOTECA, DATOS, db, _escritura, et)


class TrabajoNuevo(BaseModel):
    operacion: str
    ids: list[int] | None = None


class FlujoPreview(BaseModel):
    ids: list[int]
    operacion: str
    respaldo: str = ""
    destinos: dict[str, str] = {}


@app.get("/api/flujo/config")
def configuracion_flujo():
    p = DATOS / "flujo-config.json"
    return {"perfil": PERFIL, "respaldo": json.loads(p.read_text(encoding="utf-8")).get("respaldo", "") if p.exists() else ""}


@app.get("/api/flujo/auditoria")
def resultados_auditoria():
    return {"fotos": flujo.resultados()}


@app.get("/api/flujo/trabajos")
def trabajos_flujo():
    return {"trabajos": flujo.trabajos()}


@app.post("/api/flujo/trabajos")
def iniciar_trabajo(cambio: TrabajoNuevo):
    return flujo.iniciar(cambio.operacion, cambio.ids)


@app.post("/api/flujo/trabajos/{identificador}/cancelar")
def cancelar_trabajo(identificador: str):
    return flujo.cancelar(identificador)


@app.post("/api/flujo/preview")
def preparar_flujo(cambio: FlujoPreview):
    return flujo.preparar(cambio.ids, cambio.operacion, cambio.respaldo, cambio.destinos)


@app.post("/api/flujo/sugerencias")
def sugerencias_flujo(cambio: FlujoPreview):
    return {"archivos": flujo.sugerencias(cambio.ids)}


@app.post("/api/flujo/aplicar")
def confirmar_flujo(cambio: OperacionConfirmar):
    return flujo.confirmar(cambio.token, cambio.texto)


@app.on_event("startup")
def _inicio():
    indice.sincronizar(db, et)


@app.on_event("shutdown")
def _fin():
    flujo.cerrar()
    et.cerrar()


app.mount("/", StaticFiles(directory=ESTATICOS, html=True), name="static")
