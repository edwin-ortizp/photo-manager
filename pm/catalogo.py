"""Catálogo local de etiquetas vacías y operaciones de jerarquía."""
import json
from collections import Counter

from .etiquetas import con_padres, hojas


def leer(ruta):
    return set(json.loads(ruta.read_text(encoding="utf-8"))) if ruta.exists() else set()


def guardar(ruta, etiquetas):
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(sorted(etiquetas), ensure_ascii=False), encoding="utf-8")
    temporal.replace(ruta)


def pertenece(etiqueta, rama):
    return etiqueta == rama or etiqueta.startswith(rama + "|")


def renombradas(etiquetas, origen, destino):
    return hojas(destino + t[len(origen):] if pertenece(t, origen) else t for t in etiquetas)


def resumen(fotos, catalogo):
    conteos = Counter()
    for _, etiquetas in fotos:
        conteos.update(con_padres(etiquetas))
    return [{"id": t, "total": conteos[t]} for t in sorted(set(conteos) | set(con_padres(catalogo)))]
