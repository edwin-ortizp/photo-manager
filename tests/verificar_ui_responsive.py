"""Galería y gestos contra 10 000 registros sintéticos; sin biblioteca personal."""
import io
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CAPTURAS = Path(tempfile.gettempdir()) / "photo-manager-responsive"
CAPTURAS.mkdir(exist_ok=True)

class Silencioso(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Silencioso, directory=str(ROOT / "pm/static")))
threading.Thread(target=server.serve_forever, daemon=True).start()
imagenes = []
for n, color in enumerate(["#35637a", "#ad704e", "#64835b", "#74618d", "#a15866", "#537d8d"]):
    img = Image.new("RGB", (600, 450), color)
    dibujo = ImageDraw.Draw(img)
    dibujo.ellipse((290, 40, 440, 190), fill="#efc681")
    dibujo.polygon([(0, 450), (220, 180), (400, 450)], fill="#263d49")
    dibujo.polygon([(210, 450), (460, 230), (600, 450)], fill="#41675e")
    b = io.BytesIO(); img.save(b, format="JPEG"); imagenes.append(b.getvalue())
fotos = [dict(id=n+1, ruta=f"2026/foto-{n:05}.jpg", fecha=f"2026-10-{30-(n//60)%28:02}T12:00:00", etiquetas=["tipo|foto", "personas|ana"], descripcion="Paisaje de prueba", camara="", gps="", caras=[]) for n in range(10000)]
peticiones = []
fallo = {"fotos": False, "original": False}

def responder(route):
    url = urlparse(route.request.url); query = parse_qs(url.query)
    assert route.request.method == "GET", "Esta prueba de navegación no debe escribir"
    peticiones.append(url.path)
    if url.path == "/api/conexion":
        datos = dict(habilitada=False, puerto=8642, urls=[])
    elif url.path == "/api/resumen":
        datos = dict(etiquetas=[dict(id="personas", total=10000), dict(id="personas|ana", total=10000)], carpetas=[dict(id="2026", total=10000)], bandejas=[dict(id="todas", nombre="Todas", total=10000), dict(id="entrada", nombre="Entrada", total=0)])
    elif url.path == "/api/fotos":
        if fallo["fotos"]:
            route.abort(); return
        offset = int(query.get("offset", [0])[0]); limite = int(query.get("limite", [300])[0])
        lista = [] if query.get("q") == ["vacio"] else fotos
        datos = dict(total=len(lista), fotos=lista[offset:offset+limite])
    elif url.path.startswith(("/api/miniatura/", "/api/original/")):
        if fallo["original"] and "/original/" in url.path:
            route.abort(); return
        route.fulfill(body=imagenes[int(url.path.split("/")[-1]) % len(imagenes)], content_type="image/jpeg"); return
    elif url.path.startswith("/api/foto/"):
        datos = dict(fotos[int(url.path.split("/")[-1])-1], exif={})
    else:
        raise AssertionError(url.path)
    route.fulfill(json=datos)

def nav(page, seccion):
    if page.viewport_size["width"] < 768:
        page.locator(f"#navegacion [data-seccion={seccion}]").click()

def pointer(page, selector, tipo, x, y, ident=1):
    page.locator(selector).dispatch_event(tipo, dict(pointerId=ident, pointerType="touch", clientX=x, clientY=y, button=0, bubbles=True))

def cerrar(page, selector):
    page.locator(selector).click()
    page.wait_for_timeout(80)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport=dict(width=390, height=844), has_touch=True, is_mobile=True, device_scale_factor=1)
        page = ctx.new_page(); page.set_default_timeout(8000)
        errores = []; page.on("pageerror", lambda e: errores.append(str(e)))
        page.route("**/api/**", responder)
        page.goto(f"http://127.0.0.1:{server.server_port}")
        page.locator(".foto").first.wait_for()
        for ancho, alto in [(360,800),(390,844),(480,800),(768,1024),(1024,768),(1280,850),(1440,900),(844,390),(390,420)]:
            page.set_viewport_size(dict(width=ancho,height=alto)); page.wait_for_timeout(100)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), ancho
            assert page.locator(".foto").count() < 180, (ancho, page.locator(".foto").count())
            if ancho < 768 and alto > ancho:
                assert page.locator(".grupo").first.evaluate("e => getComputedStyle(e).gridTemplateColumns.split(' ').length") == 3
            for seccion in ["explorar", "gestionar", "fotos"]:
                nav(page,seccion)
                if ancho in (390,1440) and alto > 500:
                    page.screenshot(path=str(CAPTURAS / f"{seccion}-{ancho}.png"))
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if ancho >= 768:
                assert page.locator("#navegacion").is_hidden()
                assert page.locator("#lateral").is_visible()
                assert page.locator("main").is_visible()
                assert page.locator("#lateral").bounding_box()["width"] == 250
                assert page.locator("#seccion-titulo").inner_text() == "Fotos"
                assert page.locator("#administrar-etiquetas").inner_text() == "Administrar"
                assert page.locator("#bandejas").is_visible()
                assert page.locator("#etiquetas").is_visible()
                assert page.locator(".foto .marcas").first.is_visible()
                assert page.locator("#abrir-auditoria").evaluate("e=>e.getBoundingClientRect().height<48")
                page.locator(".foto").first.click()
                page.locator("#detalle").wait_for()
                assert page.locator("#seleccion-barra").is_hidden()
                assert page.locator("#detalle").bounding_box()["width"] == 360
                if ancho >= 1100:
                    assert page.locator("main").bounding_box()["x"] + page.locator("main").bounding_box()["width"] <= page.locator("#detalle").bounding_box()["x"] + 1
                page.screenshot(path=str(CAPTURAS / f"pc-detalle-{ancho}.png"))
                cerrar(page,"#sel-limpiar")
                page.locator("#detalle").wait_for(state="hidden")
            page.screenshot(path=str(CAPTURAS / f"fotos-{ancho}-{alto}.png"))
        page.set_viewport_size(dict(width=390,height=844)); page.wait_for_timeout(100)
        nav(page,"explorar"); page.locator("#buscar-carpetas").fill("no-existe")
        assert page.locator("#carpetas li").first.is_hidden()
        page.locator("#buscar-carpetas").fill("2026"); page.locator("#carpetas li").first.click()
        assert page.locator("main").is_visible()
        nav(page,"explorar"); page.locator("#filtro-etiquetas").fill("ana")
        page.locator(".etiqueta-hijos button").click(); page.locator(".foto").first.wait_for()
        page.touchscreen.tap(60,240)
        # Usar el centro real, independientemente del encabezado de fecha.
        if page.locator("#visor").is_hidden():
            caja = page.locator(".foto").first.bounding_box(); page.touchscreen.tap(caja['x']+20,caja['y']+20)
        page.locator("#visor").wait_for()
        assert page.evaluate("ui.visorId") == 1
        page.wait_for_function("!document.querySelector('#visor-carga').textContent")
        pointer(page,"#visor-superficie","pointerdown",300,400)
        pointer(page,"#visor-superficie","pointermove",80,405)
        pointer(page,"#visor-superficie","pointerup",80,405)
        page.wait_for_function("ui.visorId === 2")
        # Doble toque y pan con zoom no cambian la foto.
        for _ in range(2):
            pointer(page,"#visor-superficie","pointerdown",180,300)
            pointer(page,"#visor-superficie","pointerup",180,300)
        assert page.evaluate("ui.zoom") > 1
        pointer(page,"#visor-superficie","pointerdown",300,400)
        pointer(page,"#visor-superficie","pointermove",80,400)
        pointer(page,"#visor-superficie","pointerup",80,400)
        assert page.evaluate("ui.visorId") == 2
        # Pellizco sintético de dos punteros.
        pointer(page,"#visor-superficie","pointerdown",120,350,1)
        pointer(page,"#visor-superficie","pointerdown",220,350,2)
        pointer(page,"#visor-superficie","pointermove",280,350,2)
        pointer(page,"#visor-superficie","pointerup",280,350,2)
        pointer(page,"#visor-superficie","pointerup",120,350,1)
        assert page.evaluate("ui.zoom") > 2.5
        page.screenshot(path=str(CAPTURAS / "visor.png"))
        page.locator("#visor-detalle").click(); page.locator("#detalle").wait_for()
        page.locator("#detalle-ampliar").click()
        assert page.locator("#detalle").evaluate("e => e.getBoundingClientRect().height <= innerHeight")
        page.locator("#editar-datos").click(); page.locator("#editor-datos").wait_for()
        for selector in ["#editor-cerrar", "#editor-listo"]:
            assert page.locator(selector).evaluate("e => {const r=e.getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight}")
        # Atrás durante una escritura respeta la guarda, sin ejecutar ningún POST.
        page.evaluate("datosOcupado=true")
        page.go_back(); page.wait_for_timeout(120)
        assert page.locator("#editor-datos").is_visible()
        page.evaluate("datosOcupado=false")
        page.go_back(); page.locator("#editor-datos").wait_for(state="hidden")
        page.locator("#detalle").wait_for()
        page.go_back(); page.locator("#detalle").wait_for(state="hidden")
        assert page.locator("#visor").is_visible()
        page.go_back(); page.locator("#visor").wait_for(state="hidden")
        page.go_forward(); page.locator("#visor").wait_for()
        page.go_back(); page.locator("#visor").wait_for(state="hidden")
        # Long press does not open the editor; movement cancels it.
        celda = page.locator(".foto").first
        celda.dispatch_event("pointerdown",dict(pointerType="touch",pointerId=1,clientX=30,clientY=250))
        page.wait_for_function("estado.sel.size === 1")
        celda.dispatch_event("pointerup",dict(pointerType="touch",pointerId=1,clientX=30,clientY=250))
        celda.dispatch_event("click",dict(pointerType="touch"))
        assert page.evaluate("estado.sel.size") == 1
        assert page.locator("#detalle").is_hidden()
        segunda = page.locator(".foto").nth(1).bounding_box(); page.touchscreen.tap(segunda['x']+20,segunda['y']+20)
        assert page.evaluate("estado.sel.size") == 2
        page.locator("#seleccion-acciones").click(); page.locator("#detalle").wait_for()
        page.screenshot(path=str(CAPTURAS / "detalle.png"))
        page.keyboard.press("Escape"); page.locator("#detalle").wait_for(state="hidden")
        cerrar(page,"#seleccion-cancelar")
        assert page.evaluate("estado.sel.size") == 0
        celda = page.locator(".foto").first
        celda.dispatch_event("pointerdown",dict(pointerType="touch",pointerId=1,clientX=30,clientY=250))
        celda.dispatch_event("pointermove",dict(pointerType="touch",pointerId=1,clientX=30,clientY=290))
        page.wait_for_timeout(480)
        celda.dispatch_event("pointercancel",dict(pointerType="touch",pointerId=1))
        assert page.evaluate("estado.sel.size") == 0
        # Cargar 10 000 registros, recorrer inicio/medio/final y preservar selección.
        page.evaluate("async () => { while (estado.fotos.length < estado.total) await cargarMas(); }")
        assert page.evaluate("estado.fotos.length") == 10000
        for posicion in [0, .25, .5, 1, .5, 0]:
            page.evaluate("p => { const m=document.querySelector('main'); m.scrollTop=(m.scrollHeight-m.clientHeight)*p; }", posicion)
            page.wait_for_timeout(100)
            assert 0 < page.locator(".foto").count() < 180
            assert abs(page.locator("#rejilla").evaluate("e=>e.scrollHeight") - page.evaluate("ui.alto")) < 80
        page.evaluate("document.querySelector('main').scrollTop=2400"); page.wait_for_timeout(100)
        scroll = page.locator("main").evaluate("e=>e.scrollTop")
        caja = page.locator(".foto").evaluate_all("els => { const e=els.find(e=>{const r=e.getBoundingClientRect(); return r.top>150 && r.bottom<700}); const r=e.getBoundingClientRect(); return {x:r.x,y:r.y}; }")
        scroll = page.locator("main").evaluate("e=>e.scrollTop")
        page.touchscreen.tap(caja['x']+20,caja['y']+20)
        page.locator("#visor").wait_for(); page.go_back(); page.locator("#visor").wait_for(state="hidden")
        assert abs(page.locator("main").evaluate("e=>e.scrollTop") - scroll) < 2
        # Frontera de paginación del visor, y error con reintento explícito.
        page.evaluate("() => { estado.fotos=estado.fotos.slice(0,300); reconstruirCronologia(); mostrarVisor(299); }")
        page.evaluate("navegarVisor(1)"); page.wait_for_function("ui.visorId===301")
        fallo["original"] = True
        page.evaluate("mostrarVisor(302)"); page.locator("#visor-reintentar").wait_for()
        fallo["original"] = False
        page.locator("#visor-reintentar").click(); page.wait_for_function("!document.querySelector('#visor-carga').textContent")
        page.go_back(); page.locator("#visor").wait_for(state="hidden")
        fallo["fotos"] = True
        page.locator("#buscar").fill("fallo"); page.locator("#reintentar-galeria").wait_for()
        fallo["fotos"] = False
        page.locator("#reintentar-galeria").click(); page.locator(".foto").first.wait_for()
        page.locator("#buscar").fill("vacio"); page.wait_for_function("document.querySelector('#estado-galeria').textContent.includes('No hay fotos')")
        # Teclado, selección de escritorio, foco y movimiento reducido.
        page.set_viewport_size(dict(width=1440,height=900))
        page.locator("#buscar").fill(""); page.locator(".foto").first.wait_for()
        page.locator(".foto").first.focus(); page.keyboard.press("Enter")
        assert page.evaluate("estado.sel.size") == 1
        page.locator(".foto").nth(1).click(modifiers=["Control"])
        assert page.evaluate("estado.sel.size") == 2
        page.locator(".foto").first.dblclick(); page.locator("#visor").wait_for()
        assert not page.locator("#visor").evaluate("e=>e.inert")
        page.keyboard.press("ArrowRight"); page.wait_for_function("ui.visorId===2")
        page.evaluate("document.querySelector('#visor').classList.add('sin-controles')")
        page.keyboard.press("Tab")
        assert not page.locator("#visor").evaluate("e=>e.classList.contains('sin-controles')")
        page.keyboard.press("Escape"); page.locator("#visor").wait_for(state="hidden")
        page.emulate_media(reduced_motion="reduce")
        assert page.locator(".visor-controles").first.evaluate("e=>getComputedStyle(e).transitionDuration") == "0s"
        assert page.locator("#navegacion").is_hidden()
        # Cambiar de móvil a PC desde Explorar o Gestionar nunca oculta el sidebar o la galería.
        for seccion in ["explorar", "gestionar"]:
            page.set_viewport_size(dict(width=390,height=844)); page.wait_for_timeout(80)
            nav(page,seccion)
            page.set_viewport_size(dict(width=1280,height=850)); page.wait_for_timeout(80)
            assert page.locator("#lateral").is_visible() and page.locator("main").is_visible()
            assert page.locator("#navegacion").is_hidden()
        assert not errores, errores
        assert not [x for x in peticiones if '/aplicar' in x]
        browser.close()
        print(f"OK: responsive, navegación, gestos, selección, historial, 10000 registros, paginación, errores y reintento. Capturas: {CAPTURAS}")
finally:
    server.shutdown(); server.server_close()
