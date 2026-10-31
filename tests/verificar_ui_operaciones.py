"""UI y API reales sobre fotos temporales: escritorio y móvil."""
import hashlib
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


def visible_en_ventana(page, selector):
    caja = page.locator(selector).bounding_box()
    assert caja and caja['x'] >= 0 and caja['y'] >= 0
    assert caja['x'] + caja['width'] <= page.viewport_size['width'] + 1
    assert caja['y'] + caja['height'] <= page.viewport_size['height'] + 1


capturas = Path(tempfile.gettempdir()) / 'photo-manager-verificacion-operaciones'
capturas.mkdir(exist_ok=True)

with tempfile.TemporaryDirectory() as tmp:
    raiz = Path(tmp)
    config.BIBLIOTECA = raiz / 'fotos'
    config.DATOS = raiz / 'datos'
    config.INDICE = config.DATOS / 'indice.db'
    config.MINIATURAS = config.DATOS / 'miniaturas'
    for carpeta in ('origen-a', 'origen-b', 'destino-vacio'):
        (config.BIBLIOTECA / carpeta).mkdir(parents=True)
    from pm import panel
    for i in range(16):
        carpeta = 'origen-a' if i % 2 == 0 else 'origen-b'
        archivo = config.BIBLIOTECA / carpeta / f'foto-{i:02}.jpg'
        Image.new('RGB', (120, 90), '#375377').save(archivo)
        panel.et.escribir(archivo, '-XMP-lr:HierarchicalSubject=personas|ana', '-XMP-photoshop:DateCreated=2020:05')
    originales = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in config.BIBLIOTECA.rglob('*.jpg')}
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    puerto = sock.getsockname()[1]
    servidor = uvicorn.Server(uvicorn.Config(panel.app, log_level='error'))
    hilo = threading.Thread(target=servidor.run, kwargs={'sockets': [sock]}, daemon=True)
    hilo.start()
    try:
        for _ in range(100):
            if servidor.started:
                break
            time.sleep(.05)
        assert servidor.started
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            errores = []
            page.on('pageerror', lambda e: errores.append(str(e)))
            url = f'http://127.0.0.1:{puerto}'
            page.goto(url)
            page.locator('.foto').first.wait_for()
            # Selección explícita de las 16 fotos mediante el control de día.
            page.locator('.dia button').first.click()
            page.locator('#mover-fotos').click()
            page.locator('#operaciones-destino option[value="destino-vacio"]').wait_for(state='attached')
            page.locator('#operaciones-destino').select_option('destino-vacio')
            page.locator('#operaciones-revisar').click()
            page.locator('#operaciones-preview').wait_for(state='visible')
            assert page.locator('.operacion-foto').count() == 16
            assert page.locator('#operaciones-lista h3').count() == 2
            assert page.locator('#operaciones-confirmar').is_disabled()
            page.locator('#operaciones-texto').fill('MOVER')
            assert page.locator('#operaciones-confirmar').is_disabled()
            page.locator('#operaciones-texto').fill('MOVER 16 FOTOS')
            assert page.locator('#operaciones-confirmar').is_enabled()
            # Cambiar destino invalida el texto y la revisión.
            page.locator('#operaciones-destino').select_option('')
            assert page.locator('#operaciones-texto').input_value() == ''
            assert page.locator('#operaciones-preview').is_hidden()
            page.locator('#operaciones-destino').select_option('destino-vacio')
            page.locator('#operaciones-revisar').click()
            page.locator('#operaciones-preview').wait_for(state='visible')
            visible_en_ventana(page, '#operaciones-cerrar')
            visible_en_ventana(page, '#operaciones-confirmar')
            page.locator('#operaciones .admin-cuerpo').evaluate('e => e.scrollTop = e.scrollHeight')
            page.screenshot(path=str(capturas / 'operaciones-desktop.png'))
            # Móvil, scroll, teclado y cancelación sin escritura.
            page.set_viewport_size({'width': 390, 'height': 844})
            visible_en_ventana(page, '#operaciones-cerrar')
            visible_en_ventana(page, '#operaciones-confirmar')
            assert page.locator('#operaciones').evaluate('e => e.scrollWidth <= e.clientWidth')
            page.locator('#operaciones-texto').fill('MOVER 16 FOTOS')
            entrada = page.locator('#operaciones-texto').bounding_box()
            assert entrada['y'] + entrada['height'] <= page.locator('#operaciones footer').bounding_box()['y']
            page.screenshot(path=str(capturas / 'operaciones-movil.png'))
            page.keyboard.press('Escape')
            assert page.locator('#operaciones').is_hidden()
            assert not list((config.BIBLIOTECA / 'destino-vacio').iterdir())
            page.set_viewport_size({'width': 1440, 'height': 900})
            page.locator('#mover-fotos').click()
            page.locator('#operaciones-destino option[value="destino-vacio"]').wait_for(state='attached')
            page.locator('#operaciones-destino').select_option('destino-vacio')
            page.locator('#operaciones-revisar').click()
            page.locator('#operaciones-preview').wait_for(state='visible')
            page.locator('#operaciones-texto').fill('MOVER 16 FOTOS')
            # Dos clics sin espera: el guard de ejecución impide duplicar la petición.
            contador = []
            page.on('request', lambda r: contador.append(r.post_data_json) if r.url.endswith('/api/operaciones/aplicar') else None)
            page.locator('#operaciones-confirmar').evaluate('e => { e.click(); e.click(); }')
            page.wait_for_function('document.querySelector("#operaciones-resultado").textContent.includes("16 completadas")')
            page.wait_for_function('!operacionOcupada')
            assert len(contador) == 1
            assert page.request.post(url + '/api/operaciones/aplicar', data=contador[0]).status == 409
            assert len(list((config.BIBLIOTECA / 'destino-vacio').glob('*.jpg'))) == 16
            for archivo in (config.BIBLIOTECA / 'destino-vacio').glob('*.jpg'):
                assert hashlib.sha256(archivo.read_bytes()).hexdigest() == originales[archivo.name]
            assert all(f['ruta'].startswith('destino-vacio/') for f in panel.fotos()['fotos'])
            page.locator('#operaciones-cancelar').click()
            assert page.locator('.foto').count() == 16
            page.locator('#detalle').wait_for(state='hidden')
            # API rechaza una frase equivocada y un token reutilizado.
            foto_id = panel.fotos()['fotos'][0]['id']
            preview = page.request.post(url + '/api/operaciones/preview', data={'ids': [foto_id], 'operacion': 'papelera'}).json()
            assert page.request.post(url + '/api/operaciones/aplicar', data={'token': preview['token'], 'texto': 'ELIMINAR'}).status == 400
            # Operación real de papelera desde UI, solo sobre una foto temporal.
            page.set_viewport_size({'width': 390, 'height': 844})
            page.locator('.foto').first.click()
            page.locator('#seleccion-acciones').click()
            page.locator('#papelera-fotos').click()
            page.locator('#operaciones-revisar').click()
            page.locator('#operaciones-preview').wait_for(state='visible')
            page.locator('#operaciones-texto').fill('ENVIAR 1 FOTO A LA PAPELERA')
            visible_en_ventana(page, '#operaciones-confirmar')
            page.locator('#operaciones-confirmar').click()
            page.wait_for_function('document.querySelector("#operaciones-resultado").textContent.includes("1 completadas")')
            page.wait_for_function('!operacionOcupada')
            assert len(panel.fotos()['fotos']) == 15
            assert page.locator('.foto').count() == 15
            assert not errores, errores
            browser.close()
        print('OK: API, mover sin alterar contenido/XMP, papelera Windows real, escritorio/móvil, cancelación y doble clic. Biblioteca temporal.')
    finally:
        servidor.should_exit = True
        hilo.join(10)
        panel.db.close()
