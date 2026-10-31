"""Integración aislada: SQLite, fotos y XMP reales en un directorio temporal."""
import importlib
import tempfile
import unittest
import sqlite3
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from pm import config
from pm.etiquetas import asignaciones


class EtiquetasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        raiz = Path(cls.tmp.name)
        config.BIBLIOTECA = raiz / "fotos"
        config.DATOS = raiz / "datos"
        config.INDICE = config.DATOS / "indice.db"
        config.MINIATURAS = config.DATOS / "miniaturas"
        config.BIBLIOTECA.mkdir()
        cls.panel = importlib.import_module("pm.panel")
        cls.client = TestClient(cls.panel.app)

    @classmethod
    def tearDownClass(cls):
        cls.panel.et.cerrar()
        cls.panel.db.close()
        cls.tmp.cleanup()

    def setUp(self):
        p = self.panel
        p.db.execute("DELETE FROM fotos")
        p.db.commit()
        p.CATALOGO.unlink(missing_ok=True)
        for nombre, etiquetas in [("a.jpg", ["personas|ana", "personas|luis", "escena|noche"]),
                                   ("b.jpg", ["personas|ana", "_ia|v1"])]:
            ruta = config.BIBLIOTECA / nombre
            Image.new("RGB", (20, 20)).save(ruta)
            p.et.escribir(ruta, *asignaciones(etiquetas))
        p.indice.releer(p.db, p.et, ["a.jpg", "b.jpg"])

    def test_grupos_sin_duplicar_y_filtro(self):
        etiquetas = {t["id"]: t["total"] for t in self.client.get("/api/resumen").json()["etiquetas"]}
        self.assertEqual(etiquetas["personas"], 2)
        self.assertEqual(etiquetas["personas|luis"], 1)
        self.assertEqual(self.client.get("/api/fotos?etiqueta=personas").json()["total"], 2)

    def test_bandejas_pendientes_por_rama(self):
        foto_id = self.panel.db.execute("SELECT id FROM fotos WHERE ruta='a.jpg'").fetchone()[0]
        for bandeja, rama in [("sin-estilo", "estilo"), ("sin-momento", "momento"),
                              ("sin-tema", "tema"), ("sin-persona", "personas")]:
            with self.subTest(bandeja=bandeja):
                antes = self.client.get("/api/fotos", params={"bandeja": bandeja}).json()["total"]
                etiqueta = rama + "|prueba|detalle"
                cambio = self.client.post("/api/etiquetar", json={"ids": [foto_id], "agregar": [etiqueta]})
                self.assertTrue(cambio.json()["ok"], cambio.text)
                r = self.client.get("/api/fotos", params={"bandeja": bandeja}).json()
                self.assertNotIn(foto_id, [f["id"] for f in r["fotos"]])
                self.assertEqual(r["total"], antes - (0 if rama == "personas" else 1))
                resumen = {b["id"]: b["total"] for b in self.client.get("/api/resumen").json()["bandejas"]}
                self.assertEqual(resumen[bandeja], r["total"])
                self.assertNotIn("sin-mascota", resumen)
                self.assertNotIn("sin-vehiculo", resumen)
                self.assertEqual(self.client.get("/api/fotos", params={"bandeja": bandeja, "q": "a.jpg"}).json()["total"], 0)
                cambio = self.client.post("/api/etiquetar", json={"ids": [foto_id], "quitar": [rama]})
                self.assertTrue(cambio.json()["ok"], cambio.text)
                r = self.client.get("/api/fotos", params={"bandeja": bandeja, "q": "a.jpg"}).json()
                self.assertEqual(r["total"], 1)
                # La ausencia de etiquetas personales no implica personas detectadas sin nombre.
                if rama == "personas":
                    self.assertEqual(self.client.get("/api/fotos?bandeja=personas-sin-nombre").json()["total"], 0)

    def test_crear_vacia_duplicada_y_normalizada(self):
        r = self.client.post("/api/etiquetas/crear", json={"nombre": "Lugar / Bogotá"})
        self.assertEqual(r.json()["nombre"], "lugar|bogota")
        self.assertIn({"id": "lugar|bogota", "total": 0}, self.client.get("/api/resumen").json()["etiquetas"])
        self.assertEqual(self.client.post("/api/etiquetas/crear", json={"nombre": "lugar|bogota"}).status_code, 409)
        self.assertEqual(self.client.post("/api/etiquetas/crear", json={"nombre": "///"}).status_code, 400)

    def test_renombrar_rama_con_xmp_real(self):
        cambio = {"origen": "personas", "destino": "gente"}
        self.assertEqual(self.client.post("/api/etiquetas/renombrar", json=cambio).status_code, 409)
        plan = self.client.post("/api/etiquetas/renombrar/preview", json=cambio).json()
        self.assertEqual(plan["fotos"], 2)
        r = self.client.post("/api/etiquetas/renombrar", json=plan)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["actualizadas"], 2)
        fotos = self.client.get("/api/fotos?etiqueta=gente").json()["fotos"]
        self.assertEqual(len(fotos), 2)
        self.assertTrue(all("gente|ana" in f["etiquetas"] for f in fotos))
        meta = self.panel.et.leer([config.BIBLIOTECA / "a.jpg"], "-XMP:All")[0]
        self.assertIn("gente|luis", meta["HierarchicalSubject"])
        self.assertIn("escena|noche", meta["HierarchicalSubject"])
        self.assertIn("gente/luis", meta["TagsList"])

    def test_colision_y_plan_obsoleto(self):
        r = self.client.post("/api/etiquetas/renombrar/preview", json={"origen": "personas|ana", "destino": "personas|luis"})
        self.assertEqual(r.status_code, 409)
        plan = self.client.post("/api/etiquetas/renombrar/preview", json={"origen": "personas", "destino": "gente"}).json()
        self.client.post("/api/etiquetas/crear", json={"nombre": "otra"})
        self.assertEqual(self.client.post("/api/etiquetas/renombrar", json=plan).status_code, 409)

    def test_mover_etiqueta_vacia(self):
        self.client.post("/api/etiquetas/crear", json={"nombre": "lugar|casa"})
        plan = self.client.post("/api/etiquetas/renombrar/preview", json={"origen": "lugar|casa", "destino": "sitios|hogar"}).json()
        self.assertEqual(plan["fotos"], 0)
        self.assertEqual(self.client.post("/api/etiquetas/renombrar", json=plan).status_code, 200)
        etiquetas = self.client.get("/api/resumen").json()["etiquetas"]
        self.assertIn({"id": "sitios|hogar", "total": 0}, etiquetas)

    def test_fallo_parcial_actualiza_indice(self):
        plan = self.client.post("/api/etiquetas/renombrar/preview", json={"origen": "personas", "destino": "gente"}).json()
        escribir = self.panel.et.escribir
        llamadas = []

        def fallar_segunda(*args):
            llamadas.append(args)
            if len(llamadas) == 2:
                raise RuntimeError("Fallo de prueba")
            return escribir(*args)

        with patch.object(self.panel.et, "escribir", side_effect=fallar_segunda):
            r = self.client.post("/api/etiquetas/renombrar", json=plan)
        self.assertEqual(r.status_code, 500)
        self.assertIn("tras 1 fotos", r.json()["detail"])
        self.assertEqual(self.client.get("/api/fotos?etiqueta=gente").json()["total"], 1)
        self.assertEqual(self.client.get("/api/fotos?etiqueta=personas").json()["total"], 1)

    def _ids(self):
        return [f["id"] for f in self.client.get("/api/fotos").json()["fotos"]]

    def _guardar_datos(self, **campos):
        datos = {"ids": self._ids(), **campos}
        preview = self.client.post("/api/metadatos/preview", json=datos)
        self.assertEqual(preview.status_code, 200, preview.text)
        r = self.client.post("/api/metadatos/aplicar", json=preview.json())
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_fechas_parciales_y_completas(self):
        for valor, precision in [("2020", "ano"), ("2020-05", "mes"), ("2020-05-12", "dia"),
                                 ("2020-05-12T14:30:00", "hora"), ("2020-05-12T14:30", "hora")]:
            with self.subTest(valor=valor):
                r = self._guardar_datos(fecha=valor)
                self.assertTrue(r["ok"], r)
                fotos = self.client.get("/api/fotos").json()["fotos"]
                esperado = valor + ":00" if len(valor) == 16 else valor
                self.assertTrue(all(f["fecha"] == esperado and f["fecha_precision"] == precision for f in fotos), fotos)
                self.assertEqual(self.client.get("/api/fotos?bandeja=sin-fecha").json()["total"], 0)

    def test_preserva_exif_gps_etiquetas_y_reconstruccion(self):
        p = self.panel
        ruta = config.BIBLIOTECA / "a.jpg"
        p.et.escribir(ruta, "-EXIF:DateTimeOriginal=2019:01:02 03:04:05", "-EXIF:GPSLatitude=0", "-EXIF:GPSLatitudeRef=N", "-EXIF:GPSLongitude=74", "-EXIF:GPSLongitudeRef=W")
        p.indice.releer(p.db, p.et, ["a.jpg"])
        self.assertEqual(p.db.execute("SELECT lat FROM fotos WHERE ruta='a.jpg'").fetchone()[0], 0)
        antes = {f["id"]: f["etiquetas"] for f in self.client.get("/api/fotos").json()["fotos"]}
        r = self._guardar_datos(fecha="2020-05", lugar="Casa de mi abuela")
        self.assertTrue(r["ok"], r)
        meta = p.et.leer([ruta], "-DateTimeOriginal", "-GPSLatitude", "-GPSLongitude")[0]
        self.assertEqual(meta["DateTimeOriginal"], "2019:01:02 03:04:05")
        self.assertEqual(meta["GPSLatitude"], 0)
        self.assertEqual(meta["GPSLongitude"], -74)
        for f in self.client.get("/api/fotos").json()["fotos"]:
            self.assertTrue(set(antes[f["id"]]) <= set(f["etiquetas"]))
            self.assertIn("lugar|casa-de-mi-abuela", f["etiquetas"])
        temporal = sqlite3.connect(":memory:")
        temporal.row_factory = sqlite3.Row
        temporal.executescript(p.indice._ESQUEMA)
        try:
            self.assertEqual(p.indice.sincronizar(temporal, p.et, progreso=lambda *_: None), 2)
            self.assertTrue(all(f[0] == "2020-05" for f in temporal.execute("SELECT fecha FROM fotos")))
            self.assertEqual(p.indice.sincronizar(temporal, p.et, progreso=lambda *_: None), 0)
        finally:
            temporal.close()

    def test_lugar_no_cambia_fecha_y_fecha_no_cambia_lugares(self):
        self.assertTrue(self._guardar_datos(fecha="2020")["ok"])
        self.assertTrue(self._guardar_datos(lugar="Bogotá")["ok"])
        self.assertTrue(self._guardar_datos(lugar="casa")["ok"])
        for f in self.client.get("/api/fotos").json()["fotos"]:
            self.assertEqual(f["fecha"], "2020")
            self.assertIn("lugar|bogota", f["etiquetas"])
            self.assertIn("lugar|casa", f["etiquetas"])

    def test_metadatos_requiere_confirmacion_y_detecta_conflictos(self):
        datos = {"ids": self._ids(), "fecha": "2020"}
        self.assertEqual(self.client.post("/api/metadatos/aplicar", json=datos).status_code, 409)
        plan = self.client.post("/api/metadatos/preview", json=datos).json()
        self.panel.et.escribir(config.BIBLIOTECA / "a.jpg", "-XMP-dc:Description=cambio externo")
        self.assertEqual(self.client.post("/api/metadatos/aplicar", json=plan).status_code, 409)
        for fecha in ["2020-02-30", "no", "2020-13", ""]:
            self.assertEqual(self.client.post("/api/metadatos/preview", json={**datos, "fecha": fecha}).status_code, 400)
        self.assertEqual(self.client.post("/api/metadatos/preview", json={"ids": self._ids()}).status_code, 400)

    def test_metadatos_fallo_parcial_informa_y_refresca(self):
        plan = self.client.post("/api/metadatos/preview", json={"ids": self._ids(), "fecha": "2021"}).json()
        escribir = self.panel.et.escribir
        n = []

        def fallo(*args):
            n.append(1)
            if len(n) == 2:
                raise RuntimeError("Fallo de prueba")
            return escribir(*args)

        with patch.object(self.panel.et, "escribir", side_effect=fallo):
            r = self.client.post("/api/metadatos/aplicar", json=plan).json()
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["completadas"]), 1)
        self.assertEqual(len(r["fallidas"]), 1)
        self.assertIn("Fallo de prueba", r["fallidas"][0]["error"])
        self.assertEqual(self.client.get("/api/fotos?bandeja=sin-fecha").json()["total"], 1)

    def test_tipo_unico_sin_mover_y_sin_tipo_en_documentos(self):
        ids = self._ids()
        self.panel.db.execute("UPDATE fotos SET carpeta='documentos'")
        self.panel.db.commit()
        self.assertEqual(self.client.get("/api/fotos?bandeja=sin-tipo").json()["total"], 2)
        for tipo in ["foto", "documento"]:
            r = self.client.post("/api/etiquetar", json={"ids": ids, "agregar": ["tipo|" + tipo]})
            self.assertEqual(r.status_code, 200)
        for f in self.client.get("/api/fotos").json()["fotos"]:
            self.assertEqual([t for t in f["etiquetas"] if t.startswith("tipo|")], ["tipo|documento"])
            self.assertIn(f["ruta"], ["a.jpg", "b.jpg"])
        for agregar in [["tipo|foto", "tipo|meme"], ["tipo|selfie"]]:
            self.assertEqual(self.client.post("/api/etiquetar", json={"ids": ids, "agregar": agregar}).status_code, 400)

    def test_conexion_habilitada_y_restringida(self):
        from pm import red
        with patch.object(red, "direcciones", return_value=["192.168.1.10", "10.0.0.8"]):
            self.panel.app.state.host = "0.0.0.0"
            self.panel.app.state.puerto = 9000
            datos = self.client.get("/api/conexion").json()
            self.assertTrue(datos["habilitada"])
            self.assertEqual(datos["urls"], ["http://192.168.1.10:9000", "http://10.0.0.8:9000"])
            self.panel.app.state.host = "127.0.0.1"
            datos = self.client.get("/api/conexion").json()
            self.assertFalse(datos["habilitada"])
            self.assertEqual(datos["urls"], [])

    def test_avif_png_fechas_y_lugar(self):
        p = self.panel
        for extension in ["avif", "png"]:
            ruta = config.BIBLIOTECA / ("temporal." + extension)
            try:
                Image.new("RGB", (20, 20)).save(ruta)
                p.indice.releer(p.db, p.et, [ruta.name])
                foto_id = p.db.execute("SELECT id FROM fotos WHERE ruta=?", (ruta.name,)).fetchone()[0]
                plan = self.client.post("/api/metadatos/preview", json={"ids": [foto_id], "fecha": "2018-06", "lugar": "Bogotá"}).json()
                r = self.client.post("/api/metadatos/aplicar", json=plan)
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(r.json()["ok"], r.json())
            finally:
                ruta.unlink(missing_ok=True)
                p.db.execute("DELETE FROM fotos WHERE ruta=?", (ruta.name,))
                p.db.commit()

    def test_actualiza_indice_antiguo_una_vez(self):
        p = self.panel
        p.et.escribir(config.BIBLIOTECA / "a.jpg", "-XMP-photoshop:DateCreated=2017")
        p.indice.releer(p.db, p.et, ["a.jpg"])
        # Simula un índice anterior que ignora XMP pero tiene firmas vigentes.
        p.db.execute("UPDATE fotos SET fecha=NULL")
        p.db.execute("PRAGMA user_version=0")
        p.db.commit()
        self.assertEqual(p.indice.sincronizar(p.db, p.et, progreso=lambda *_: None), 2)
        self.assertEqual(p.db.execute("SELECT fecha FROM fotos WHERE ruta='a.jpg'").fetchone()[0], "2017")
        self.assertEqual(p.indice.sincronizar(p.db, p.et, progreso=lambda *_: None), 0)

    def test_etiquetado_verifica_fallos_y_no_reescribe_asignadas(self):
        with patch.object(self.panel.et, "escribir", wraps=self.panel.et.escribir) as escribir:
            r = self.client.post("/api/etiquetar", json={"ids": self._ids(), "agregar": ["personas|ana"]})
            self.assertTrue(r.json()["ok"])
            escribir.assert_not_called()
        with patch.object(self.panel.et, "escribir", return_value="0 image files updated"):
            r = self.client.post("/api/etiquetar", json={"ids": self._ids(), "agregar": ["personas|nueva"]})
        self.assertFalse(r.json()["ok"])
        self.assertEqual(r.json()["actualizadas"], 0)
        self.assertEqual(len(r.json()["fallidas"]), 2)


if __name__ == "__main__":
    unittest.main()
