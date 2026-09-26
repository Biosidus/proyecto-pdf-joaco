# Enderezador de páginas dobles · CBR a PDF

Recibe un tomo escaneado (`.cbr`, `.cbz`, `.rar`, `.zip` o `.pdf`) y devuelve un
PDF donde **las páginas dobles quedan horizontales de verdad**, no como una
página vertical con el dibujo acostado.

No usa ninguna API ni necesita claves: la conversión es local, instantánea y no
tiene límite de uso.

## El problema que resuelve

En muchos escaneos las páginas dobles (las que ocupan dos páginas del tomo)
vienen guardadas dentro de un lienzo **vertical**, con el dibujo girado 90°. Un
conversor común las pone en una página vertical y el lector las muestra
acostadas: hay que inclinar la cabeza para leerlas.

En el tomo de ejemplo pasa exactamente eso: de 176 páginas, **16 dobles** (las 5,
24, 43, 48, 51, 58, 59, 66, 69, 78, 94, 109, 130, 147, 148 y 169) están
guardadas acostadas dentro de un lienzo vertical.

## Cómo sabe cuál es doble, sin IA

Por la forma. Si una página simple del tomo mide `P` de ancho sobre alto, una
doble desplegada mide el doble de ancho: `2P`. Guardada acostada, esa misma doble
mide `1/(2P)`. Para una página 2:3 (`P = 0,667`), la doble acostada mide `0,75`.
Son formas distintas y no se superponen.

El detector no fija ningún valor: saca la proporción dominante del propio archivo
(la página simple, que es la gran mayoría) y después, para cada página, compara
dos hipótesis: *"está derecha"* o *"está girada"*. Gana la que deja la página
parecida a una simple (`P`) o a una doble (`2P`).

En el tomo de ejemplo detecta `base = 0,691` y acierta las 16 dobles, sin tocar
las otras 160.

Si un archivo no tiene una forma de página clara —pocas páginas, o simples y
dobles empatadas— el detector **no adivina**: deja todo como está y lo marca con
confianza baja. Adivinar ahí sale peor que no hacer nada, porque termina girando
las simples y dejando las dobles como estaban.

### Por qué no usa IA

Antes de descartarlo lo medí. Escribí un detector automático por perfil de tinta
(en una página derecha el texto y los paneles forman líneas horizontales;
acostada, verticales) y lo probé contra las 176 páginas del tomo, donde la
respuesta correcta se conoce de antemano. Probé cinco estadísticas distintas y la
mejor acertó el eje **107 de 176 veces (61%)**: el arte del manga, con paneles
negros e ilustraciones a sangre, rompe la suposición de "líneas de texto" en la
que se apoyan esos métodos. La forma, en cambio, sale del propio escaneo y no
falla.

## Lo único que la forma no puede decidir

Girar 90° o 270° deja la misma forma: la doble queda horizontal en los dos casos,
pero en uno queda boca abajo. Eso es **una sola decisión por tomo**, y la
resuelve quien mira el resultado.

Por eso, después de convertir, la interfaz muestra las miniaturas de las páginas
que tocó y un botón **"Dar vuelta las dobles"** que rehace el PDF para el otro
lado. Como las páginas ya quedaron extraídas en disco, darlas vuelta no vuelve a
leer el archivo original.

## Instalación

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Para leer archivos .cbr

El formato `.cbr` es un RAR. El programa busca `unrar` en el PATH y, si no está,
prueba las rutas típicas de WinRAR (`C:\Program Files\WinRAR\UnRAR.exe`). Con
WinRAR o 7-Zip instalado no hay que hacer nada más. Los `.cbz` no lo necesitan.

## Uso

```powershell
.venv\Scripts\python.exe app.py
```

Abrí <http://127.0.0.1:8000>, soltá el archivo y esperá. Al terminar tenés el
botón de descarga, las miniaturas de las páginas enderezadas para revisarlas y el
botón para darlas vuelta si quedaron boca abajo.

El archivo original se borra apenas se extraen las páginas, y lo que queda de un
cierre forzado se limpia solo al arrancar (trabajos y subidas de más de 12
horas). No hace falta limpiar `workdir/` a mano.

También podés convertirlo desde la consola, sin interfaz:

```python
from pathlib import Path
from core.config import settings
from core.extract import extract_pages
from core.orientation import detect_layout
from core.builder import build_pdf

entrada = Path("Haikyuu - Tomo 18.cbr")
paginas = extract_pages(entrada, Path("salida/pages"), pdf_dpi=settings.pdf_render_dpi)
layout = detect_layout(paginas, giro_dobles=270)
reporte = build_pdf(paginas, layout.planes, Path("salida/tomo.pdf"),
                    page_height_pt=settings.page_height_pt, title=entrada.stem)
print(reporte["resumen"])
```

## Configuración

Todo se ajusta desde `.env` (copiá `.env.example`):

| Variable | Por defecto | Para qué |
|---|---|---|
| `GIRO_DOBLES` | `270` | Para qué lado se giran las dobles acostadas (90 o 270). Es sólo el punto de partida: se cambia con un botón. |
| `PDF_RENDER_DPI` | `200` | Resolución con la que se leen las páginas cuando la entrada es un PDF. |
| `PAGE_HEIGHT_PT` | `756` | Alto de página del PDF final en puntos (756 pt = 10.5"). Las dobles quedan del doble de ancho. |
| `MAX_UPLOAD_MB` | `2048` | Tamaño máximo de subida en MB. Si un tomo lo supera, se avisa al subirlo y no se guarda nada. |

## Estructura

```
app.py                 Servidor FastAPI y endpoints
core/config.py         Configuración desde .env
core/extract.py        CBR/CBZ/PDF -> imágenes de página en disco
core/orientation.py    Decisión de qué páginas girar, por forma
core/builder.py        Arma el PDF y las miniaturas
core/pipeline.py       Trabajos, fases, progreso y el botón de dar vuelta
static/                Interfaz web
workdir/               Subidas y resultados, se limpian solos (ignorado por git)
```

## Problemas frecuentes

- **"No se reconoce el formato"** — El archivo no empieza ni como RAR, ni como
  ZIP, ni como PDF. Se elige el lector por la firma de los primeros bytes, no por
  la extensión, así que un `.cbr` que en realidad es un PDF se lee igual.
- **"N sin poder decidir"** — No se pudo determinar la forma de página del tomo
  (pocas páginas, o simples y dobles empatadas). No se giró ninguna; revisá las
  miniaturas.
- **Las dobles quedaron boca abajo** — Es la decisión que la forma no puede tomar.
  Usá el botón "Dar vuelta las dobles".
- **Una página quedó como estaba y era doble** — Pasá el mouse por la miniatura
  para ver el motivo. Suele pasar cuando la doble ya venía horizontal: ahí se
  deja como está a propósito, porque girarla la volvería vertical.
- **"El archivo supera el límite"** — El tomo pesa más que `MAX_UPLOAD_MB` (2 GB
  por defecto) y no se guardó nada. Subí el valor en el `.env` y reiniciá la app.
