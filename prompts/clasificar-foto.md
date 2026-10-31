# Clasificar fotos personales

Vas a clasificar fotos de la biblioteca personal de Edwin (Colombia). Para cada foto
del lote devuelves un objeto JSON con su tipo, escenas, número de personas y una
descripción corta. **No inventes**: si dudas, elige la opción más general.

## Entrada

Un archivo JSON con una lista de fotos:

```json
[{"id": 3364, "imagen": "C:/.../para-ia/3364.jpg", "fecha": "2026-05-27T13:05:40",
  "camara": "SM-F936B", "sugerencias": ["vehiculos"], "personas_conocidas": ["yo"]}]
```

- `imagen`: ábrela con la herramienta Read (JPEG de 1024 px).
- `camara`: vacía suele indicar captura, meme o imagen descargada.
- `sugerencias`: pistas de un detector de objetos antiguo y poco fiable. Confírmalas solo si se ven claramente y son el tema de la foto.
- `personas_conocidas`: nombres ya etiquetados. Solo como contexto; tú no identificas a nadie.

## Taxonomía (usa exactamente estos valores, en kebab-case)

**tipo** (uno):
- `foto`: tomada con cámara de algo del mundo real.
- `captura`: captura de pantalla de una app, web, chat o juego.
- `meme`: imagen humorística con texto superpuesto o formato de meme, sticker o imagen viral.
- `documento`: papel o pantalla con texto como tema principal: recibo, factura, cédula, formulario, tablero, apuntes, presentación.
- `otro`: ilustración, wallpaper o imagen descargada que no encaja en lo anterior.

**escenas** (0 a 3, solo para `foto`; de esta lista):
`retrato`, `selfie`, `grupo`, `familia`, `celebracion`, `comida`, `mascotas`, `animales`,
`naturaleza`, `paisaje`, `playa`, `ciudad`, `viaje`, `vehiculos`, `deporte`, `hogar`,
`trabajo`, `estudio`, `compras`, `evento`, `arte`, `noche`.

- `vehiculos` solo si el vehículo es el protagonista (no un carro de fondo en la calle).
- `mascotas` para perros y gatos domésticos; `animales` para otros.
- `grupo` si hay 3 o más personas posando juntas.

**personas**: número de personas con la cara visible y reconocible (0 si no hay, o si son lejanas o de espaldas). Máximo 20.

**descripcion**: una frase en español, de 15 palabras como máximo, concreta y sin adornos. Ejemplo: "Dos personas sonriendo frente a un pastel de cumpleaños en una sala".

**sugerencias_confirmadas**: el subconjunto de `sugerencias` que sí es tema de la foto.

## Salida

Responde **solo** con un arreglo JSON válido, sin texto antes ni después ni bloques de código:

```json
[{"id": 3364, "tipo": "foto", "escenas": ["mascotas", "hogar"], "personas": 0,
  "descripcion": "Gato gris durmiendo sobre un sofá", "sugerencias_confirmadas": ["mascotas"]}]
```

Incluye un objeto por cada foto del lote, en el mismo orden. Si una imagen no se puede abrir, devuelve `{"id": N, "error": "motivo"}`.
