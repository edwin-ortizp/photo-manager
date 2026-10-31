---
name: clasificar-fotos
description: Clasifica un lote de fotos (tipo, escenas, personas, descripción) y responde solo con JSON. La invoca `python fotos.py clasificar` pasando la ruta de un lote JSON; úsala cuando pidan clasificar o etiquetar fotos con IA.
allowed-tools: Read
---

# Clasificar fotos

Argumento: ruta a un archivo de lote JSON (por ejemplo `datos/para-ia/lote-0001.json`).

1. Lee las instrucciones completas en `prompts/clasificar-foto.md` (relativo a la raíz del proyecto) y síguelas al pie de la letra.
2. Lee el archivo de lote.
3. Abre cada `imagen` del lote con Read y clasifícala.
4. Tu respuesta final debe ser **únicamente** el arreglo JSON descrito en el prompt: sin explicaciones, sin bloques de código y sin texto adicional. El script `fotos.py` la procesa automáticamente.

No escribas ni modifiques archivos: solo lees y respondes.
