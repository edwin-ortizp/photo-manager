"""Clasificacion con Claude Haiku a traves de Claude Code (skill clasificar-fotos).

Flujo por lote:
  1. Copia reducida (JPEG 1024 px) de cada foto en datos/para-ia/.
  2. `claude -p "/clasificar-fotos <lote.json>" --model haiku` devuelve un arreglo JSON.
  3. Se escriben etiquetas (tipo|*, escena|*, _ia|*), la descripcion, y las
     capturas/memes/documentos se mueven a su carpeta.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from . import indice
from .config import BIBLIOTECA, CARPETAS_TIPO, DATOS, PROYECTO
from .etiquetas import asignaciones, hojas
from .exif import ExifTool

MODELO = "claude-haiku-5-5"
VERSION = "v1"               # se guarda como _ia|v1; subirla permite reclasificar
PARA_IA = DATOS / "para-ia"
TIPOS = {"foto", "captura", "meme", "documento", "otro"}
ESCENAS = {"retrato", "selfie", "grupo", "familia", "celebracion", "comida", "mascotas", "animales",
           "naturaleza", "paisaje", "playa", "ciudad", "viaje", "vehiculos", "deporte", "hogar",
           "trabajo", "estudio", "compras", "evento", "arte", "noche"}


def pendientes(db, limite: int, carpeta: str = "") -> list[dict]:
    filas = db.execute("SELECT * FROM fotos ORDER BY fecha DESC").fetchall()
    salida = []
    for f in filas:
        etqs = json.loads(f["etiquetas"])
        if any(e.startswith("_ia|") for e in etqs) or (carpeta and f["carpeta"] != carpeta):
            continue
        salida.append({**dict(f), "etiquetas": etqs})
        if len(salida) >= limite:
            break
    return salida


def preparar_lote(fotos: list[dict], numero: int) -> Path:
    PARA_IA.mkdir(parents=True, exist_ok=True)
    lote = []
    for f in fotos:
        jpg = PARA_IA / f"{f['id']}.jpg"
        if not jpg.exists():
            with Image.open(BIBLIOTECA / f["ruta"]) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((1024, 1024))
                im.convert("RGB").save(jpg, "JPEG", quality=82)
        lote.append({
            "id": f["id"], "imagen": jpg.as_posix(), "fecha": f["fecha"], "camara": f["camara"] or "",
            "sugerencias": [e.split("|")[-1] for e in f["etiquetas"] if e.startswith("_sugerencias|")],
            "personas_conocidas": [e.split("|")[-1] for e in f["etiquetas"] if e.startswith("personas|")],
        })
    ruta = PARA_IA / f"lote-{numero:04d}.json"
    ruta.write_text(json.dumps(lote, ensure_ascii=False, indent=1), encoding="utf-8")
    return ruta


def invocar_claude(lote: Path) -> list[dict]:
    rel = lote.relative_to(PROYECTO).as_posix()
    claude = shutil.which("claude") or "claude"
    proc = subprocess.run(
        [claude, "-p", f"/clasificar-fotos {rel}", "--model", MODELO,
         "--allowedTools", "Read", "--output-format", "json"],
        cwd=PROYECTO, capture_output=True, text=True, encoding="utf-8", timeout=900,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    texto = json.loads(proc.stdout).get("result", "")
    (lote.with_suffix(".respuesta.txt")).write_text(texto, encoding="utf-8")
    m = re.search(r"\[.*\]", texto, re.S)
    if not m:
        raise RuntimeError(f"Respuesta sin JSON: {texto[:300]}")
    return json.loads(m.group(0))


def aplicar(db, et: ExifTool, resultados: list[dict]) -> dict:
    """Escribe la clasificacion en cada foto y mueve las que no son fotos."""
    resumen = {"ok": 0, "error": 0, "movidas": 0}
    for r in resultados:
        fila = db.execute("SELECT ruta FROM fotos WHERE id = ?", (r.get("id"),)).fetchone()
        if not fila or r.get("error") or r.get("tipo") not in TIPOS:
            resumen["error"] += 1
            continue
        ruta = BIBLIOTECA / fila["ruta"]
        meta = et.leer([ruta], "-XMP-lr:HierarchicalSubject")[0]
        actuales = meta.get("HierarchicalSubject") or []
        actuales = set(hojas(actuales if isinstance(actuales, list) else [actuales]))

        confirmadas = set(r.get("sugerencias_confirmadas") or []) & ESCENAS
        escenas = (set(r.get("escenas") or []) & ESCENAS) | confirmadas
        nuevas = {t for t in actuales if not t.startswith(("_sugerencias|", "tipo|", "_ia|"))}
        nuevas |= {f"tipo|{r['tipo']}", f"_ia|{VERSION}", f"_ia|personas|{int(r.get('personas') or 0)}"}
        if r["tipo"] == "foto":
            nuevas |= {f"escena|{e}" for e in escenas}

        args = asignaciones(hojas(nuevas))
        if r.get("descripcion"):
            args.append(f"-XMP-dc:Description={r['descripcion']}")
        et.escribir(ruta, *args)

        destino = ruta
        carpeta_tipo = CARPETAS_TIPO.get(r["tipo"])
        if carpeta_tipo and ruta.parent != carpeta_tipo:
            carpeta_tipo.mkdir(exist_ok=True)
            destino = carpeta_tipo / ruta.name
            n = 2
            while destino.exists():
                destino = carpeta_tipo / f"{ruta.stem}-{n}{ruta.suffix}"
                n += 1
            ruta.rename(destino)
            db.execute("DELETE FROM fotos WHERE id = ?", (r["id"],))
            resumen["movidas"] += 1
        indice.releer(db, et, [destino.relative_to(BIBLIOTECA).as_posix()])
        (PARA_IA / f"{r['id']}.jpg").unlink(missing_ok=True)
        resumen["ok"] += 1
    return resumen
