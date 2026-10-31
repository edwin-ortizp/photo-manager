"""Rutas y constantes del gestor de fotos."""
from pathlib import Path

# Biblioteca (sincronizada con Syncthing). Las fotos viven aqui; este proyecto no.
BIBLIOTECA = Path(r"C:\Users\edwin\Sync\fotos")
ENTRADA = BIBLIOTECA / "entrada"          # llegan las fotos nuevas convertidas
SIN_FECHA = BIBLIOTECA / "sin-fecha"
# Carpetas por tipo (fuera de la linea de tiempo por anio)
CARPETAS_TIPO = {
    "captura": BIBLIOTECA / "capturas",
    "meme": BIBLIOTECA / "memes",
    "documento": BIBLIOTECA / "documentos",
}

EXTENSIONES = {".avif", ".gif", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}

PROYECTO = Path(__file__).resolve().parent.parent
DATOS = PROYECTO / "datos"                 # indice, miniaturas y bitacoras (no se sincroniza)
INDICE = DATOS / "indice.db"
MINIATURAS = DATOS / "miniaturas"

EXIFTOOL = r"C:\Users\edwin\AppData\Local\Programs\ExifTool\ExifTool.exe"
