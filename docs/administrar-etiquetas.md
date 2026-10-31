# Agrupar y administrar etiquetas

## Historia de usuario
- **Como** usuario de la biblioteca de fotos.
- **Quiero** navegar por grupos y crear o renombrar etiquetas.
- **Para** encontrar todas las fotos de una categoría y mantener organizado el catálogo.

## Contexto
Las etiquetas existentes usan rutas como `personas|yo`, pero el sidebar mostraba una lista plana. Las etiquetas asignadas se conservan en los metadatos XMP de los archivos.

## Criterios de aceptación
- [x] Se debe mostrar una jerarquía desplegable con selección de grupos completos.
- [x] El conteo de cada grupo debe contar cada foto una sola vez.
- [x] Se deben separar las etiquetas internas de las categorías habituales.
- [x] Se debe permitir crear etiquetas sin asignarlas a una foto.
- [x] Se debe permitir renombrar una etiqueta o cambiar su grupo mediante una nueva ruta.
- [x] Se debe revisar el nombre normalizado y el número de fotos antes de confirmar un renombrado.
- [x] Se deben conservar las asociaciones y actualizar las subetiquetas y campos XMP compatibles.
- [x] Se debe bloquear un destino existente para evitar fusiones accidentales.

## Detalles técnicos
El catálogo de etiquetas vacías se guarda en `datos/etiquetas.json`; debe conservarse junto al índice. Las asignaciones continúan teniendo como fuente de verdad los archivos. Los cambios masivos verifican cada escritura y actualizan el índice; no son una transacción entre archivos. Un fallo interrumpe el proceso e informa del avance parcial.

## Definition of Done
- [x] Pruebas automatizadas con biblioteca temporal satisfactorias.
- [x] Verificación de interfaz en navegador, escritorio y modal móvil.
- [ ] Reiniciar el panel para cargar las nuevas rutas.
