import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import urlopen

from fastapi import FastAPI
from pm.escritorio import abrir_panel, SelectorOriginales


class EscritorioTest(unittest.TestCase):
    def test_selector_originales_nativo_y_cancelacion(self):
        from unittest.mock import Mock
        selector = SelectorOriginales(SimpleNamespace(FOLDER_DIALOG=10))
        self.assertIsNone(selector.elegir_originales())
        selector._ventana = Mock()
        selector._ventana.create_file_dialog.return_value = ("D:\\Originales",)
        self.assertEqual(selector.elegir_originales(), "D:\\Originales")
        selector._ventana.create_file_dialog.assert_called_once_with(10)
        selector._ventana.create_file_dialog.return_value = None
        self.assertIsNone(selector.elegir_originales())

    def setUp(self):
        self.app = FastAPI()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.puerto = sock.getsockname()[1]

    def libre(self):
        with socket.socket() as sock:
            self.assertNotEqual(sock.connect_ex(('127.0.0.1', self.puerto)), 0)

    def test_listo_antes_de_ventana_y_cierre(self):
        def crear(titulo, url, **opciones):
            self.assertEqual(titulo, 'Photo Manager')
            self.assertLessEqual(opciones['height'], 688)
            with urlopen(url + '/openapi.json') as respuesta:
                self.assertEqual(respuesta.status, 200)
        vista = SimpleNamespace(
            screens=[SimpleNamespace(width=1024, height=768)],
            create_window=crear, start=lambda **kwargs: None,
        )
        for _ in range(2):
            abrir_panel(self.app, '127.0.0.1', self.puerto, webview_module=vista)
            self.libre()

    def test_fallo_ventana_libera_servidor(self):
        vista = SimpleNamespace(screens=[])
        with self.assertRaisesRegex(RuntimeError, 'WebView2'):
            abrir_panel(self.app, '127.0.0.1', self.puerto, webview_module=vista)
        self.libre()

    def test_fallo_servidor_no_abre_ventana(self):
        with patch('pm.escritorio.uvicorn.Server.run', side_effect=OSError('fallo')):
            with self.assertRaisesRegex(RuntimeError, 'No se pudo iniciar'):
                abrir_panel(self.app, '127.0.0.1', self.puerto, webview_module=object())
        self.libre()

    def test_modos_cli_excluyentes(self):
        import fotos
        with patch('sys.argv', ['fotos.py', 'panel', '--navegador', '--sin-navegador']):
            with self.assertRaises(SystemExit) as salida:
                fotos.main()
            self.assertEqual(salida.exception.code, 2)

    def test_navegador_ctrl_c_libera_servidor(self):
        with patch('pm.escritorio.webbrowser.open', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                abrir_panel(self.app, '127.0.0.1', self.puerto, navegador=True)
        self.libre()

    def test_cli_solo_servidor_y_puerto_ocupado(self):
        import fotos
        import sys
        args = SimpleNamespace(puerto=self.puerto, host='127.0.0.1',
                               sin_navegador=True, navegador=False)
        panel = SimpleNamespace(app=self.app)
        with patch.dict(sys.modules, {'pm.panel': panel}):
            with patch('uvicorn.run') as run:
                fotos.cmd_panel(args)
                run.assert_called_once_with(self.app, host='127.0.0.1',
                                            port=self.puerto, log_level='warning')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', self.puerto))
            sock.listen()
            with patch('uvicorn.run') as run:
                fotos.cmd_panel(args)
                run.assert_not_called()
            with socket.socket() as cliente:
                self.assertEqual(cliente.connect_ex(('127.0.0.1', self.puerto)), 0)


if __name__ == '__main__':
    unittest.main()
