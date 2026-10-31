"""Reorganiza la biblioteca: una carpeta por anio de toma, nombres por fecha.

    2025/2025-06-28-154951.avif
    sin-fecha/<nombre-original-en-kebab>.avif

La fecha sale de DateTimeOriginal; si no hay, del nombre del archivo
(20250628_154951, IMG20220502085527, WP_20150502_19_31_10, FB_IMG_<epoch ms>).
Cuando la fecha viene del nombre se escribe en el EXIF para no perderla.
Cada movimiento queda en una bitacora CSV que permite deshacer.
"""
import csv
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .config import BIBLIOTECA, CARPETAS_TIPO, DATOS, ENTRADA, EXTENSIONES, SIN_FECHA
from .exif import ExifTool

_RE_FECHA = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_ ]?(\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)"
)
_RE_SOLO_DIA = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_]?(\d{2})[-_]?(\d{2})(?!\d)")
_RE_EPOCH_MS = re.compile(r"(?<!\d)(1[3-9]\d{11})(?!\d)")  # 2011..2033 en milisegundos
_FMT_EXIF = "%Y:%m:%d %H:%M:%S"


def kebab(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-") or "foto"


def _valida(f: datetime) -> bool:
    return datetime(1990, 1, 1) <= f <= datetime.now()


def fecha_de_nombre(nombre: str) -> datetime | None:
    if m := _RE_FECHA.search(nombre):
        try:
            f = datetime(*map(int, m.groups()))
            if _valida(f):
                return f
        except ValueError:
            pass
    if m := _RE_EPOCH_MS.search(nombre):
        f = datetime.fromtimestamp(int(m.group(1)) / 1000)
        if _valida(f):
            return f
    if m := _RE_SOLO_DIA.search(nombre):
        try:
            f = datetime(*map(int, m.groups()), 12, 0, 0)
            if _valida(f):
                return f
        except ValueError:
            pass
    return None


def fecha_exif(meta: dict) -> datetime | None:
    for campo in ("DateTimeOriginal", "CreateDate"):
        valor = str(meta.get(campo) or "")[:19]
        try:
            f = datetime.strptime(valor, _FMT_EXIF)
            if _valida(f):
                return f
        except ValueError:
            continue
    return None


def destino_para(archivo: Path, fecha: datetime | None) -> Path:
    ext = archivo.suffix.lower()
    if re.search(r"screenshot|captura", archivo.name, re.I):
        nombre = f"{fecha:%Y-%m-%d-%H%M%S}" if fecha else kebab(archivo.stem)
        return CARPETAS_TIPO["captura"] / f"{nombre}{ext}"
    if fecha:
        return BIBLIOTECA / str(fecha.year) / f"{fecha:%Y-%m-%d-%H%M%S}{ext}"
    return SIN_FECHA / f"{kebab(archivo.stem)}{ext}"


def _libre(destino: Path, ocupados: set[Path]) -> Path:
    candidato, n = destino, 2
    while candidato in ocupados or (candidato.exists()):
        candidato = destino.with_name(f"{destino.stem}-{n}{destino.suffix}")
        n += 1
    return candidato


def _archivos_a_organizar() -> list[Path]:
    """Todo lo que no esta ya en su lugar: raiz, ready/, entrada/, y archivos mal nombrados."""
    fijas = {SIN_FECHA, *CARPETAS_TIPO.values()}
    salida = []
    for p in BIBLIOTECA.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in EXTENSIONES:
            continue
        if any(parte.startswith(".") for parte in p.relative_to(BIBLIOTECA).parts):
            continue  # .stfolder, .dtrash, etc.
        if p.parent in fijas:
            continue
        if (p.parent in fijas or re.fullmatch(r"\d{4}", p.parent.name) and p.parent.parent == BIBLIOTECA) and re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{6}(-\d+)?", p.stem):
            continue  # ya organizada
        salida.append(p)
    return sorted(salida)


def organizar(simular: bool = True) -> list[dict]:
    archivos = _archivos_a_organizar()
    plan, ocupados = [], set()
    with ExifTool() as et:
        metas = {}
        for i in range(0, len(archivos), 500):
            for m in et.leer(archivos[i:i + 500], "-DateTimeOriginal", "-CreateDate"):
                metas[Path(m["SourceFile"]).resolve()] = m
        for a in archivos:
            meta = metas.get(a.resolve(), {})
            fecha, origen = fecha_exif(meta), "exif"
            if not fecha:
                fecha, origen = fecha_de_nombre(a.name), "nombre"
            if not fecha:
                origen = "ninguna"
            destino = _libre(destino_para(a, fecha), ocupados)
            ocupados.add(destino)
            plan.append({"origen": str(a), "destino": str(destino), "fecha": fecha.isoformat() if fecha else "",
                         "fuente_fecha": origen})

        if simular:
            return plan

        DATOS.mkdir(parents=True, exist_ok=True)
        bitacora = DATOS / f"movimientos-{datetime.now():%Y%m%d-%H%M%S}.csv"
        with bitacora.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(plan[0]) if plan else ["origen"])
            w.writeheader()
            for p in plan:
                origen, destino = Path(p["origen"]), Path(p["destino"])
                if p["fuente_fecha"] == "nombre" and origen.suffix.lower() != ".gif":
                    f = datetime.fromisoformat(p["fecha"]).strftime(_FMT_EXIF)
                    et.escribir(origen, f"-EXIF:DateTimeOriginal={f}", f"-EXIF:CreateDate={f}")
                destino.parent.mkdir(parents=True, exist_ok=True)
                origen.rename(destino)
                w.writerow(p)
        print(f"Bitacora: {bitacora}")
    # Limpia carpetas que quedaron vacias (ready/, etc.)
    for d in sorted(BIBLIOTECA.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()) and d != ENTRADA and not d.name.startswith("."):
            d.rmdir()
    ENTRADA.mkdir(exist_ok=True)
    return plan


def deshacer(bitacora: Path):
    with bitacora.open(encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    for f in reversed(filas):
        d, o = Path(f["destino"]), Path(f["origen"])
        if d.exists() and not o.exists():
            o.parent.mkdir(parents=True, exist_ok=True)
            d.rename(o)

