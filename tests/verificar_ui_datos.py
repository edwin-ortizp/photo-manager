"""Navegador contra API y metadatos reales, exclusivamente en biblioteca temporal."""
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from PIL import Image
from playwright.sync_api import sync_playwright

from pm import config
from pm.etiquetas import asignaciones


with tempfile.TemporaryDirectory() as tmp:
    raiz = Path(tmp)
    config.BIBLIOTECA = raiz / "fotos"
    config.DATOS = raiz / "datos"
    config.INDICE = config.DATOS / "indice.db"
    config.MINIATURAS = config.DATOS / "miniaturas"
    config.BIBLIOTECA.mkdir()
    from pm import panel

    personas = [f"personas|persona-{n:02}" for n in range(12)]
    lugares = [f"lugar|sitio-{n:02}" for n in range(8)]
    for n, color in enumerate(["#375377", "#654b80", "#4a7762"]):
        ruta = config.BIBLIOTECA / f"foto-{n}.jpg"
        Image.new("RGB", (640, 480), color).save(ruta)
        tags = [*personas, *lugares, "personas|desconocido", "escena|selfie", "_ia|v1"]
        if n == 0:
            tags.append("tipo|foto")
        panel.et.escribir(ruta, *asignaciones(tags), "-XMP-photoshop:DateCreated=2020:05")
    sock = socket.socket()
    sock.bind(("0.0.0.0", 0))
    puerto = sock.getsockname()[1]
    panel.app.state.host = "0.0.0.0"
    panel.app.state.puerto = puerto
    server = uvicorn.Server(uvicorn.Config(panel.app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errores = []
            errores_http = []
            page.on("pageerror", lambda e: errores.append(str(e)))
            page.on("response", lambda r: errores_http.append(f"{r.status}: {r.url}") if r.status >= 500 else None)
            page.goto(f"http://127.0.0.1:{puerto}")
            page.locator(".foto").first.wait_for()
            for ancho, alto in [(1440, 1000), (390, 844)]:
                page.set_viewport_size({"width": ancho, "height": alto})
                for bandeja, nombre, total in [("sin-estilo", "Sin estilo", 3), ("sin-momento", "Sin momento", 3),
                                                ("sin-tema", "Sin tema", 3), ("sin-persona", "Sin persona", 0)]:
                    if page.viewport_size["width"] < 768:
                        page.locator("#navegacion [data-seccion=gestionar]").click()
                    item = page.locator("#bandejas li").filter(has=page.get_by_text(nombre, exact=True))
                    assert item.locator(".n").inner_text() == str(total)
                    item.click()
                    page.wait_for_url(f"**/*bandeja={bandeja}")
                    page.wait_for_function("n => document.querySelectorAll('.foto').length === n", arg=total)
                    page.reload()
                    if page.viewport_size["width"] < 768:
                        page.locator("#navegacion [data-seccion=gestionar]").click()
                    page.locator("#bandejas li.activo").wait_for()
                    assert nombre in page.locator("#bandejas li.activo").inner_text()
                page.locator("#bandejas li").filter(has=page.get_by_text("Todas", exact=True)).click()
                page.locator(".foto").first.wait_for()
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.evaluate("document.fonts.ready")
            assert page.evaluate('document.fonts.check("14px Nunito")')
            assert "Nunito" in page.locator("body").evaluate("e => getComputedStyle(e).fontFamily")
            if page.viewport_size["width"] < 768:
                page.locator("#navegacion [data-seccion=gestionar]").click()
            page.locator("#conexion summary").click()
            page.wait_for_function('!document.querySelector("#conexion-direcciones").textContent.includes("Consultando")')
            assert "misma red" in page.locator("#conexion-direcciones").inner_text()
            if page.viewport_size["width"] < 768:
                page.locator("#navegacion [data-seccion=fotos]").click()
            page.locator(".foto").first.click()
            assert page.locator("#detalle h2").all_text_contents()[:9] == ["Tipo", "Lugar", "Personas", "Mascotas", "Vehículos", "Estilo", "Momento", "Tema", "Fecha"]
            for rama in ["mascotas", "vehiculos", "estilo", "momento", "tema"]:
                assert "Todavía no hay etiquetas" in page.locator(f"#frecuentes-{rama}").inner_text()
            assert not panel.CATALOGO.exists(), "Mostrar los grupos no debe crear etiquetas"
            nuevas = {"mascotas": "simon", "vehiculos": "mi-carro", "estilo": "selfie", "momento": "dia", "tema": "arquitectura"}
            for rama, nombre in nuevas.items():
                r = page.request.post(f"http://127.0.0.1:{puerto}/api/etiquetas/crear", data={"nombre": rama + "|" + nombre})
                assert r.ok
            page.reload()
            page.locator(".foto").first.click()
            for rama, nombre in nuevas.items():
                # Las etiquetas vacías que administra el usuario también están disponibles.
                page.locator(f"#frecuentes-{rama} button").click()
                page.locator(f"#chips-{rama} .chip").wait_for()
                assert nombre in page.locator(f"#chips-{rama}").inner_text()
            assert "escena" in page.locator("#sel-etiquetas").text_content()
            assert "escena|selfie" in panel.fotos()["fotos"][0]["etiquetas"]
            # Quitar y volver a asignar desde el control reutilizado del grupo.
            page.locator("#chips-mascotas .chip button").click()
            page.locator("#chips-mascotas .chip").wait_for(state="detached")
            page.locator("#agregar-mascotas").fill("simon")
            page.get_by_role("button", name="Asignar etiqueta de Mascotas", exact=True).click()
            page.locator("#chips-mascotas .chip").wait_for()
            assert page.locator("#frecuentes-personas button").count() == 8
            assert page.locator("#frecuentes-lugar button").count() == 6
            assert "desconocido" not in page.locator("#frecuentes-personas").inner_text()
            assert "día desconocido" in page.locator("#fecha-resumen").inner_text()
            page.locator("#tipo-principal").select_option("documento")
            page.wait_for_function('document.querySelector("#tipo-principal").value === "documento"')
            page.locator("#agregar-persona").fill("Amiga nueva")
            page.locator("#agregar-persona").press("Enter")
            page.get_by_text("amiga-nueva", exact=True).wait_for()
            page.locator("#detalle").screenshot(path=str(config.DATOS / "detalle-desktop.png"))
            page.locator("#sel-limpiar").click()
            page.locator(".dia button").first.click()
            page.locator("#frecuentes-mascotas button").click()
            page.wait_for_function('document.querySelector("#chips-mascotas .n")?.textContent === "3"')
            page.locator("#editar-datos").click()
            assert "3 foto(s)" in page.locator("#editor-seleccion").inner_text()
            page.locator("#modificar-fecha").check()
            page.locator("#fecha-precision").select_option("ano")
            page.locator("#fecha-valor").fill("2018")
            page.locator("#modificar-lugar").check()
            page.locator("#lugar-valor").fill("Casa de mi abuela")
            page.locator("#form-datos button").click()
            page.locator("#datos-preview").wait_for()
            assert "3 fechas existentes" in page.locator("#datos-impacto").inner_text()
            assert all(f["fecha"] == "2020-05" for f in panel.fotos()["fotos"])
            # Editar después de revisar debe invalidar la confirmación anterior.
            page.locator("#fecha-valor").fill("2019")
            assert page.locator("#datos-preview").is_hidden()
            page.locator("#form-datos button").click()
            page.locator("#datos-preview").wait_for()
            page.locator("#datos-confirmar").click()
            page.get_by_text("3 foto(s) completadas; 0 con errores.", exact=True).wait_for()
            assert all(f["fecha"] == "2019" and "lugar|casa-de-mi-abuela" in f["etiquetas"] for f in panel.fotos()["fotos"])
            page.locator("#editor-listo").click()
            page.locator(".foto").first.click()
            page.set_viewport_size({"width": 390, "height": 720})
            page.locator("#seleccion-acciones").click()
            assert page.locator("#sel-limpiar").is_visible()
            page.locator("#detalle").evaluate("e => e.scrollTop = e.scrollHeight")
            caja = page.locator("#sel-limpiar").bounding_box()
            assert caja and caja["y"] >= 0 and caja["y"] + caja["height"] < 720
            page.locator("#editar-datos").click()
            page.locator("#modificar-fecha").check()
            page.locator("#fecha-precision").select_option("mes")
            page.locator("#fecha-valor").fill("2019-06")
            page.locator("#form-datos button").click()
            page.locator("#datos-preview").wait_for()
            caja = page.locator("#editor-datos").bounding_box()
            assert caja and caja["x"] >= 0 and caja["x"] + caja["width"] <= 390
            page.screenshot(path=str(config.DATOS / "editor-movil.png"))
            # Copias de evidencia fuera de la biblioteca temporal.
            import shutil
            destino = Path(__file__).resolve().parents[1] / "datos"
            destino.mkdir(exist_ok=True)
            for nombre in ["detalle-desktop.png", "editor-movil.png"]:
                shutil.copy2(config.DATOS / nombre, destino / nombre)
            page.keyboard.press("Escape")
            page.locator("#editor-datos").wait_for(state="hidden")
            assert not errores, errores
            assert not errores_http, errores_http
            browser.close()
        # Tráfico real hacia la interfaz LAN del PC, sin proxy ni fotos personales.
        urls = panel.conexion()["urls"]
        accesibles = []
        for url in urls:
            try:
                with build_opener(ProxyHandler({})).open(url + "/api/conexion", timeout=3) as respuesta:
                    assert respuesta.status == 200
                    accesibles.append(url)
            except OSError:
                pass
        print(f"UI OK: ocho grupos, catálogo vacío sin crear tags, etiquetas nuevas del administrador, asignar/quitar por grupo, lote, API temporal real, fuente local, fechas parciales, confirmación y móvil. Interfaces LAN accesibles desde PC: {len(accesibles)}. Sin prueba desde celular físico.")
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        panel.et.cerrar()
        panel.db.close()
        sock.close()
