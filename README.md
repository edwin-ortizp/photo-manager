# photo-manager

Gestor de la biblioteca de fotos en `C:\Users\edwin\Sync\fotos` (sincronizada con Syncthing).
Las fotos son la fuente de verdad: todas las etiquetas viven en el XMP de cada archivo.
Este proyecto solo guarda un índice y las miniaturas en `datos/`, y no se sincroniza.

## Estructura de la biblioteca

```
fotos/
  entrada/      fotos nuevas (convertir-avif.ps1 las deja aquí)
  2011/ … 2026/ una carpeta por año de toma: 2025-06-28-154951.avif
  sin-fecha/
  capturas/  memes/  documentos/
```

## Etiquetas (kebab-case, jerárquicas con `|`)

| Rama | Ejemplo | Quién la pone |
|---|---|---|
| `tipo|` | `tipo|foto`, `tipo|captura` | IA |
| `escena|` | `escena|mascotas` | IA o tú (confirmando sugerencias) |
| `personas|` | `personas|yo`, `personas|camila-mateus`, `personas|desconocido` | tú |
| `mascotas|`, `lugar|`, … | `mascotas|simon` | tú / reglas |
| `_ia|` | `_ia|v1`, `_ia|personas|2` | IA (interna, no se ve en galerías) |
| `_sugerencias|` | `_sugerencias|vehiculos` | antiguo detector de digiKam, por confirmar |

## Comandos

```powershell
python fotos.py organizar [--aplicar]       # mueve entrada/ y sueltas a <año>/ con nombre por fecha
python fotos.py deshacer datos/movimientos-….csv
python fotos.py indexar [--miniaturas]
python fotos.py clasificar --limite 200     # Claude Haiku vía skill clasificar-fotos
python fotos.py panel                      # ventana de escritorio y acceso por red local
python fotos.py panel --navegador           # alternativa en una pestaña del navegador
python fotos.py panel --sin-navegador       # solo servidor (Ctrl+C para cerrar)
python fotos.py panel --host 127.0.0.1     # solo este PC
```

Flujo desde la interfaz: copiar las fotos a `entrada/` → **Actualizar inventario** →
**Entrada** → auditar, convertir y editar datos → **Organizar selección**.
Los scripts externos y comandos anteriores siguen disponibles.

## Entrada, auditoría y conversión AVIF

**Entrada** incluye todas las imágenes de `entrada/` y sus subcarpetas, también
TIFF. Las miniaturas muestran pendientes independientes: fecha, tipo, clasificación,
personas cuando existe evidencia y revisión técnica. Una foto AVIF puede seguir
pendiente de organización; los pendientes no impiden moverla.

**Actualizar inventario** detecta fotos nuevas, modificadas o retiradas sin reiniciar.
**Auditoría y trabajos** permite auditar toda la biblioteca; **Auditar selección**
revisa exclusivamente las fotos seleccionadas. La auditoría decodifica las imágenes,
comprueba formato real, dimensiones, profundidad y muestreo AVIF. Separa errores,
advertencias y valores desconocidos, además de pendientes de organización y años de
carpeta incoherentes con la fecha efectiva. Los resultados técnicos se guardan en
el índice local y se invalidan cuando cambia el archivo o la versión de reglas.
La auditoría no escribe en las fotos ni ejecuta la IA.

Para **Convertir / corregir AVIF**, selecciona las fotos e indica una ruta absoluta
para los originales en el **PC que ejecuta el gestor**, también desde el celular.
En la ventana de escritorio puedes usar el selector nativo. El destino debe estar
fuera de la biblioteca sincronizada y no contenerla; el gestor recuerda el último
destino confirmado. La estructura relativa se conserva en el respaldo.

La conversión usa ImageMagick (`magick` en PATH) y ExifTool. El perfil inicial es
máximo 3840 px por lado, calidad 75, 8 bits y 4:2:0; no amplía fotos pequeñas.
Omite AVIF conformes y bloquea archivos de múltiples cuadros. La calidad de una
conversión anterior no se puede deducir del archivo y no forma parte de la auditoría.
Estos controles técnicos no sustituyen una prueba en un modelo de celular concreto.

Antes de aplicar se muestran las rutas finales y del respaldo, y debes escribir
la frase indicada. Las revisiones vencen en diez minutos y se usan una sola vez.
El resultado se genera temporalmente en la carpeta de origen y se verifica junto
con las fechas, etiquetas, descripción, GPS y metadatos XMP/IPTC. Las regiones MWG
normalizadas se adaptan a la orientación y dimensiones; los formatos de regiones
incompatibles bloquean la operación. Se copia el original al respaldo y se verifica
su SHA-256 antes de sustituirlo. Nunca se sobrescribe un respaldo existente.
Los AVIF permanecen en la carpeta de origen hasta que decidas organizarlos.

Si ExifTool no reconoce las MakerNotes de la cámara y devuelve ese error menor,
se reintenta la escritura únicamente sobre el AVIF temporal. Las MakerNotes se
comparan byte por byte con las del original antes de continuar; si difieren, se
detiene la conversión. La excepción se informa como advertencia en el resultado
del archivo. Los demás errores siguen deteniendo el lote.

**Organizar selección** sugiere `capturas/`, `memes/` o `documentos/` según el tipo;
para el resto propone el año de la fecha efectiva o `sin-fecha/`. Respeta la fecha
manual y las fechas parciales sin inventar día u hora. Puedes editar cada carpeta
de destino, incluidas subcarpetas; las que falten se crean al confirmar. Conserva los
nombres, no modifica metadatos y bloquea conflictos de nombres. La edición de fecha
y personas sigue disponible en el detalle. Mover una foto fuera de `entrada/` la
retira de esa bandeja, aunque tenga pendientes.

Los trabajos se ejecutan en segundo plano, serializando las escrituras. Puedes
cerrar el diálogo y consultar el progreso en **Auditoría y trabajos**. Cancelar
termina el archivo actual y deja los restantes pendientes. Al primer fallo se detiene
el lote. No se reintenta ni se reanuda automáticamente después de reiniciar:
los trabajos activos se marcan como interrumpidos. Cerrar la aplicación espera al
archivo actual; la actualización del inventario termina su escaneo en curso.
Mientras hay un trabajo, las otras operaciones de escritura sobre fotos se rechazan.

Los resúmenes y bitácoras quedan en `datos/trabajos/`. Si una interrupción deja
archivos ya modificados, revisa las rutas registradas y actualiza el inventario.
Para recuperar un original, usa la ruta del respaldo que muestra el trabajo y
cópialo manualmente a la biblioteca, resolviendo antes cualquier conflicto con el
AVIF. Un respaldo fallido puede quedar incompleto: no lo uses para recuperar sin
verificarlo; el original permanece en la biblioteca. No existe reversión automática
de lotes ni transacción entre archivos. Syncthing puede propagar los cambios.

Validación aislada: `python -m unittest discover -s tests -v` y
`python tests/verificar_ui_flujo.py` (Chromium de Playwright). Las pruebas usan fotos
sintéticas temporales y herramientas reales; no usan la biblioteca personal.

## Ventana de escritorio (Windows)

El panel abre una ventana propia **Photo Manager**, redimensionable y sin pestañas.
Requiere `python -m pip install pywebview` y **Microsoft Edge WebView2 Runtime**
(https://developer.microsoft.com/microsoft-edge/webview2/). La ventana se ajusta
al tamaño de la pantalla, hasta 1280 × 850. No requiere instalar un ejecutable.

Al cerrar la ventana se detiene el servidor, esperando las peticiones en curso;
el acceso desde el celular termina también. Mientras esté abierta, el acceso
por red local funciona igual que antes. `--navegador` conserva el modo anterior,
con servidor activo hasta Ctrl+C. `--sin-navegador` inicia únicamente el servidor;
no puede combinarse con `--navegador`. Ambos modos funcionan sin pywebview.
Si el puerto está ocupado, se informa sin detener el proceso que lo está usando.

Verificación de la ventana real: `python tests/verificar_escritorio.py`. Abre y
cierra WebView2 automáticamente con una foto temporal, comprueba filtros,
diálogos, acceso LAN desde el PC y liberación del puerto al cerrar.

La IA se configura en `prompts/clasificar-foto.md` (taxonomía y formato) y en `.claude/skills/clasificar-fotos/SKILL.md`.

## Administrar etiquetas desde el panel

Las bandejas **Sin estilo**, **Sin momento**, **Sin tema** y **Sin persona** muestran
las fotos que no tienen etiquetas de la rama correspondiente. Las subetiquetas
también cuentan como dato asignado. **Sin persona** es independiente de
**Personas sin nombre**, que conserva el criterio de personas detectadas pendientes
de identificar. Los conteos se actualizan al asignar o quitar etiquetas.

El sidebar muestra grupos desplegables: pulsa `personas` para ver todas las fotos
con etiquetas de esa rama; la flecha despliega sus etiquetas. Los conteos de los
grupos no duplican fotos. Las etiquetas internas quedan en una sección aparte.

En **Etiquetas → Administrar** puedes crear etiquetas o grupos vacíos y renombrar
etiquetas existentes. Usa `grupo|etiqueta` para organizar la jerarquía o cambiar de
grupo. Antes de renombrar se muestra el nombre normalizado y cuántas fotos se
modificarán; debes confirmarlo. Se actualizan también las subetiquetas y los
metadatos XMP de las fotos, conservando las asociaciones. Un destino existente se
rechaza para evitar fusiones accidentales.

Las etiquetas vacías se conservan en `datos/etiquetas.json` (guarda una copia si
reconstruyes el índice). Las asignaciones siguen viviendo en los archivos.
Un renombrado masivo no es atómico entre archivos: si falla, se detiene e informa
del avance parcial; las escrituras realizadas se vuelven a indexar.

Tras actualizar el código, reinicia el panel y recarga el navegador.
Verificación aislada: `python -m unittest discover -s tests -v` y, con Playwright
Chromium instalado, `python tests/verificar_ui.py`. No usan la biblioteca personal.

## Celular y edición de datos

El panel inicia con acceso por red local. **Abrir en el celular** muestra las URL
de las interfaces IPv4 del PC con el puerto configurado y permite copiarlas.
Conecta ambos dispositivos a la misma red. Si no conecta, revisa el firewall o el
aislamiento Wi-Fi; la aplicación no cambia esas configuraciones. El acceso desde
el celular permite también editar y no incorpora autenticación. Usa
`--host 127.0.0.1` si quieres restringirlo al equipo.

La tipografía Nunito se sirve localmente desde `pm/static/fonts/`, con su licencia
OFL; la interfaz no depende de servicios de fuentes externos.

El detalle separa **Tipo**, **Lugar**, **Personas**, **Mascotas**, **Vehículos**,
**Estilo**, **Momento** y **Tema**, además de **Fecha**. Cada grupo muestra sus
etiquetas asignadas, búsqueda y botones basados en el catálogo del usuario,
incluidas las etiquetas recién creadas sin fotos. Puedes asignar con Enter o el
botón `+`. Mostrar un grupo vacío no crea etiquetas. Las etiquetas de `escena`
y cualquier otra rama se conservan en **Otras etiquetas** hasta que las
reorganices desde el administrador. Elegir un tipo sustituye los
tipos anteriores sin mover el archivo. Selfie y las demás escenas permanecen como
características opcionales. Las fotos sin tipo continúan disponibles y pendientes.

**Editar datos** funciona con una foto o una selección. Activa únicamente los
campos que quieras cambiar, revisa el resumen y confirma. La fecha admite solo
año, mes y año, día completo o fecha con hora. Se guarda en
`XMP-photoshop:DateCreated` y tiene prioridad para mostrar y ordenar, conservando
el EXIF original. Las fechas parciales no inventan día u hora. Agregar un lugar
conserva los otros lugares y las coordenadas GPS; los chips permiten quitar una
etiqueta de forma explícita.

El primer arranque vuelve a leer los metadatos para actualizar el índice de
fechas (versión SQLite 1), sin escribir en las fotos ni cambiar sus rutas. Las
operaciones por lote verifican cada escritura, refrescan el índice e informan
los archivos completados y los errores; no son una transacción entre archivos.
Formatos que ExifTool no pueda escribir se muestran como errores, sin anunciar
éxito. La edición manual no mueve ni renombra fotos.

Verificación adicional: `python tests/verificar_ui_datos.py` usa una biblioteca
temporal con API y ExifTool reales, revisa escritorio y móvil y comprueba acceso
HTTP por las interfaces LAN desde el mismo PC. Esto no sustituye la prueba con un
celular físico.


## Mover fotos y enviar a la papelera

Selecciona una foto o un conjunto de fotos y usa **Mover de carpeta** o
**Enviar a la papelera** en el detalle. Solo se afectan los archivos seleccionados;
los filtros no incluyen automáticamente más fotos. Mover conserva el nombre y
permite elegir carpetas físicas existentes de la biblioteca, incluidas las vacías.
No crea carpetas, no sobrescribe archivos ni modifica sus metadatos.

La revisión muestra todas las fotos, cantidad, miniaturas, rutas de origen y
destino. Para continuar debes escribir exactamente la frase indicada, por ejemplo
`MOVER 12 FOTOS` o `ENVIAR 1 FOTO A LA PAPELERA`. Cambiar destino o selección
invalida la revisión. Cada revisión vence a los diez minutos y se usa una sola vez;
el servidor vuelve a comprobar los archivos antes de operar.

La papelera es la de **Windows en el PC que ejecuta el gestor**, también si operas
desde el celular. La recuperación se hace desde Windows. No hay borrado definitivo
ni alternativa de borrado si la papelera falla. Instala la dependencia en ese PC:

```powershell
python -m pip install "Send2Trash>=2.1.0"
```

Estas operaciones modifican archivos reales: **Syncthing puede propagar los
movimientos y eliminaciones a otros dispositivos**. Las carpetas ocultas y los
enlaces o junctions no se ofrecen como destinos. Los movimientos requieren Windows.

Al primer fallo se detiene el lote y se muestran las fotos completadas, el error
y las pendientes. No se reintenta automáticamente. Se actualiza el índice por
archivo y se escribe una bitácora en `datos/operaciones-*.jsonl`. Si el archivo se
modificó pero falló la actualización del índice, el resultado lo indica: revisa el
disco y vuelve a indexar antes de continuar. No es una transacción entre archivos.

Verificación aislada: `python -m unittest discover -s tests -v` y
`python tests/verificar_ui_operaciones.py` (requiere Playwright Chromium).
La prueba de papelera real usa exclusivamente archivos temporales identificados
como pruebas; pueden quedar en la papelera de Windows. No usa fotos personales.
Las capturas con fotos sintéticas quedan en `%TEMP%/photo-manager-verificacion-operaciones/`.
Reinicia el panel y recarga la interfaz después de actualizar el código.


## Galería adaptativa para Android

La web comparte la biblioteca del PC. En el celular, **Fotos** muestra la cronología,
**Explorar** permite buscar carpetas y etiquetas y **Gestionar** reúne Entrada,
bandejas pendientes, inventario, auditoría, trabajos y administración de etiquetas.
La navegación nueva se limita a teléfonos de menos de 768 px. Desde 768 px se conserva
la interfaz de PC: sidebar de 250 px, galería central y detalle de 360 px,
superpuesto en ventanas de menos de 1100 px. Los controles de PC conservan su tamaño compacto.

En pantallas táctiles, toca una foto para abrirla; mantén pulsado 450 ms para seleccionar.
Los siguientes toques agregan o quitan fotos. **Seleccionar cargadas** afecta únicamente
las fotos de esa fecha ya cargadas. **Datos y acciones** abre el detalle ampliable.
El visor permite deslizar, pellizcar y usar doble toque para zoom; con zoom, arrastrar
mueve la imagen. Un toque muestra u oculta los controles. Atrás cierra superficies
conservando la posición; las operaciones mantienen sus confirmaciones sobre archivos del PC.
En escritorio se conservan clic para seleccionar, Ctrl/Cmd, Shift, doble clic y teclado.

La cronología virtualiza filas para mantener acotado el DOM. Las imágenes se muestran
primero como miniaturas grandes y después como originales. Los errores ofrecen un
reintento explícito; las escrituras nunca se reintentan automáticamente.

Verificación aislada adicional: `python tests/verificar_ui_responsive.py` usa 10 000
registros ficticios y miniaturas sintéticas, cubre móvil/tablet/escritorio, gestos,
selección, historial, zoom, paginación, errores y teclado. Sus capturas quedan en
`%TEMP%/photo-manager-responsive`. También se verificó la ventana real WebView2.
La emulación y WebView2 no sustituyen una prueba en Chrome de Android físico por LAN;
esa comprobación queda pendiente. No se incluye PWA ni acceso a fotos locales del teléfono.
