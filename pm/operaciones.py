"""Operaciones sobre archivos con planes efímeros y confirmación explícita."""
import json
import os
import secrets
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException


def enviar_papelera(ruta):
    if os.name != "nt":
        raise RuntimeError("Esta operación requiere la papelera de Windows.")
    try:
        from send2trash import send2trash
    except ImportError as exc:
        raise RuntimeError("Falta Send2Trash. Instala: python -m pip install Send2Trash") from exc
    send2trash(str(ruta))


class Operaciones:
    def __init__(self, biblioteca, datos, db, lock):
        self.biblioteca = Path(biblioteca).resolve()
        self.datos, self.db, self.lock = Path(datos), db, lock
        self.planes = {}

    def _ruta(self, relativa, carpeta=False):
        p = Path(relativa)
        if p.is_absolute() or p.drive or ".." in p.parts or any(x.startswith(".") for x in p.parts):
            raise HTTPException(400, "Ruta fuera de la biblioteca o no permitida.")
        ruta = self.biblioteca / p
        # No atravesar enlaces/junctions: una ruta revisada no debe redirigir archivos.
        actual = self.biblioteca
        for parte in p.parts:
            actual = actual / parte
            if actual.is_symlink() or (hasattr(actual, "is_junction") and actual.is_junction()):
                raise HTTPException(400, "No se permiten enlaces o uniones de carpetas.")
            try:
                if getattr(actual.stat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_HIDDEN:
                    raise HTTPException(400, "No se permiten archivos o carpetas ocultos.")
            except OSError as exc:
                raise HTTPException(409, "La ruta ya no está disponible.") from exc
        try:
            resuelta = ruta.resolve(strict=True)
            if not resuelta.is_relative_to(self.biblioteca):
                raise HTTPException(400, "Ruta fuera de la biblioteca.")
            if not (resuelta.is_dir() if carpeta else resuelta.is_file()):
                raise HTTPException(400, "La ruta no tiene el tipo esperado.")
        except OSError as exc:
            raise HTTPException(409, "Un archivo o carpeta ya no existe o no está disponible.") from exc
        return ruta

    def carpetas(self):
        salida = [{"ruta": "", "absoluta": str(self.biblioteca)}]
        for base, dirs, _ in os.walk(self.biblioteca, followlinks=False):
            validas = []
            for nombre in sorted(dirs):
                relativa = (Path(base) / nombre).relative_to(self.biblioteca).as_posix()
                try:
                    ruta = self._ruta(relativa, carpeta=True)
                except HTTPException:
                    continue
                validas.append(nombre)
                salida.append({"ruta": relativa, "absoluta": str(ruta)})
            dirs[:] = validas
        return salida

    @staticmethod
    def _estado(ruta):
        s = ruta.stat()
        return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]

    def _preparar(self, ids, operacion, destino):
        if operacion not in ("mover", "papelera") or not ids:
            raise HTTPException(400, "Selecciona fotos y una operación válida.")
        if operacion == "papelera" and destino:
            raise HTTPException(400, "Enviar a la papelera no admite un destino.")
        carpeta = self._ruta(destino, carpeta=True) if operacion == "mover" else None
        archivos, ocupados = [], set()
        for foto_id in sorted(set(ids)):
            fila = self.db.execute("SELECT * FROM fotos WHERE id = ?", (foto_id,)).fetchone()
            if fila is None:
                raise HTTPException(409, "Una foto de la selección ya no existe. Revisa nuevamente.")
            ruta = self._ruta(fila["ruta"])
            nueva = carpeta / ruta.name if carpeta else None
            if nueva:
                if nueva.parent == ruta.parent:
                    raise HTTPException(409, "Una foto ya está en la carpeta de destino.")
                clave = os.path.normcase(str(nueva))
                if os.path.lexists(nueva) or clave in ocupados:
                    raise HTTPException(409, f"Nombre en conflicto: {ruta.name}. No se sobrescriben archivos.")
                ocupados.add(clave)
            archivos.append({"id": foto_id, "ruta": fila["ruta"], "origen": str(ruta),
                             "carpeta": str(ruta.parent), "nombre": ruta.name,
                             "destino": str(nueva) if nueva else None,
                             "estado": self._estado(ruta), "fila": dict(fila)})
        return {"operacion": operacion, "destino": destino,
                "destino_absoluto": str(carpeta) if carpeta else None,
                "estado_destino": self._estado(carpeta)[:2] if carpeta else None,
                "archivos": archivos}

    def preview(self, ids, operacion, destino=""):
        with self.lock:
            ahora = time.monotonic()
            self.planes = {k: p for k, p in self.planes.items() if p["vence"] > ahora}
            if len(self.planes) >= 100:
                raise HTTPException(429, "Hay demasiadas revisiones pendientes. Espera a que caduquen.")
            plan = self._preparar(ids, operacion, destino)
            n = len(plan["archivos"])
            fotos = f"{n} FOTO" + ("S" if n != 1 else "")
            frase = f"MOVER {fotos}" if operacion == "mover" else f"ENVIAR {fotos} A LA PAPELERA"
            token = secrets.token_urlsafe(32)
            self.planes[token] = {"plan": plan, "vence": ahora + 600, "frase": frase}
            return {"token": token, "frase": frase, "fotos": n, "operacion": operacion,
                    "biblioteca": str(self.biblioteca), "destino": plan["destino_absoluto"],
                    "archivos": [{k: v for k, v in f.items() if k not in ("estado", "fila")}
                                 for f in plan["archivos"]], "vigencia_segundos": 600}

    def aplicar(self, token, texto):
        with self.lock:
            guardado = self.planes.get(token)
            if not guardado or guardado["vence"] <= time.monotonic():
                self.planes.pop(token, None)
                raise HTTPException(409, "La revisión venció o ya se utilizó. Revisa nuevamente.")
            if texto != guardado["frase"]:
                raise HTTPException(400, "Escribe exactamente la frase de confirmación.")
            # Consumir antes de comprobar/ejecutar: un fallo exige una nueva revisión.
            del self.planes[token]
            plan = guardado["plan"]
            nuevo = self._preparar([f["id"] for f in plan["archivos"]], plan["operacion"], plan["destino"])
            if nuevo != plan:
                raise HTTPException(409, "Los archivos o el destino cambiaron. Revisa nuevamente.")
            self.datos.mkdir(parents=True, exist_ok=True)
            bitacora = self.datos / f"operaciones-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(4)}.jsonl"
            completadas, fallidas = [], []
            def registrar(fh, evento):
                fh.write(json.dumps({"fecha": datetime.now(timezone.utc).isoformat(), **evento}, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            with bitacora.open("x", encoding="utf-8") as fh:
                registrar(fh, {"evento": "inicio", "plan": plan})
                for f in plan["archivos"]:
                    realizada = False
                    try:
                        origen = self._ruta(f["ruta"])
                        if self._estado(origen) != f["estado"]:
                            raise RuntimeError("El archivo cambió después de revisarlo.")
                        if plan["operacion"] == "mover":
                            carpeta = self._ruta(plan["destino"], carpeta=True)
                            if self._estado(carpeta)[:2] != plan["estado_destino"]:
                                raise RuntimeError("La carpeta de destino cambió.")
                            destino = carpeta / f["nombre"]
                            if os.path.lexists(destino):
                                raise RuntimeError("El nombre de destino ya existe.")
                            # Windows rename falla si el destino existe; nunca usar replace.
                            if os.name != "nt":
                                raise RuntimeError("El movimiento seguro requiere Windows.")
                            origen.rename(destino)
                            realizada = True
                            relativa = destino.relative_to(self.biblioteca).as_posix()
                            self.db.execute("UPDATE fotos SET ruta = ?, carpeta = ? WHERE id = ?",
                                            (relativa, carpeta.relative_to(self.biblioteca).as_posix(), f["id"]))
                        else:
                            enviar_papelera(origen)
                            realizada = not os.path.lexists(origen)
                            if not realizada:
                                raise RuntimeError("Windows no confirmó el envío a la papelera.")
                            self.db.execute("DELETE FROM fotos WHERE id = ?", (f["id"],))
                        self.db.commit()
                        completadas.append({"id": f["id"], "ruta": f["ruta"], "destino": f["destino"]})
                        registrar(fh, {"evento": "completada", **completadas[-1]})
                    except Exception as exc:
                        self.db.rollback()
                        realizada = realizada or not os.path.lexists(self.biblioteca / f["ruta"])
                        fallidas.append({"id": f["id"], "ruta": f["ruta"], "error": str(exc), "archivo_modificado": realizada})
                        registrar(fh, {"evento": "error", **fallidas[-1]})
                        break
                procesadas = {f["id"] for f in completadas + fallidas}
                pendientes = [{"id": f["id"], "ruta": f["ruta"]} for f in plan["archivos"] if f["id"] not in procesadas]
                resultado = {"ok": not fallidas, "completadas": completadas, "fallidas": fallidas,
                             "pendientes": pendientes, "bitacora": bitacora.name}
                registrar(fh, {"evento": "fin", **resultado})
            return resultado
