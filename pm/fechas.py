"""Fechas con precisión explícita; nunca se completan componentes desconocidos."""
import re
from datetime import datetime


def normalizar(valor):
    texto = str(valor or "").strip()
    texto = texto[:10].replace(":", "-") + texto[10:].replace(" ", "T", 1)
    formatos = {4: "%Y", 7: "%Y-%m", 10: "%Y-%m-%d", 16: "%Y-%m-%dT%H:%M", 19: "%Y-%m-%dT%H:%M:%S"}
    if len(texto) not in formatos or not re.fullmatch(r"[0-9T:\-]+", texto):
        raise ValueError("Fecha inválida. Usa año, año-mes, año-mes-día o fecha con hora.")
    datetime.strptime(texto, formatos[len(texto)])
    return texto + ":00" if len(texto) == 16 else texto


def precision(fecha):
    return {4: "ano", 7: "mes", 10: "dia", 16: "hora", 19: "hora"}.get(len(fecha or ""))


def efectiva(meta):
    for clave in ("DateCreated", "DateTimeOriginal"):
        valor = meta.get(clave)
        if valor is None:
            continue
        try:
            return normalizar(valor)
        except ValueError:
            # EXIF puede incluir zona horaria/subsegundos; conservar su hora local.
            if len(str(valor)) > 19:
                try:
                    return normalizar(str(valor)[:19])
                except ValueError:
                    pass
    return None
