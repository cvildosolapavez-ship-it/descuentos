# Descuentos del Día

App de descuentos bancarios en Chile que se actualiza sola todos los días.

- `index.html`: la app. Lee los descuentos desde `descuentos.json`.
- `descuentos.json`: los datos. Lo actualiza GitHub cada mañana.
- `scraper.py`: lee los sitios de beneficios de los bancos.
- `.github/workflows/actualizar.yml`: tarea diaria (07:00 hora de Chile).
- `manifest.json` e íconos: para instalarla en el iPhone como app.

## Puesta en marcha (una sola vez, unos 15 minutos)

1. **Crea una cuenta** en github.com (gratis).
2. **Crea un repositorio**: botón **New** → nombre `descuentos` → **Public** → **Create repository**.
3. **Sube los archivos**: en el repositorio vacío, toca **uploading an existing file** y arrastra
   todo el contenido de esta carpeta, incluida la carpeta `.github`. Luego **Commit changes**.
   - En Mac, la carpeta `.github` está oculta: en el Finder presiona `Cmd + Shift + .` para verla.
   - Revisa que aparezca `.github/workflows/actualizar.yml`. Si no subió, usa
     **Add file → Create new file**, escribe ese nombre exacto y pega el contenido del archivo.
4. **Permite que la tarea guarde cambios**: **Settings → Actions → General →
   Workflow permissions → Read and write permissions → Save**.
5. **Publica la app**: **Settings → Pages → Source: Deploy from a branch →
   Branch: main, carpeta / (root) → Save**. En 1–2 minutos queda en
   `https://TU-USUARIO.github.io/descuentos/`.
6. **Primera actualización**: pestaña **Actions → Actualizar descuentos → Run workflow**.
   Al terminar, abre el paso "Leer descuentos de los bancos" para ver cuántos descuentos
   encontró en cada banco.
7. **En el iPhone**: abre el link en Safari → **Compartir → Agregar a pantalla de inicio**.

## Cómo se protegen los datos

- Los descuentos con `"origen": "manual"` nunca se borran: son los que cargas a mano.
- Si un banco falla o devuelve 0 resultados, se conservan los que ya tenía.

## Agregar descuentos a mano

En GitHub abre `descuentos.json`, toca el lápiz y agrega un bloque como este:

```json
{
  "shop": "Nombre del comercio",
  "cat": "comida",
  "bank": "scotia",
  "pct": 30,
  "days": [1, 3],
  "cond": "Tarjeta de crédito, tope $10.000",
  "upTo": false,
  "perLitre": false,
  "loc": "",
  "vig": "Hasta 31 oct. 2026",
  "url": "https://link-del-beneficio",
  "origen": "manual"
}
```

- `days`: 0 = domingo, 1 = lunes … 6 = sábado.
- `cat`: comida, entretenimiento, belleza, moda, supermercado, viajes, salud, bencina, otros.
- `bank`: bchile, estado, santander, bci, scotia, itau, falabella, security, ripley.
- `perLitre: true` para descuentos de bencina en pesos por litro (ej. `"pct": 100` = $100 x litro).

## Si un banco siempre devuelve 0

Su sitio cambió o la URL no es la correcta. Abre su página de beneficios, haz clic derecho
sobre una tarjeta de descuento → **Inspeccionar**, y ajusta `url` y `selector` de ese banco
en la sección `BANCOS` de `scraper.py`.

## Banco de Chile (exportación manual, una vez al mes)

El sitio del Banco de Chile bloquea a los servidores de GitHub, así que sus beneficios
se exportan desde tu navegador:

1. Abre https://sitiospublicos.bancochile.cl/personas/beneficios en Chrome o Edge.
2. Presiona F12 y entra a la pestaña **Console**. Si Chrome pide confirmar, escribe `allow pasting` y Enter.
3. Pega el contenido de `exportar-bchile.js` y presiona Enter. Se descarga `bchile-importado.json`.
4. Súbelo al repositorio (**Add file → Upload files**), reemplazando el anterior.

Cada día el scraper vuelve a leer ese archivo y descarta los beneficios vencidos.

## Bancos que no se leen automáticamente

BancoEstado, Santander e Itaú bloquean navegadores automáticos. Sus descuentos se cargan
a mano en `descuentos.json` con `"origen": "manual"`.
