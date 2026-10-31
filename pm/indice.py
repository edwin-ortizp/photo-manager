"""Indice SQLite de la biblioteca y miniaturas en cache.

Las fotos son la fuente de verdad: el indice solo acelera las consultas y se
reconstruye leyendo los archivos que cambiaron (por tamanio + fecha de modificacion).
"""
import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

from PIL import Image, ImageOps

from .config import BIBLIOTECA, DATOS, EXTENSIONES, INDICE, MINIATURAS
from .etiquetas import hojas
from .exif import ExifTool
from .fechas import efectiva

LADO_MINIATURA = 360

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS fotos (
    id        INTEGER PRIMARY KEY,
    ruta      TEXT UNIQUE NOT NULL,   -- relativa a BIBLIOTECA, con '/'
    carpeta   TEXT NOT NULL,
    fecha     TEXT,                   -- ISO, de DateTimeOriginal
    ancho     INTEGER, alto INTEGER,
    lat       REAL, lon REAL,
    camara    TEXT,
    etiquetas TEXT NOT NULL DEFAULT '[]',  -- hojas jerarquicas (json)
    caras     TEXT NOT NULL DEFAULT '[]',  -- nombres de regiones de cara (json)
    descripcion TEXT,
    firma     TEXT NOT NULL           -- tamanio:mtime para detectar cambios
);
CREATE INDEX IF NOT EXISTS ix_fotos_carpeta ON fotos(carpeta);
CREATE INDEX IF NOT EXISTS ix_fotos_fecha ON fotos(fecha);
"""

_CAMPOS_EXIF = ["-DateTimeOriginal", "-XMP-photoshop:DateCreated", "-ImageWidth", "-ImageHeight", "-GPSLatitude", "-GPSLongitude",
                "-Model", "-XMP-lr:HierarchicalSubject", "-XMP-mwg-rs:RegionName", "-XMP-dc:Description"]


def conectar() -> sqlite3.Connection:
    DATOS.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(INDICE, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(_ESQUEMA)
    return db


def _rel(p: Path) -> str:
    return p.relative_to(BIBLIOTECA).as_posix()


def _firma(p: Path) -> str:
    st = p.stat()
    return f"{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}"


def _lista(valor) -> list:
    if valor in (None, ""):
        return []
    return valor if isinstance(valor, list) else [valor]


def _fila(meta: dict) -> dict:
    fecha = efectiva(meta)
    return {
        "fecha": fecha,
        "ancho": meta.get("ImageWidth"), "alto": meta.get("ImageHeight"),
        "lat": meta.get("GPSLatitude"), "lon": meta.get("GPSLongitude"),
        "camara": meta.get("Model") or None,
        "etiquetas": json.dumps(hojas([str(e) for e in _lista(meta.get("HierarchicalSubject"))])),
        "caras": json.dumps([str(c) for c in _lista(meta.get("RegionName"))]),
        "descripcion": meta.get("Description") or None,
    }


def archivos_biblioteca() -> list[Path]:
    return sorted(p for p in BIBLIOTECA.rglob("*")
                  if p.is_file() and p.suffix.lower() in EXTENSIONES
                  and not any(x.startswith(".") for x in p.relative_to(BIBLIOTECA).parts))


def sincronizar(db: sqlite3.Connection, et: ExifTool, progreso=print) -> int:
    """Actualiza el indice con los archivos nuevos, cambiados o borrados."""
    actuales = {_rel(p): p for p in archivos_biblioteca()}
    conocidas = {r["ruta"]: r["firma"] for r in db.execute("SELECT ruta, firma FROM fotos")}
    borradas = set(conocidas) - set(actuales)
    db.executemany("DELETE FROM fotos WHERE ruta = ?", [(r,) for r in borradas])

    version = db.execute("PRAGMA user_version").fetchone()[0]
    pendientes = [p for r, p in actuales.items() if version < 1 or conocidas.get(r) != _firma(p)]
    for i in range(0, len(pendientes), 300):
        lote = pendientes[i:i + 300]
        for meta in et.leer(lote, *_CAMPOS_EXIF):
            p = Path(meta["SourceFile"])
            guardar(db, p, meta)
        db.commit()
        progreso(f"Indexadas {min(i + 300, len(pendientes))}/{len(pendientes)}")
    db.execute("PRAGMA user_version = 1")
    db.commit()
    return len(pendientes) + len(borradas)


def guardar(db: sqlite3.Connection, p: Path, meta: dict):
    fila = _fila(meta)
    fila.update(ruta=_rel(p), carpeta=p.parent.relative_to(BIBLIOTECA).as_posix(), firma=_firma(p))
    columnas = ", ".join(fila)
    db.execute(
        f"INSERT INTO fotos ({columnas}) VALUES ({', '.join('?' * len(fila))}) "
        f"ON CONFLICT(ruta) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in fila),
        list(fila.values()),
    )


def releer(db: sqlite3.Connection, et: ExifTool, rutas: list[str]):
    """Vuelve a indexar archivos concretos tras escribirles metadatos."""
    for meta in et.leer([BIBLIOTECA / r for r in rutas], *_CAMPOS_EXIF):
        guardar(db, Path(meta["SourceFile"]), meta)
    db.commit()


_generando = threading.Semaphore(4)          # decodificar AVIF 4K es caro: maximo 4 a la vez
_locks: dict[str, threading.Lock] = {}
_locks_guardia = threading.Lock()


def miniatura(ruta: str, lado: int = LADO_MINIATURA) -> Path:
    """Devuelve (y genera si falta) la miniatura WebP de una foto.

    La clave incluye ruta y estado preciso del archivo para invalidar también
    conversiones que conserven el nombre o la fecha de modificación.
    """
    origen = BIBLIOTECA / ruta
    clave = hashlib.sha1(f"{ruta}:{_firma(origen)}:{lado}".encode()).hexdigest()
    destino = MINIATURAS / clave[:2] / f"{clave}.webp"
    if destino.exists():
        return destino
    with _locks_guardia:
        lock = _locks.setdefault(clave, threading.Lock())
    with lock, _generando:
        if not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            temporal = destino.with_suffix(f".{threading.get_ident()}.tmp")
            with Image.open(origen) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((lado, lado))
                im.convert("RGB").save(temporal, "WEBP", quality=78 if lado <= 400 else 85)
            os.replace(temporal, destino)
    with _locks_guardia:
        _locks.pop(clave, None)
    return destino
