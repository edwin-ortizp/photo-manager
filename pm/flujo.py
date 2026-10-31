"""Auditoría y trabajos explícitos sobre la biblioteca; nunca se ejecutan al detectar fotos."""
import copy
import hashlib
import json
import math
import os
import secrets
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from . import fechas, indice
from .operaciones import Operaciones

VERSION = 1
PERFIL = {"max_lado": 3840, "calidad": 75, "bits": 8, "chroma": "4:2:0"}


def ejecutar(args):
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as exc:
        raise RuntimeError("Falta ImageMagick (magick) o ExifTool en el PC del gestor.") from exc
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout or "Falló la herramienta de imagen.")[-2000:])
    return r.stdout


def estado_archivo(p):
    return Operaciones._estado(p)


def escribir_temporal(args, advertencias):
    """Tolerar únicamente el error menor conocido; verificar los datos antes de publicar."""
    try:
        return ejecutar(args)
    except RuntimeError as exc:
        errores = [linea for linea in str(exc).splitlines() if linea.startswith("Error:")]
        if not errores or not all(linea.startswith("Error: [minor] Maker notes could not be parsed - ") for linea in errores):
            raise
        resultado = ejecutar([args[0], "-m", *args[1:]])
        aviso = "MakerNotes no reconocidas por ExifTool; se conservaron y verificaron byte por byte."
        if aviso not in advertencias:
            advertencias.append(aviso)
        return resultado


def maker_notes(p, exiftool):
    r = subprocess.run([exiftool, "-b", "-MakerNotes", str(p)], capture_output=True, timeout=300,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode:
        raise RuntimeError("No se pudieron leer las MakerNotes para verificar su conservación.")
    return r.stdout


def hash_archivo(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def guardar_json(p, valor):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(valor, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def equivalentes(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equivalentes(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equivalentes(x, y) for x, y in zip(a, b))
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-8)
    return a == b


def identidad_carpetas(p):
    return {str(a): estado_archivo(a)[:2] for a in [*reversed(p.parents), p] if a.exists()}


def organizacion(f):
    etiquetas = json.loads(f["etiquetas"])
    avisos = []
    if not f["fecha"]:
        avisos.append("sin-fecha")
    if not any(t.startswith("tipo|") for t in etiquetas):
        avisos.append("sin-tipo")
    if not any(t.startswith("_ia|") for t in etiquetas):
        avisos.append("sin-clasificar")
    esperadas = []
    for t in etiquetas:
        if t.startswith("_ia|personas|") and t.rsplit("|", 1)[-1].isdigit():
            esperadas.append(int(t.rsplit("|", 1)[-1]))
    nombradas = sum(t.startswith("personas|") and t != "personas|desconocido" for t in etiquetas)
    caras = [n for n in json.loads(f.get("caras", "[]")) if n and n.lower() != "desconocido"]
    if (esperadas and max(esperadas) > nombradas) or any("desconocido" in t for t in etiquetas if t.startswith("personas|")):
        avisos.append("personas-pendientes")
    elif caras and not nombradas:
        avisos.append("personas-pendientes")
    carpeta = f["ruta"].split("/")[0]
    if carpeta.isdigit() and len(carpeta) == 4 and f["fecha"] and carpeta != f["fecha"][:4]:
        avisos.append("ano-incoherente")
    return avisos


def inspeccionar(p, et):
    """Decodificar de verdad: identify -ping solo no detecta todos los archivos truncados."""
    meta = (et.leer([p], "-FileType", "-ImagePixelDepth", "-ChromaFormat") or [{}])[0]
    lineas = ejecutar(["magick", "identify", "-format", "%m|%w|%h|%z\n", str(p)]).strip().splitlines()
    if not lineas:
        raise RuntimeError("La imagen no se pudo decodificar.")
    formato, w, h, bits = lineas[0].split("|")
    es_avif = meta.get("FileType") == "AVIF" and formato == "AVIF"
    profundidad = meta.get("ImagePixelDepth") if es_avif else int(bits)
    chroma = meta.get("ChromaFormat")
    # AV1Configuration usa bits de submuestreo: X+Y=3 para 4:2:0.
    chroma = {0: "4:4:4", 2: "4:2:2", 3: "4:2:0", 7: "4:0:0"}.get(chroma, chroma)
    errores, avisos, desconocidos = [], [], []
    if len(lineas) != 1:
        errores.append("multiples-cuadros")
    if not es_avif:
        avisos.append("sin-avif")
    if max(int(w), int(h)) > PERFIL["max_lado"]:
        avisos.append("dimensiones")
    if es_avif:
        if profundidad is None:
            desconocidos.append("profundidad")
        elif profundidad != 8:
            avisos.append("profundidad")
        if chroma is None:
            desconocidos.append("muestreo")
        elif chroma != "4:2:0":
            avisos.append("muestreo")
    if p.suffix.lower() == ".avif" and not es_avif:
        avisos.append("extension-incoherente")
    return {"formato": meta.get("FileType") or formato, "ancho": int(w), "alto": int(h),
            "bits": profundidad, "chroma": chroma, "cuadros": len(lineas),
            "errores": errores, "avisos": avisos, "desconocidos": desconocidos,
            "conforme": es_avif and not (errores or avisos or desconocidos)}


def metadatos(p, et):
    campos = ["-G1", "-struct", "-XMP:all", "-IPTC:all", "-EXIF:DateTimeOriginal", "-EXIF:CreateDate",
              "-EXIF:OffsetTime*", "-EXIF:SubSecTime*", "-EXIF:GPS*", "-EXIF:Make", "-EXIF:Model",
              "-EXIF:ImageDescription", "-EXIF:Artist", "-EXIF:Copyright", "-EXIF:UserComment"]
    m = (et.leer([p], *campos) or [{}])[0]
    return {k: v for k, v in m.items() if k != "SourceFile" and not k.endswith(":XMPToolkit")}


def regiones_orientadas(meta, orientacion, ancho, alto):
    """Transformar rectángulos normalizados MWG junto con los píxeles."""
    m = copy.deepcopy(meta)
    for clave in list(m):
        if clave.endswith(":Orientation"):
            m[clave] = 1
    region = m.get("XMP-mwg-rs:RegionInfo")
    if not region:
        return m
    if orientacion != 1 and ("XMP-MP:RegionInfo" in m or "XMP-mp:RegionInfo" in m):
        raise RuntimeError("Las regiones de personas de este formato requieren revisión de orientación.")
    transformaciones = {1: lambda x, y: (x, y), 2: lambda x, y: (1-x, y),
                        3: lambda x, y: (1-x, 1-y), 4: lambda x, y: (x, 1-y),
                        5: lambda x, y: (y, x), 6: lambda x, y: (1-y, x),
                        7: lambda x, y: (1-y, 1-x), 8: lambda x, y: (y, 1-x)}
    for r in region.get("RegionList", []):
        a = r.get("Area", {})
        if a.get("Unit") != "normalized" or not all(k in a for k in ("X", "Y", "W", "H")):
            raise RuntimeError("Región de personas incompatible; el original se conserva.")
        a["X"], a["Y"] = transformaciones[orientacion](float(a["X"]), float(a["Y"]))
        if orientacion >= 5:
            a["W"], a["H"] = a["H"], a["W"]
    region["AppliedToDimensions"] = {"W": ancho, "H": alto, "Unit": "pixel"}
    return m


class Flujo:
    def __init__(self, biblioteca, datos, db, lock, et):
        self.biblioteca, self.datos, self.db, self.lock, self.et = Path(biblioteca).resolve(), Path(datos), db, lock, et
        self.ops = Operaciones(self.biblioteca, self.datos, db, lock)
        self.guard = threading.RLock()
        self.planes, self.hilo, self.cancelar_evento = {}, None, threading.Event()
        self.actual = None
        self.db.execute("CREATE TABLE IF NOT EXISTS auditorias (ruta TEXT PRIMARY KEY, estado TEXT, version INTEGER, resultado TEXT)")
        self.db.commit()
        for p in (self.datos / "trabajos").glob("*.json"):
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
                if j["estado"] in ("ejecutando", "pendiente"):
                    j["estado"] = "interrumpido"
                    guardar_json(p, j)
            except (OSError, ValueError, KeyError):
                continue

    def ocupado(self):
        return self.hilo is not None and self.hilo.is_alive()

    def comprobar_libre(self):
        if self.ocupado():
            raise HTTPException(409, "Hay un trabajo en curso. Espera o cancélalo antes de modificar fotos.")

    def _filas(self, ids):
        filas = []
        for i in sorted(set(ids)):
            f = self.db.execute("SELECT * FROM fotos WHERE id = ?", (i,)).fetchone()
            if not f:
                raise HTTPException(409, "Una foto ya no existe. Actualiza el inventario.")
            filas.append(dict(f))
        return filas

    def auditoria(self, f):
        p = self.ops._ruta(f["ruta"])
        estado = json.dumps(estado_archivo(p))
        r = self.db.execute("SELECT * FROM auditorias WHERE ruta = ?", (f["ruta"],)).fetchone()
        if r and r["estado"] == estado and r["version"] == VERSION:
            return json.loads(r["resultado"])
        try:
            resultado = inspeccionar(p, self.et)
        except Exception as exc:
            resultado = {"conforme": False, "errores": ["ilegible"], "avisos": [], "desconocidos": [], "detalle": str(exc)}
        if json.dumps(estado_archivo(p)) != estado:
            raise RuntimeError("El archivo cambió durante la auditoría.")
        self.db.execute("INSERT OR REPLACE INTO auditorias VALUES (?, ?, ?, ?)",
                        (f["ruta"], estado, VERSION, json.dumps(resultado)))
        self.db.commit()
        return resultado

    def resultados(self):
        with self.lock:
            salida = []
            for f in self._filas([r[0] for r in self.db.execute("SELECT id FROM fotos")]):
                r = self.db.execute("SELECT * FROM auditorias WHERE ruta = ?", (f["ruta"],)).fetchone()
                tecnico = None
                try:
                    if r and r["version"] == VERSION and r["estado"] == json.dumps(estado_archivo(self.ops._ruta(f["ruta"]))):
                        tecnico = json.loads(r["resultado"])
                except (OSError, HTTPException):
                    pass
                salida.append({"id": f["id"], "ruta": f["ruta"], "organizacion": organizacion(f), "tecnica": tecnico})
            return salida

    def pendientes(self, f):
        pendientes = organizacion(f)
        r = self.db.execute("SELECT * FROM auditorias WHERE ruta = ?", (f["ruta"],)).fetchone()
        try:
            if r and r["version"] == VERSION and r["estado"] == json.dumps(estado_archivo(self.ops._ruta(f["ruta"]))):
                t = json.loads(r["resultado"])
                return pendientes + t["errores"] + t["avisos"] + ["desconocido: " + x for x in t["desconocidos"]]
        except (HTTPException, OSError):
            pass
        return pendientes + (["conversion-por-revisar"] if not f["ruta"].lower().endswith(".avif") else ["avif-por-auditar"])

    def _externa(self, texto):
        p = Path(texto)
        if not texto.strip() or not p.is_absolute() or ".." in p.parts:
            raise HTTPException(400, "Indica una ruta absoluta para los originales en el PC del gestor.")
        self._componentes(p)
        p = p.resolve()
        if p.is_relative_to(self.biblioteca) or self.biblioteca.is_relative_to(p):
            raise HTTPException(400, "Elige una carpeta de originales fuera de la biblioteca y no una carpeta que la contenga.")
        self._componentes(p)
        return p

    @staticmethod
    def _componentes(p):
        for a in [*reversed(p.parents), p]:
            if hasattr(os.path, "isreserved") and a.name and os.path.isreserved(a.name):
                raise HTTPException(400, "El destino contiene un nombre reservado de Windows.")
            if a.is_symlink() or (hasattr(a, "is_junction") and a.is_junction()):
                raise HTTPException(400, "No se permiten enlaces o junctions en el destino.")
            if a.exists() and not a.is_dir():
                raise HTTPException(400, "Una parte del destino no es una carpeta.")

    def _destino(self, texto):
        p = Path(texto)
        if p.is_absolute() or p.drive or not p.parts or not texto or any(x.startswith(".") or ":" in x for x in p.parts):
            raise HTTPException(400, "El destino debe ser una carpeta relativa dentro de la biblioteca.")
        destino = self.biblioteca / p
        self._componentes(destino)
        if not destino.resolve().is_relative_to(self.biblioteca):
            raise HTTPException(400, "Destino fuera de la biblioteca.")
        return destino

    @staticmethod
    def sugerencia(f):
        tags = json.loads(f["etiquetas"])
        tipo = next((t.split("|", 1)[1] for t in tags if t.startswith("tipo|")), "foto")
        return {"captura": "capturas", "meme": "memes", "documento": "documentos"}.get(tipo) or (f["fecha"][:4] if f["fecha"] else "sin-fecha")

    def sugerencias(self, ids):
        with self.lock:
            return [{"id": f["id"], "ruta": f["ruta"], "carpeta_destino": self.sugerencia(f)} for f in self._filas(ids)]

    def preparar(self, ids, operacion, respaldo="", destinos=None):
        if operacion not in ("convertir", "organizar") or not ids:
            raise HTTPException(400, "Selecciona fotos y una operación válida.")
        with self.guard, self.lock:
            self.comprobar_libre()
            archivos, omitidas, ocupados = [], [], set()
            carpeta_respaldo = self._externa(respaldo) if operacion == "convertir" else None
            for f in self._filas(ids):
                origen = self.ops._ruta(f["ruta"])
                backup = None
                if operacion == "convertir":
                    a = self.auditoria(f)
                    if a["conforme"]:
                        omitidas.append({"id": f["id"], "ruta": f["ruta"], "motivo": "AVIF conforme"})
                        continue
                    if a["errores"]:
                        raise HTTPException(400, f"{f['ruta']}: {', '.join(a['errores'])}. No se puede convertir.")
                    destino = origen.with_suffix(".avif")
                    backup = carpeta_respaldo / f["ruta"]
                    self._componentes(backup.parent)
                    if os.path.lexists(backup):
                        raise HTTPException(409, f"Ya existe el original de respaldo: {backup}")
                else:
                    sugerida = self.sugerencia(f)
                    carpeta = self._destino((destinos or {}).get(str(f["id"]), sugerida))
                    destino = carpeta / origen.name
                    if destino == origen:
                        omitidas.append({"id": f["id"], "ruta": f["ruta"], "motivo": "Ya está en el destino"})
                        continue
                clave = os.path.normcase(str(destino))
                if clave in ocupados or (destino != origen and os.path.lexists(destino)):
                    raise HTTPException(409, f"Nombre en conflicto: {destino}. Elige otro destino; no se sobrescriben fotos.")
                ocupados.add(clave)
                archivos.append({"id": f["id"], "ruta": f["ruta"], "estado": estado_archivo(origen),
                                 "fila": f, "destino": str(destino), "respaldo": str(backup) if backup else None,
                                 "carpetas": {**identidad_carpetas(destino.parent), **(identidad_carpetas(backup.parent) if backup else {})}})
            plan = {"operacion": operacion, "archivos": archivos, "omitidas": omitidas, "respaldo": respaldo,
                    "destinos": destinos or {}, "ids": sorted(set(ids))}
            self.planes = {k: v for k, v in self.planes.items() if v["vence"] > time.monotonic()}
            if len(self.planes) >= 100:
                raise HTTPException(429, "Hay demasiadas revisiones pendientes.")
            token = secrets.token_urlsafe(32)
            frase = f"{operacion.upper()} {len(archivos)} FOTO" + ("S" if len(archivos) != 1 else "")
            self.planes[token] = {"plan": plan, "vence": time.monotonic() + 600, "frase": frase}
            return {"token": token, "frase": frase, "operacion": operacion, "perfil": PERFIL,
                    "archivos": [{**{k: v for k, v in a.items() if k not in ("fila", "estado", "carpetas")},
                                  "carpeta_destino": Path(a["destino"]).parent.relative_to(self.biblioteca).as_posix()} for a in archivos],
                    "omitidas": omitidas, "vigencia_segundos": 600}

    def confirmar(self, token, texto):
        with self.guard, self.lock:
            self.comprobar_libre()
            p = self.planes.get(token)
            if not p or p["vence"] <= time.monotonic():
                raise HTTPException(409, "La revisión venció o ya fue utilizada.")
            if p["frase"] != texto:
                raise HTTPException(400, "Escribe exactamente la frase de confirmación.")
            del self.planes[token]
            plan = p["plan"]
            nuevo = self.preparar(plan["ids"], plan["operacion"], plan["respaldo"], plan["destinos"])
            comprobacion = self.planes.pop(nuevo["token"])["plan"]
            if comprobacion != plan:
                raise HTTPException(409, "Los archivos cambiaron; revisa nuevamente.")
            if not plan["archivos"]:
                raise HTTPException(400, "No hay archivos pendientes para esta operación.")
            if plan["operacion"] == "convertir":
                guardar_json(self.datos / "flujo-config.json", {"respaldo": plan["respaldo"]})
            return self._iniciar(plan["operacion"], plan["archivos"], plan["omitidas"])

    def iniciar(self, operacion, ids=None):
        with self.guard, self.lock:
            self.comprobar_libre()
            if operacion not in ("auditar", "actualizar"):
                raise HTTPException(400, "Trabajo inválido.")
            filas = self._filas(ids if ids is not None else [r[0] for r in self.db.execute("SELECT id FROM fotos")]) if operacion == "auditar" else []
            return self._iniciar(operacion, filas)

    def _iniciar(self, operacion, archivos, omitidas=None):
        j = {"id": secrets.token_hex(12), "operacion": operacion, "estado": "pendiente", "total": len(archivos),
             "procesadas": 0, "completadas": [], "fallidas": [], "omitidas": omitidas or [],
             "pendientes": [a["ruta"] for a in archivos], "creado": datetime.now(timezone.utc).isoformat()}
        self.cancelar_evento.clear()
        self.actual = j
        self._persistir(j)
        self.hilo = threading.Thread(target=self._trabajar, args=(j, archivos), name="photo-manager-trabajo", daemon=False)
        self.hilo.start()
        return copy.deepcopy(j)

    def _persistir(self, j):
        guardar_json(self.datos / "trabajos" / (j["id"] + ".json"), j)

    def _evento(self, j, evento):
        p = self.datos / "trabajos" / (j["id"] + ".jsonl")
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"fecha": datetime.now(timezone.utc).isoformat(), **evento}, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _trabajar(self, j, archivos):
        try:
            with self.guard:
                j["estado"] = "ejecutando"
                self._persistir(j)
                self._evento(j, {"evento": "inicio", "operacion": j["operacion"], "total": j["total"]})
            if j["operacion"] == "actualizar":
                with self.lock:
                    cambios = indice.sincronizar(self.db, self.et, progreso=lambda *_: None)
                with self.guard:
                    j["total"] = cambios
                    j["procesadas"] = cambios
            for a in archivos:
                if self.cancelar_evento.is_set():
                    break
                with self.guard:
                    j["archivo_actual"] = a["ruta"]
                    self._persistir(j)
                try:
                    with self.lock:
                        if j["operacion"] == "auditar":
                            r = self.auditoria(a)
                            resultado = {"ruta": a["ruta"], "tecnica": r, "organizacion": organizacion(a)}
                        else:
                            resultado = self._aplicar_archivo(j, a)
                    with self.guard:
                        j["completadas"].append(resultado)
                        j["procesadas"] += 1
                        j["pendientes"].remove(a["ruta"])
                        self._evento(j, {"evento": "completada", **resultado})
                        self._persistir(j)
                except Exception as exc:
                    with self.guard:
                        error = {"ruta": a["ruta"], "error": str(exc)}
                        if "destino" in a:
                            error.update(destino=a["destino"], respaldo=a["respaldo"],
                                         archivo_modificado=not (self.biblioteca / a["ruta"]).exists() or
                                         ((self.biblioteca / a["ruta"]).exists() and estado_archivo(self.biblioteca / a["ruta"]) != a["estado"]))
                        j["fallidas"].append(error)
                        self._evento(j, {"evento": "error", **error})
                    break
            with self.guard:
                j["estado"] = "error" if j["fallidas"] else ("cancelado" if self.cancelar_evento.is_set() else "completado")
        except Exception as exc:
            with self.guard:
                j["estado"] = "error"
                j["fallidas"].append({"error": str(exc)})
        finally:
            with self.guard:
                j.pop("archivo_actual", None)
                self._persistir(j)

    def _aplicar_archivo(self, j, a):
        origen = self.ops._ruta(a["ruta"])
        fila = self._filas([a["id"]])[0]
        if estado_archivo(origen) != a["estado"] or fila != a["fila"]:
            raise RuntimeError("El archivo o sus metadatos cambiaron desde la revisión.")
        destino = Path(a["destino"])
        for carpeta, identidad in a["carpetas"].items():
            if not Path(carpeta).is_dir() or estado_archivo(Path(carpeta))[:2] != identidad:
                raise RuntimeError("Una carpeta cambió desde la revisión. Revisa nuevamente.")
        self._componentes(destino.parent)
        if destino != origen and os.path.lexists(destino):
            raise RuntimeError("El destino ya existe.")
        tecnico, advertencias = None, []
        if j["operacion"] == "convertir":
            tecnico, advertencias = self._convertir(j, a, origen, destino)
        else:
            destino.parent.mkdir(parents=True, exist_ok=True)
            self._evento(j, {"evento": "antes-mover", **a})
            if os.name != "nt":
                raise RuntimeError("El movimiento sin sobrescritura requiere Windows.")
            origen.rename(destino)
        relativa = destino.relative_to(self.biblioteca).as_posix()
        try:
            self.db.execute("UPDATE fotos SET ruta = ?, carpeta = ? WHERE id = ?", (relativa, destino.parent.relative_to(self.biblioteca).as_posix(), a["id"]))
            indice.releer(self.db, self.et, [relativa])
            self.db.execute("DELETE FROM auditorias WHERE ruta IN (?, ?)", (a["ruta"], relativa))
            if tecnico:
                self.db.execute("INSERT INTO auditorias VALUES (?, ?, ?, ?)",
                                (relativa, json.dumps(estado_archivo(destino)), VERSION, json.dumps(tecnico)))
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            raise RuntimeError(f"Archivo modificado en {destino}; falló el índice. Actualiza el inventario. {exc}") from exc
        return {"id": a["id"], "ruta": a["ruta"], "destino": relativa, "respaldo": a["respaldo"], "advertencias": advertencias}

    def _convertir(self, j, a, origen, destino):
        backup = Path(a["respaldo"])
        self._externa(str(backup.parent))
        self._componentes(backup.parent)
        if os.path.lexists(backup):
            raise RuntimeError("Ya existe el original de respaldo.")
        temporal = origen.parent / (".pm-" + secrets.token_hex(12) + ".avif")
        json_meta = self.datos / ("metadatos-" + secrets.token_hex(12) + ".json")
        try:
            advertencias = []
            notas_originales = maker_notes(origen, self._exiftool())
            esperados = metadatos(origen, self.et)
            ori = (self.et.leer([origen], "-Orientation") or [{}])[0].get("Orientation", 1)
            if ori not in range(1, 9):
                raise RuntimeError("Orientación desconocida; revisa la foto antes de convertir.")
            if ori != 1 and any("Region" in k and k != "XMP-mwg-rs:RegionInfo" for k in esperados):
                raise RuntimeError("Regiones de personas incompatibles con el cambio de orientación.")
            ejecutar(["magick", str(origen), "-auto-orient", "-resize", "3840x3840>", "-depth", "8",
                      "-sampling-factor", "4:2:0", "-quality", "75", str(temporal)])
            escribir_temporal([self._exiftool(), "-overwrite_original", "-TagsFromFile", str(origen), "-all:all", str(temporal)], advertencias)
            escribir_temporal([self._exiftool(), "-overwrite_original", "-IFD0:Orientation#=1", "-XMP-tiff:Orientation#=1", str(temporal)], advertencias)
            tecnico = inspeccionar(temporal, self.et)
            if not tecnico["conforme"]:
                raise RuntimeError("El resultado no cumple el perfil AVIF: " + json.dumps(tecnico))
            esperados = regiones_orientadas(esperados, ori, tecnico["ancho"], tecnico["alto"])
            # Actualizar dimensiones XMP existentes para no conservar el tamaño previo.
            for k in esperados:
                if k.endswith((":ImageWidth", ":ExifImageWidth")):
                    esperados[k] = tecnico["ancho"]
                elif k.endswith((":ImageHeight", ":ExifImageHeight")):
                    esperados[k] = tecnico["alto"]
            guardar_json(json_meta, [{"SourceFile": str(temporal), **esperados}])
            escribir_temporal([self._exiftool(), "-overwrite_original", "-struct", "-json=" + str(json_meta), str(temporal)], advertencias)
            leidos = metadatos(temporal, self.et)
            for k, v in esperados.items():
                if not equivalentes(leidos.get(k), v):
                    raise RuntimeError(f"No se preservó el metadato {k}; el original se conserva.")
            tecnico = inspeccionar(temporal, self.et)
            if not tecnico["conforme"]:
                raise RuntimeError("El AVIF dejó de cumplir el perfil después de escribir los metadatos.")
            if maker_notes(temporal, self._exiftool()) != notas_originales:
                raise RuntimeError("No se conservaron las MakerNotes intactas; el original se conserva.")
            if estado_archivo(origen) != a["estado"]:
                raise RuntimeError("El original cambió durante la conversión.")
            backup.parent.mkdir(parents=True, exist_ok=True)
            self._evento(j, {"evento": "antes-respaldar", **a})
            # 'xb' impide sobrescribir, también entre discos.
            with origen.open("rb") as fuente, backup.open("xb") as salida:
                shutil.copyfileobj(fuente, salida, 1024 * 1024)
                salida.flush()
                os.fsync(salida.fileno())
            if hash_archivo(backup) != hash_archivo(origen):
                raise RuntimeError("No se pudo verificar el respaldo. El original sigue en la biblioteca.")
            if estado_archivo(origen) != a["estado"]:
                raise RuntimeError("El original cambió durante el respaldo.")
            self._evento(j, {"evento": "respaldo-verificado", **a})
            if destino == origen:
                os.replace(temporal, destino)
            else:
                if os.name != "nt":
                    raise RuntimeError("La conversión sin sobrescritura requiere Windows.")
                temporal.rename(destino)
                # El respaldo verificado existe antes de retirar el original de la biblioteca.
                origen.unlink()
            return tecnico, advertencias
        finally:
            temporal.unlink(missing_ok=True)
            json_meta.unlink(missing_ok=True)

    @staticmethod
    def _exiftool():
        from .config import EXIFTOOL
        return EXIFTOOL

    def trabajos(self):
        with self.guard:
            return [json.loads(p.read_text(encoding="utf-8")) for p in
                    sorted((self.datos / "trabajos").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]]

    def cancelar(self, identificador):
        with self.guard:
            if not self.actual or self.actual["id"] != identificador or not self.ocupado():
                raise HTTPException(409, "El trabajo ya no está activo.")
            self.cancelar_evento.set()
            return {"cancelacion_solicitada": True}

    def cerrar(self):
        self.cancelar_evento.set()
        if self.hilo:
            self.hilo.join()
