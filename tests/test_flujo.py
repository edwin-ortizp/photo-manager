"""Auditoría y conversiones reales únicamente sobre archivos temporales."""
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

from pm.etiquetas import asignaciones
from pm.exif import ExifTool


class FlujoTest(unittest.TestCase):
    def setUp(self):
        # No importar indice/flujo durante el discovery: las otras pruebas configuran
        # su biblioteca temporal antes de importar el panel.
        global indice, Flujo, guardar_json, hash_archivo, inspeccionar, metadatos, organizacion
        from pm import indice
        from pm.flujo import Flujo, guardar_json, hash_archivo, inspeccionar, metadatos, organizacion
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.bib = self.raiz / "fotos"
        (self.bib / "entrada/sub").mkdir(parents=True)
        self.datos = self.raiz / "datos"
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(indice._ESQUEMA)
        self.addCleanup(self.db.close)
        self.et = ExifTool()
        self.addCleanup(self.et.cerrar)
        parche = patch.object(indice, "BIBLIOTECA", self.bib)
        parche.start()
        self.addCleanup(parche.stop)
        self.flujo = Flujo(self.bib, self.datos, self.db, threading.RLock(), self.et)
        self.addCleanup(self.flujo.cerrar)

    def foto(self, nombre="entrada/sub/niña.jpg", fecha="2020", orientacion=1):
        p = self.bib / nombre
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (80, 40), "#4d6f8a").save(p)
        self.et.escribir(p, *asignaciones(["tipo|foto", "personas|ana", "_ia|v1"]),
                         "-XMP-photoshop:DateCreated=" + fecha, "-EXIF:DateTimeOriginal=2019:01:02 03:04:05",
                         "-EXIF:GPSLatitude=4.5", "-EXIF:GPSLatitudeRef=N", "-EXIF:GPSLongitude=74.2", "-EXIF:GPSLongitudeRef=W",
                         "-XMP-dc:Description=Descripción de prueba", f"-Orientation#={orientacion}")
        indice.releer(self.db, self.et, [nombre])
        return self.db.execute("SELECT id FROM fotos WHERE ruta = ?", (nombre,)).fetchone()[0]

    def confirmar(self, p):
        j = self.flujo.confirmar(p["token"], p["frase"])
        self.flujo.hilo.join(40)
        self.assertFalse(self.flujo.hilo.is_alive(), "Trabajo no terminó")
        return next(x for x in self.flujo.trabajos() if x["id"] == j["id"])

    def test_convertir_real_respaldo_metadatos_y_omitir_conforme(self):
        i = self.foto()
        origen = self.bib / "entrada/sub/niña.jpg"
        antes, digest = metadatos(origen, self.et), hash_archivo(origen)
        p = self.flujo.preparar([i], "convertir", str(self.raiz / "originales"))
        self.assertFalse((self.raiz / "originales").exists(), "Revisar no debe crear carpetas")
        j = self.confirmar(p)
        self.assertEqual(j["estado"], "completado", j)
        destino = origen.with_suffix(".avif")
        self.assertFalse(origen.exists())
        self.assertEqual(hash_archivo(self.raiz / "originales/entrada/sub/niña.jpg"), digest)
        despues = metadatos(destino, self.et)
        for k, v in antes.items():
            self.assertEqual(despues.get(k), v, k)
        self.assertTrue(inspeccionar(destino, self.et)["conforme"])
        self.assertTrue(self.flujo.resultados()[0]["tecnica"]["conforme"])
        self.assertEqual(self.db.execute("SELECT fecha FROM fotos WHERE id=?", (i,)).fetchone()[0], "2020")
        p2 = self.flujo.preparar([i], "convertir", str(self.raiz / "originales"))
        self.assertEqual(len(p2["omitidas"]), 1)
        self.assertFalse(p2["archivos"])

    def test_corregir_avif_grande_y_respaldo_original(self):
        i = self.foto("entrada/a.avif")
        p = self.bib / "entrada/a.avif"
        # Pillow genera 4:4:4; la corrección debe producir 4:2:0 sin perder XMP.
        antes = hash_archivo(p)
        plan = self.flujo.preparar([i], "convertir", str(self.raiz / "originales"))
        j = self.confirmar(plan)
        self.assertEqual(j["estado"], "completado", j)
        self.assertEqual(hash_archivo(self.raiz / "originales/entrada/a.avif"), antes)
        self.assertTrue(inspeccionar(p, self.et)["conforme"])

    def test_makernotes_desconocidas_se_conservan(self):
        from pm.flujo import maker_notes
        p = self.bib / "entrada/notas.jpg"
        exif = Image.Exif()
        exif[271] = "motorola"
        exif[34665] = {37500: b"notas-desconocidas-1234567"}
        Image.new("RGB", (80, 40), "#4d6f8a").save(p, exif=exif)
        indice.releer(self.db, self.et, ["entrada/notas.jpg"])
        i = self.db.execute("SELECT id FROM fotos").fetchone()[0]
        notas = maker_notes(p, self.flujo._exiftool())
        self.assertTrue(notas)
        plan = self.flujo.preparar([i], "convertir", str(self.raiz / "originales"))
        j = self.confirmar(plan)
        self.assertEqual(j["estado"], "completado", j)
        self.assertEqual(maker_notes(p.with_suffix(".avif"), self.flujo._exiftool()), notas)

    def test_no_ignora_otros_errores_y_bloquea_perdida_de_notas(self):
        from pm.flujo import escribir_temporal
        avisos = []
        with patch("pm.flujo.ejecutar", side_effect=[RuntimeError("Error: [minor] Maker notes could not be parsed - temporal.avif"), "OK"]) as run:
            self.assertEqual(escribir_temporal(["exiftool", "temporal.avif"], avisos), "OK")
            self.assertEqual(run.call_args.args[0], ["exiftool", "-m", "temporal.avif"])
            self.assertEqual(len(avisos), 1)
        with patch("pm.flujo.ejecutar", side_effect=RuntimeError("Error: archivo dañado")) as run:
            with self.assertRaisesRegex(RuntimeError, "archivo dañado"):
                escribir_temporal(["exiftool", "temporal.avif"], [])
            self.assertEqual(run.call_count, 1)
        i = self.foto()
        plan = self.flujo.preparar([i], "convertir", str(self.raiz / "originales"))
        with patch("pm.flujo.maker_notes", side_effect=[b"original", b"distinto"]):
            j = self.confirmar(plan)
        self.assertEqual(j["estado"], "error")
        self.assertTrue((self.bib / "entrada/sub/niña.jpg").exists())
        self.assertFalse((self.raiz / "originales").exists())

    def test_orientacion_y_regiones_reales(self):
        i = self.foto(orientacion=6)
        p = self.bib / "entrada/sub/niña.jpg"
        self.et.escribir(p, "-RegionInfo={AppliedToDimensions={W=80,H=40,Unit=pixel},RegionList=[{Area={X=0.25,Y=0.5,W=0.2,H=0.4,Unit=normalized},Name=Ana,Type=Face}]}")
        indice.releer(self.db, self.et, ["entrada/sub/niña.jpg"])
        plan = self.flujo.preparar([i], "convertir", str(self.raiz / "originales"))
        j = self.confirmar(plan)
        self.assertEqual(j["estado"], "completado", j)
        r = metadatos(p.with_suffix(".avif"), self.et)["XMP-mwg-rs:RegionInfo"]
        self.assertEqual(r["AppliedToDimensions"]["W"], 40)
        self.assertEqual(r["RegionList"][0]["Area"]["X"], .5)
        self.assertEqual(r["RegionList"][0]["Area"]["Y"], .25)
        self.assertEqual(r["RegionList"][0]["Area"]["W"], .4)

    def test_auditoria_cache_invalida_y_organizacion(self):
        i = self.foto()
        f = dict(self.db.execute("SELECT * FROM fotos WHERE id=?", (i,)).fetchone())
        a = self.flujo.auditoria(f)
        self.assertIn("sin-avif", a["avisos"])
        self.assertEqual(self.flujo.resultados()[0]["tecnica"], a)
        with patch("pm.flujo.inspeccionar", side_effect=AssertionError("No debe reescanear")):
            self.assertEqual(self.flujo.auditoria(f), a)
        self.et.escribir(self.bib / f["ruta"], "-XMP-dc:Description=Cambió")
        self.assertIsNone(self.flujo.resultados()[0]["tecnica"])
        f.update(ruta="2021/a.jpg", fecha="2020", etiquetas='["_ia|personas|2", "personas|ana"]')
        self.assertIn("ano-incoherente", organizacion(f))
        self.assertIn("personas-pendientes", organizacion(f))
        f.update(etiquetas='["tipo|foto"]', caras="[]")
        self.assertNotIn("personas-pendientes", organizacion(f))

    def test_organizar_fecha_parcial_tipo_y_destino_editable(self):
        i = self.foto(fecha="2020:05")
        plan = self.flujo.preparar([i], "organizar")
        self.assertEqual(plan["archivos"][0]["carpeta_destino"], "2020")
        plan = self.flujo.preparar([i], "organizar", destinos={str(i): "2020/revisadas"})
        j = self.confirmar(plan)
        self.assertEqual(j["estado"], "completado", j)
        fila = dict(self.db.execute("SELECT * FROM fotos WHERE id=?", (i,)).fetchone())
        self.assertEqual(fila["fecha"], "2020-05")
        self.assertEqual(fila["ruta"], "2020/revisadas/niña.jpg")

    def test_conflictos_rutas_vencimiento_y_cambio(self):
        i = self.foto()
        for respaldo in [str(self.bib / "originales"), str(self.raiz), "relativa"]:
            with self.assertRaises(HTTPException):
                self.flujo.preparar([i], "convertir", respaldo)
        for destino in ["../fuera", ".oculta", str(self.raiz)]:
            with self.assertRaises(HTTPException):
                self.flujo.preparar([i], "organizar", destinos={str(i): destino})
        plan = self.flujo.preparar([i], "organizar")
        self.flujo.planes[plan["token"]]["vence"] = 0
        with self.assertRaises(HTTPException):
            self.flujo.confirmar(plan["token"], plan["frase"])
        plan = self.flujo.preparar([i], "organizar")
        self.et.escribir(self.bib / "entrada/sub/niña.jpg", "-Description=Modificada")
        with self.assertRaises(HTTPException):
            self.flujo.confirmar(plan["token"], plan["frase"])
        (self.bib / "entrada/sub/niña.avif").write_bytes(b"no sobrescribir")
        with self.assertRaises(HTTPException):
            self.flujo.preparar([i], "convertir", str(self.raiz / "originales"))

    def test_animacion_e_ilegible_bloqueadas(self):
        p = self.bib / "entrada/animada.gif"
        Image.new("RGB", (30, 30), "red").save(p, save_all=True, append_images=[Image.new("RGB", (30, 30), "blue")], duration=100, loop=0)
        indice.releer(self.db, self.et, ["entrada/animada.gif"])
        i = self.db.execute("SELECT id FROM fotos").fetchone()[0]
        with self.assertRaises(HTTPException):
            self.flujo.preparar([i], "convertir", str(self.raiz / "originales"))
        p.write_bytes(b"imagen truncada")
        f = dict(self.db.execute("SELECT * FROM fotos").fetchone())
        self.assertIn("ilegible", self.flujo.auditoria(f)["errores"])

    def test_fallo_respaldo_no_retira_original_y_detiene_lote(self):
        ids = [self.foto(), self.foto("entrada/segunda.jpg")]
        plan = self.flujo.preparar(ids, "convertir", str(self.raiz / "originales"))
        with patch("pm.flujo.shutil.copyfileobj", side_effect=OSError("No hay espacio")):
            j = self.confirmar(plan)
        self.assertEqual(j["estado"], "error")
        self.assertEqual(len(j["fallidas"]), 1)
        self.assertEqual(len(j["pendientes"]), 2)
        self.assertTrue((self.bib / "entrada/sub/niña.jpg").exists())
        self.assertFalse((self.bib / "entrada/sub/niña.avif").exists())

    def test_cancelacion_entre_archivos_y_trabajo_interrumpido(self):
        ids = [self.foto(), self.foto("entrada/segunda.jpg")]
        plan = self.flujo.preparar(ids, "organizar")
        real = self.flujo._aplicar_archivo
        def cancelar(j, a):
            r = real(j, a)
            self.flujo.cancelar_evento.set()
            return r
        with patch.object(self.flujo, "_aplicar_archivo", side_effect=cancelar):
            j = self.confirmar(plan)
        self.assertEqual(j["estado"], "cancelado")
        self.assertEqual(len(j["completadas"]), 1)
        self.assertEqual(len(j["pendientes"]), 1)
        guardar_json(self.datos / "trabajos/prueba.json", {"estado": "ejecutando"})
        Flujo(self.bib, self.datos, self.db, threading.RLock(), self.et)
        self.assertEqual(json.loads((self.datos / "trabajos/prueba.json").read_text())["estado"], "interrumpido")

    def test_dimensiones_y_dependencia_ausente(self):
        i = self.foto("entrada/grande.png")
        p = self.bib / "entrada/grande.png"
        Image.new("RGB", (4200, 20), "#abc123").save(p)
        indice.releer(self.db, self.et, ["entrada/grande.png"])
        plan = self.flujo.preparar([i], "convertir", str(self.raiz / "originales"))
        j = self.confirmar(plan)
        self.assertEqual(j["estado"], "completado", j)
        self.assertEqual(inspeccionar(p.with_suffix(".avif"), self.et)["ancho"], 3840)
        with patch("pm.flujo.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "Falta ImageMagick"):
                inspeccionar(p.with_suffix(".avif"), self.et)

    def test_region_incompatible_y_respaldo_existente(self):
        i = self.foto()
        p = self.bib / "entrada/sub/niña.jpg"
        self.et.escribir(p, "-RegionInfo={AppliedToDimensions={W=80,H=40,Unit=pixel},RegionList=[{Area={X=20,Y=20,W=10,H=10,Unit=pixel},Name=Ana,Type=Face}]}")
        indice.releer(self.db, self.et, ["entrada/sub/niña.jpg"])
        plan = self.flujo.preparar([i], "convertir", str(self.raiz / "originales"))
        j = self.confirmar(plan)
        self.assertEqual(j["estado"], "error")
        self.assertTrue(p.exists())
        self.assertFalse(p.with_suffix(".avif").exists())
        backup = self.raiz / "originales/entrada/sub/niña.jpg"
        backup.parent.mkdir(parents=True)
        backup.write_bytes(b"no sobrescribir")
        with self.assertRaises(HTTPException):
            self.flujo.preparar([i], "convertir", str(self.raiz / "originales"))

    def test_nombres_repetidos_y_carpeta_reemplazada(self):
        ids = [self.foto("entrada/uno/repetida.jpg"), self.foto("entrada/dos/repetida.jpg")]
        with self.assertRaises(HTTPException):
            self.flujo.preparar(ids, "organizar")
        carpeta = self.bib / "2020"
        carpeta.mkdir()
        plan = self.flujo.preparar([ids[0]], "organizar")
        carpeta.rename(self.bib / "2020-anterior")
        carpeta.mkdir()
        with self.assertRaises(HTTPException):
            self.flujo.confirmar(plan["token"], plan["frase"])

    def test_cancelar_consulta_y_bloqueo_de_otro_trabajo(self):
        i = self.foto()
        entrado, liberar = threading.Event(), threading.Event()
        real = self.flujo.auditoria
        def lento(f):
            entrado.set()
            liberar.wait(5)
            return real(f)
        with patch.object(self.flujo, "auditoria", side_effect=lento):
            j = self.flujo.iniciar("auditar", [i])
            self.assertTrue(entrado.wait(5))
            self.assertEqual(self.flujo.trabajos()[0]["estado"], "ejecutando")
            with self.assertRaises(HTTPException):
                self.flujo.comprobar_libre()
            self.assertTrue(self.flujo.cancelar(j["id"])["cancelacion_solicitada"])
            liberar.set()
            self.flujo.hilo.join(10)
        self.assertEqual(self.flujo.trabajos()[0]["estado"], "cancelado")


if __name__ == "__main__":
    unittest.main()
