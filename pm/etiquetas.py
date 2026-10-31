"""Etiquetas jerarquicas en kebab-case, escritas igual que digiKam/Lightroom.

Una etiqueta es "rama|sub|hoja". Las ramas que empiezan con "_" (_sugerencias,
_ia) son internas: van en HierarchicalSubject pero no en dc:Subject, que es lo
que muestran las galerias.
"""
import re
import unicodedata

CAMPOS_LISTA = ("XMP-lr:HierarchicalSubject", "XMP-mediapro:CatalogSets",
                "XMP-digiKam:TagsList", "XMP-microsoft:LastKeywordXMP", "XMP-dc:Subject")
SEP = ";;"


def kebab(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9_]+", "-", texto.lower()).strip("-")


def normalizar(etiqueta: str) -> str:
    """'Personas / Camila Mateus' -> 'personas|camila-mateus'."""
    partes = [kebab(p) for p in re.split(r"[|/]", etiqueta)]
    return "|".join(p for p in partes if p)


def con_padres(etiquetas) -> list[str]:
    salida = set()
    for e in etiquetas:
        partes = e.split("|")
        for i in range(1, len(partes) + 1):
            salida.add("|".join(partes[:i]))
    return sorted(salida)


def hojas(etiquetas) -> list[str]:
    """Solo las hojas, sin padres redundantes: ['personas|yo', 'personas'] -> ['personas|yo']."""
    lista = set(etiquetas)
    return sorted(e for e in lista if not any(o.startswith(e + "|") for o in lista))


def visibles(etiquetas) -> list[str]:
    return [e for e in etiquetas if not e.startswith("_")]


def asignaciones(etiquetas) -> list[str]:
    """Argumentos de exiftool para dejar exactamente esta lista en todos los campos."""
    todas = con_padres(etiquetas)
    jer = SEP.join(todas)
    bar = SEP.join(t.replace("|", "/") for t in todas)
    dc = SEP.join(sorted({t.split("|")[-1] for t in visibles(todas)}))
    return ["-sep", SEP,
            f"-XMP-lr:HierarchicalSubject={jer}", f"-XMP-mediapro:CatalogSets={jer}",
            f"-XMP-digiKam:TagsList={bar}", f"-XMP-microsoft:LastKeywordXMP={bar}",
            f"-XMP-dc:Subject={dc}"]
