"""Verificación de interfaz con respuestas ficticias, sin acceder a la biblioteca."""
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


class Silencioso(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


servidor = ThreadingHTTPServer(("127.0.0.1", 0), partial(Silencioso, directory=str(Path(__file__).resolve().parents[1] / "pm/static")))
threading.Thread(target=servidor.serve_forever, daemon=True).start()
etiquetas = [{"id": "personas", "total": 2}, {"id": "personas|ana", "total": 2},
             {"id": "personas|luis", "total": 1}, {"id": "_ia", "total": 2}, {"id": "_ia|v1", "total": 2}]
confirmaciones = []


def responder(route):
    url = route.request.url
    if url.endswith("/api/conexion"):
        datos = {"habilitada": False, "puerto": 8642, "urls": []}
    elif url.endswith("/api/resumen"):
        datos = {"etiquetas": etiquetas, "carpetas": [{"id": "2026", "total": 2}],
                 "bandejas": [{"id": "todas", "nombre": "Todas", "total": 2}]}
    elif "/api/fotos" in url:
        datos = {"total": 0, "fotos": []}
    elif url.endswith("/crear"):
        etiquetas.append({"id": "lugar", "total": 0})
        datos = {"nombre": "lugar"}
    elif url.endswith("/preview"):
        datos = {"origen": "personas", "destino": "gente", "fotos": 2, "confirmacion": "prueba"}
    elif url.endswith("/renombrar"):
        confirmaciones.append(route.request.post_data_json)
        datos = {"origen": "personas", "destino": "gente", "actualizadas": 2}
    else:
        raise AssertionError(url)
    route.fulfill(json=json.loads(json.dumps(datos)))


try:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        errores = []
        page.on("pageerror", lambda e: errores.append(str(e)))
        page.route("**/api/**", responder)
        page.goto(f"http://127.0.0.1:{servidor.server_port}")
        if page.viewport_size["width"] < 768:
            page.locator("#navegacion [data-seccion=explorar]").click()
        grupo = page.locator('#etiquetas details[data-ruta="personas"]')
        grupo.wait_for()
        assert not grupo.get_attribute("open")
        grupo.locator("summary .desplegar").click()
        assert grupo.locator(".etiqueta-hijos").is_visible()
        grupo.locator("summary button").click()
        page.wait_for_url("**/*tag=personas")
        assert page.locator("#etiquetas-internas").is_hidden()
        if page.viewport_size["width"] < 768:
            page.locator("#navegacion [data-seccion=explorar]").click()
        page.locator("#filtro-etiquetas").fill("ana")
        assert page.locator("#etiquetas .etiqueta-hijos button").count() == 1
        if page.viewport_size["width"] < 768:
            page.locator("#navegacion [data-seccion=gestionar]").click()
        page.locator("#administrar-etiquetas").click()
        page.locator("#crear-nombre").fill("lugar")
        page.locator("#crear-etiqueta button").click()
        page.get_by_text("Etiqueta creada: lugar", exact=True).wait_for()
        page.locator(".admin-fila").filter(has=page.get_by_text("personas", exact=True)).get_by_role("button").click()
        page.locator("#renombrar-destino").fill("gente")
        page.locator("#renombrar-etiqueta button").click()
        page.locator("#admin-preview").wait_for()
        assert not confirmaciones
        assert "2 fotos" in page.locator("#admin-impacto").inner_text()
        page.locator("#admin-confirmar").click()
        page.get_by_text("Renombrado completado: 2 fotos actualizadas.", exact=True).wait_for()
        assert confirmaciones[0]["confirmacion"] == "prueba"
        page.set_viewport_size({"width": 390, "height": 640})
        caja = page.locator("#administrador").bounding_box()
        assert caja["x"] >= 0 and caja["x"] + caja["width"] <= 390
        assert page.locator("#admin-listo").is_visible()
        page.screenshot(path=str(Path(__file__).resolve().parents[1] / "datos/admin-etiquetas-verificacion.png"))
        page.keyboard.press("Escape")
        page.locator("#administrador").wait_for(state="hidden")
        assert not errores, errores
        browser.close()
        print("UI OK: grupos, filtro, creación, preview, confirmación, modal móvil y teclado.")
finally:
    servidor.shutdown()
    servidor.server_close()
