"""Flujo real desde Chromium; no usa la biblioteca personal."""
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from PIL import Image
from playwright.sync_api import sync_playwright
from pm import config


with tempfile.TemporaryDirectory() as tmp:
    raiz = Path(tmp)
    config.BIBLIOTECA = raiz / "fotos"
    config.DATOS = raiz / "datos"
    config.INDICE = config.DATOS / "indice.db"
    config.MINIATURAS = config.DATOS / "miniaturas"
    (config.BIBLIOTECA / "entrada/sub").mkdir(parents=True)
    foto = config.BIBLIOTECA / "entrada/sub/prueba.jpg"
    Image.new("RGB", (640, 480), "#375377").save(foto)
    from pm import panel
    panel.et.escribir(foto, "-XMP-photoshop:DateCreated=2020:05", "-HierarchicalSubject=personas|ana")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    puerto = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(panel.app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        limite = time.monotonic() + 20
        while not server.started:
            assert time.monotonic() < limite
            time.sleep(.05)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errores = []
            page.on("pageerror", lambda e: errores.append(str(e)))
            page.goto(f"http://127.0.0.1:{puerto}")
            if page.viewport_size["width"] < 768:
                page.locator("#navegacion [data-seccion=gestionar]").click()
            page.locator("#bandejas li", has_text="Entrada").click()
            page.locator(".foto").first.wait_for()
            assert "Sin tipo" in page.locator(".pendientes-foto").inner_text()
            page.locator(".foto").click()
            page.locator("#convertir-seleccion").click()
            page.locator("#flujo-respaldo").fill(str(raiz / "originales"))
            page.locator("#flujo-revisar").click()
            page.locator("#flujo-preview").wait_for(state="visible")
            assert "Original:" in page.locator("#flujo-lista").inner_text()
            assert page.locator("#flujo-confirmar").is_disabled()
            page.locator("#flujo-texto").fill(page.locator("#flujo-frase").inner_text())
            page.locator("#flujo-confirmar").click()
            page.wait_for_function('document.querySelector("#flujo-trabajos").textContent.includes("convertir: completado")', timeout=45000)
            assert foto.with_suffix(".avif").exists()
            assert not foto.exists()
            assert (raiz / "originales/entrada/sub/prueba.jpg").exists()
            page.locator("#flujo-listo").click()
            page.locator(".foto").click()
            page.locator("#organizar-seleccion").click()
            destino = page.locator("#flujo-destinos input")
            destino.wait_for()
            assert destino.input_value() == "2020"
            destino.fill("2020/revisadas")
            page.locator("#flujo-revisar").click()
            page.locator("#flujo-preview").wait_for(state="visible")
            page.locator("#flujo-texto").fill(page.locator("#flujo-frase").inner_text())
            page.locator("#flujo-confirmar").click()
            page.wait_for_function('document.querySelector("#flujo-trabajos").textContent.includes("organizar: completado")', timeout=15000)
            assert (config.BIBLIOTECA / "2020/revisadas/prueba.avif").exists()
            assert page.locator(".foto").count() == 0, "Debe salir de Entrada después de mover"
            page.locator("#flujo-listo").click()
            if page.viewport_size["width"] < 768:
                page.locator("#navegacion [data-seccion=gestionar]").click()
            page.locator("#abrir-auditoria").click()
            page.locator("#auditar-biblioteca").click()
            page.wait_for_function('document.querySelector("#flujo-trabajos").textContent.includes("auditar: completado")', timeout=15000)
            page.locator("#auditoria-filtro").select_option("conforme")
            assert "AVIF conforme" in page.locator("#auditoria-resultados").inner_text()
            # El inventario incorpora nuevas imágenes sin reiniciar.
            nueva = config.BIBLIOTECA / "entrada/nueva.png"
            Image.new("RGB", (40, 40), "green").save(nueva)
            page.locator("#flujo-listo").click()
            page.locator("#actualizar-inventario").click()
            page.wait_for_function('document.querySelector("#flujo-trabajos").textContent.includes("actualizar: completado")', timeout=15000)
            assert panel.db.execute("SELECT COUNT(*) FROM fotos").fetchone()[0] == 2
            # Comprobar geometría del diálogo y cierre en escritorio y móvil.
            capturas = Path(tempfile.gettempdir()) / "photo-manager-verificacion-flujo"
            capturas.mkdir(exist_ok=True)
            for nombre, ancho, alto in [("escritorio", 1400, 1000), ("movil", 390, 844)]:
                page.set_viewport_size({"width": ancho, "height": alto})
                page.screenshot(path=str(capturas / f"{nombre}.png"))
                assert page.locator("#flujo").evaluate("e => e.getBoundingClientRect().width <= innerWidth")
                for selector in ["#flujo-cerrar", "#flujo-listo"]:
                    assert page.locator(selector).evaluate("e => { const r=e.getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight; }")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#flujo-cerrar").click()
            assert not errores, errores
            browser.close()
            print(f"OK: conversión, respaldo, organización, Entrada, auditoría, inventario y móvil. Capturas: {capturas}")
    finally:
        server.should_exit = True
        thread.join(40)
        panel.db.close()
