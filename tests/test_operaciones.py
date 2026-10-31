"""Pruebas aisladas de planes y operaciones; nunca usan la biblioteca personal."""
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pm.operaciones import Operaciones, enviar_papelera


class OperacionesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.bib = self.raiz / 'fotos'
        self.bib.mkdir()
        (self.bib / 'origen').mkdir()
        (self.bib / 'vacia').mkdir()
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE fotos (id INTEGER PRIMARY KEY, ruta TEXT UNIQUE, carpeta TEXT, etiquetas TEXT)')
        for i in range(1, 4):
            (self.bib / 'origen' / f'{i}.jpg').write_bytes(b'foto con metadatos XMP')
            self.db.execute('INSERT INTO fotos VALUES (?, ?, ?, ?)', (i, f'origen/{i}.jpg', 'origen', '["personas|ana"]'))
        self.db.commit()
        self.ops = Operaciones(self.bib, self.raiz / 'datos', self.db, threading.RLock())

    def revisar(self, ids=None, operacion='mover', destino='vacia'):
        return self.ops.preview(ids or [1, 2], operacion, destino)

    def ejecutar(self, p, texto=None):
        return self.ops.aplicar(p['token'], p['frase'] if texto is None else texto)

    def test_confirmacion_exacta_y_uso_unico(self):
        p = self.revisar()
        self.assertEqual(p['frase'], 'MOVER 2 FOTOS')
        for texto in ['', 'MOVER', 'mover 2 fotos', 'MOVER 2 FOTOS ']:
            with self.assertRaises(HTTPException):
                self.ejecutar(p, texto)
        r = self.ejecutar(p)
        self.assertTrue(r['ok'])
        self.assertEqual(len(r['completadas']), 2)
        self.assertEqual((self.bib / 'vacia/1.jpg').read_bytes(), b'foto con metadatos XMP')
        fila = self.db.execute('SELECT * FROM fotos WHERE id = 1').fetchone()
        self.assertEqual(fila['ruta'], 'vacia/1.jpg')
        self.assertEqual(fila['etiquetas'], '["personas|ana"]')
        with self.assertRaises(HTTPException):
            self.ejecutar(p)
        eventos = [json.loads(l) for l in (self.raiz / 'datos' / r['bitacora']).read_text(encoding='utf-8').splitlines()]
        self.assertEqual([e['evento'] for e in eventos], ['inicio', 'completada', 'completada', 'fin'])

    def test_vencimiento(self):
        p = self.revisar()
        self.ops.planes[p['token']]['vence'] = 0
        with self.assertRaises(HTTPException):
            self.ejecutar(p)
        self.assertTrue((self.bib / 'origen/1.jpg').exists())

    def test_archivo_modificado_identidad_y_ruta(self):
        for cambio in ('contenido', 'reemplazo', 'indice'):
            with self.subTest(cambio=cambio):
                p = self.revisar()
                ruta = self.bib / 'origen/1.jpg'
                if cambio == 'contenido':
                    ruta.write_bytes(b'cambio')
                elif cambio == 'reemplazo':
                    ruta.rename(ruta.with_suffix('.old'))
                    ruta.write_bytes(b'cambio')
                else:
                    self.db.execute("UPDATE fotos SET etiquetas = '[]' WHERE id = 1")
                    self.db.commit()
                with self.assertRaises(HTTPException):
                    self.ejecutar(p)
                self.assertFalse((self.bib / 'vacia/1.jpg').exists())

    def test_destinos_y_selecciones_invalidas(self):
        (self.bib / '.oculta').mkdir()
        for ids, destino in [([], 'vacia'), ([999], 'vacia'), ([1], '../fuera'), ([1], str(self.raiz)),
                              ([1], 'no-existe'), ([1], '.oculta'), ([1], 'origen')]:
            with self.subTest(ids=ids, destino=destino), self.assertRaises(HTTPException):
                self.ops.preview(ids, 'mover', destino)
        rutas = {c['ruta'] for c in self.ops.carpetas()}
        self.assertIn('vacia', rutas)
        self.assertIn('', rutas)
        self.assertNotIn('.oculta', rutas)

    def test_conflicto_antes_y_despues_de_preview(self):
        p = self.revisar()
        (self.bib / 'vacia/1.jpg').write_bytes(b'no tocar')
        with self.assertRaises(HTTPException):
            self.ejecutar(p)
        with self.assertRaises(HTTPException):
            self.revisar()
        self.assertEqual((self.bib / 'vacia/1.jpg').read_bytes(), b'no tocar')

    def test_nombres_duplicados_en_lote(self):
        (self.bib / '1.jpg').write_bytes(b'otra')
        self.db.execute("INSERT INTO fotos VALUES (4, '1.jpg', '', '[]')")
        with self.assertRaises(HTTPException):
            self.revisar([1, 4])

    def test_destino_reemplazado(self):
        p = self.revisar()
        (self.bib / 'vacia').rename(self.bib / 'anterior')
        (self.bib / 'vacia').mkdir()
        with self.assertRaises(HTTPException):
            self.ejecutar(p)
        self.assertTrue((self.bib / 'origen/1.jpg').exists())

    def test_bitacora_no_disponible_no_mueve(self):
        p = self.revisar()
        self.ops.datos.write_text('no es directorio', encoding='utf-8')
        with self.assertRaises(OSError):
            self.ejecutar(p)
        self.assertTrue((self.bib / 'origen/1.jpg').exists())

    @unittest.skipUnless(os.name == 'nt', 'atributo oculto de Windows')
    def test_carpeta_oculta_windows(self):
        import ctypes
        ruta = self.bib / 'vacia'
        self.assertTrue(ctypes.windll.kernel32.SetFileAttributesW(str(ruta), 2))
        self.addCleanup(lambda: ctypes.windll.kernel32.SetFileAttributesW(str(ruta), 128))
        with self.assertRaises(HTTPException):
            self.revisar()
        self.assertNotIn('vacia', {c['ruta'] for c in self.ops.carpetas()})

    def test_archivo_ausente(self):
        p = self.revisar()
        (self.bib / 'origen/1.jpg').unlink()
        with self.assertRaises(HTTPException):
            self.ejecutar(p)

    def test_junction_externa(self):
        if os.name != 'nt':
            self.skipTest('junction de Windows')
        import subprocess
        fuera = self.raiz / 'fuera'
        fuera.mkdir()
        enlace = self.bib / 'enlace'
        r = subprocess.run(['cmd', '/c', 'mklink', '/J', str(enlace), str(fuera)], capture_output=True)
        self.assertEqual(r.returncode, 0)
        self.addCleanup(lambda: os.rmdir(enlace) if enlace.exists() else None)
        with self.assertRaises(HTTPException):
            self.revisar(destino='enlace')
        self.assertNotIn('enlace', {c['ruta'] for c in self.ops.carpetas()})

    def test_papelera_fallo_parcial_y_reintento_bloqueado(self):
        p = self.revisar([1, 2, 3], 'papelera', '')
        self.assertEqual(p['frase'], 'ENVIAR 3 FOTOS A LA PAPELERA')
        def papelera(ruta):
            if ruta.name == '2.jpg':
                raise OSError('papelera no disponible')
            ruta.rename(self.raiz / ruta.name)
        with patch('pm.operaciones.enviar_papelera', side_effect=papelera):
            r = self.ejecutar(p)
        self.assertFalse(r['ok'])
        self.assertEqual([x['id'] for x in r['completadas']], [1])
        self.assertEqual([x['id'] for x in r['fallidas']], [2])
        self.assertEqual([x['id'] for x in r['pendientes']], [3])
        self.assertIsNone(self.db.execute('SELECT * FROM fotos WHERE id = 1').fetchone())
        self.assertTrue((self.bib / 'origen/2.jpg').exists())
        with self.assertRaises(HTTPException):
            self.ejecutar(p)

    def test_papelera_sin_confirmacion_del_sistema(self):
        p = self.revisar([1], 'papelera', '')
        self.assertEqual(p['frase'], 'ENVIAR 1 FOTO A LA PAPELERA')
        with patch('pm.operaciones.enviar_papelera'):
            r = self.ejecutar(p)
        self.assertFalse(r['ok'])
        self.assertTrue((self.bib / 'origen/1.jpg').exists())
        self.assertIsNotNone(self.db.execute('SELECT * FROM fotos WHERE id = 1').fetchone())

    def test_adaptador_sin_borrado_al_fallar(self):
        ruta = self.bib / 'origen/1.jpg'
        with patch('send2trash.send2trash', side_effect=OSError('fallo')):
            with self.assertRaises(OSError):
                enviar_papelera(ruta)
        self.assertTrue(ruta.exists())

    @unittest.skipUnless(os.name == 'nt', 'requiere papelera de Windows')
    def test_papelera_windows_real_solo_archivo_temporal(self):
        ruta = self.raiz / 'photo-manager-prueba-papelera.txt'
        ruta.write_text('Archivo temporal de prueba de Photo Manager', encoding='utf-8')
        enviar_papelera(ruta)
        self.assertFalse(ruta.exists())


if __name__ == '__main__':
    unittest.main()
