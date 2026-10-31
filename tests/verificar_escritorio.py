"""Smoke real WebView2 en Windows, exclusivamente con biblioteca temporal."""
import socket
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webview
from PIL import Image
from pm import config
from pm.escritorio import abrir_panel


with tempfile.TemporaryDirectory() as tmp:
    raiz = Path(tmp)
    config.BIBLIOTECA = raiz / 'fotos'
    config.DATOS = raiz / 'datos'
    config.INDICE = config.DATOS / 'indice.db'
    config.MINIATURAS = config.DATOS / 'miniaturas'
    config.BIBLIOTECA.mkdir()
    Image.new('RGB', (640, 480), '#375377').save(config.BIBLIOTECA / 'prueba.jpg')
    from pm import panel
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        puerto = sock.getsockname()[1]
    panel.app.state.host = '0.0.0.0'
    panel.app.state.puerto = puerto
    errores = []
    direcciones = []

    def verificar():
        ventana = webview.windows[0]
        try:
            limite = time.monotonic() + 30
            while not ventana.evaluate_js('document.querySelectorAll(".foto").length > 0'):
                assert time.monotonic() < limite, 'No cargó la foto temporal'
                time.sleep(.1)
            while not ventana.evaluate_js('document.querySelector(".foto img").complete && document.querySelector(".foto img").naturalWidth > 0'):
                assert time.monotonic() < limite, 'No cargó la miniatura'
                time.sleep(.1)
            while not ventana.evaluate_js('!!window.pywebview?.api?.elegir_originales'):
                assert time.monotonic() < limite, 'No se expuso el selector nativo de originales'
                time.sleep(.1)
            assert ventana.evaluate_js('getComputedStyle(document.querySelector("#lateral")).display !== "none"'), 'El sidebar de PC debe permanecer visible'
            assert ventana.evaluate_js('getComputedStyle(document.querySelector("#navegacion")).display === "none"'), 'PC no debe usar navegación móvil'
            ventana.evaluate_js('document.querySelector("#abrir-auditoria").click()')
            while not ventana.evaluate_js('document.querySelector("#flujo").open'):
                assert time.monotonic() < limite, 'No abrió la auditoría en WebView2'
                time.sleep(.1)
            ventana.evaluate_js('document.querySelector("#flujo-cerrar").click()')
            while ventana.evaluate_js('document.querySelector("#flujo").open'):
                assert time.monotonic() < limite, 'No cerró la auditoría'
                time.sleep(.05)
            ventana.evaluate_js('document.querySelector("#administrar-etiquetas").click()')
            limite = time.monotonic() + 10
            while not ventana.evaluate_js('document.querySelector("#administrador").open'):
                assert time.monotonic() < limite, 'No abrió el diálogo'
                time.sleep(.1)
            ventana.evaluate_js('document.querySelector("#admin-cerrar").click()')
            while ventana.evaluate_js('document.querySelector("#administrador").open'):
                assert time.monotonic() < limite, 'No cerró el administrador'
                time.sleep(.05)
            ventana.evaluate_js('document.querySelector("#buscar").value="inexistente"; document.querySelector("#buscar").dispatchEvent(new Event("input"))')
            limite = time.monotonic() + 10
            while ventana.evaluate_js('document.querySelectorAll(".foto").length'):
                assert time.monotonic() < limite, 'No funciona el filtro'
                time.sleep(.1)
            for url in panel.conexion()['urls']:
                try:
                    with build_opener(ProxyHandler({})).open(url + '/api/conexion', timeout=3) as respuesta:
                        assert respuesta.status == 200
                        direcciones.append(url)
                except OSError:
                    pass
        except BaseException as exc:
            errores.append(exc)
        finally:
            ventana.destroy()

    class Vista:
        @property
        def screens(self):
            return webview.screens

        create_window = staticmethod(webview.create_window)

        @staticmethod
        def start(**kwargs):
            webview.start(verificar, **kwargs)

    try:
        abrir_panel(panel.app, '0.0.0.0', puerto, webview_module=Vista())
        assert not errores, errores
        for host in ['127.0.0.1', *[url.split('//')[1].split(':')[0] for url in direcciones]]:
            with socket.socket() as sock:
                assert sock.connect_ex((host, puerto)) != 0, 'Servidor activo tras cerrar'
        print(f'WebView2 OK: foto, filtro, diálogo, cierre y puerto liberado. LAN desde PC: {len(direcciones)} interfaces. Sin celular físico.')
    finally:
        panel.et.cerrar()
        panel.db.close()
