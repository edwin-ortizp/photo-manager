"""Ventana de escritorio y ciclo de vida del servidor del panel."""
import threading
import time
import webbrowser

import uvicorn


class SelectorOriginales:
    """Puente disponible exclusivamente en la ventana nativa del PC."""
    def __init__(self, modulo):
        self._modulo = modulo
        self._ventana = None

    def elegir_originales(self):
        if self._ventana is None:
            return None
        seleccion = self._ventana.create_file_dialog(self._modulo.FOLDER_DIALOG)
        return seleccion[0] if seleccion else None


def abrir_panel(app, host, puerto, *, navegador=False, webview_module=None):
    if not navegador and webview_module is None:
        try:
            import webview as webview_module
        except ImportError as exc:
            raise RuntimeError(
                'Falta pywebview. Instala con: python -m pip install pywebview. '
                'Alternativa: python fotos.py panel --navegador'
            ) from exc

    servidor = uvicorn.Server(uvicorn.Config(app, host=host, port=puerto, log_level="warning"))
    errores = []

    def servir():
        try:
            servidor.run()
        except BaseException as exc:
            errores.append(exc)

    hilo = threading.Thread(target=servir, name="photo-manager-servidor")
    hilo.start()
    try:
        limite = time.monotonic() + 30
        while not servidor.started:
            if not hilo.is_alive() or time.monotonic() >= limite:
                raise RuntimeError(f'No se pudo iniciar el panel: {errores or "tiempo de espera agotado"}')
            time.sleep(.05)
        url = f"http://127.0.0.1:{puerto}"
        if navegador:
            webbrowser.open(url)
            while hilo.is_alive():
                hilo.join(.2)
        else:
            try:
                pantalla = webview_module.screens[0]
                ancho = min(1280, max(200, pantalla.width - 40))
                alto = min(850, max(100, pantalla.height - 80))
                selector = SelectorOriginales(webview_module)
                selector._ventana = webview_module.create_window(
                    "Photo Manager", url, width=ancho, height=alto,
                    min_size=(min(800, ancho), min(600, alto)), resizable=True,
                    js_api=selector,
                )
                webview_module.start(gui="edgechromium")
            except Exception as exc:
                raise RuntimeError(
                    'No se pudo abrir la ventana. Comprueba pywebview y Microsoft Edge '
                    'WebView2 Runtime. Alternativa: python fotos.py panel --navegador'
                ) from exc
    finally:
        # Uvicorn termina las peticiones en curso antes de liberar el puerto.
        servidor.should_exit = True
        hilo.join()
