# Medición de la distancia del HUD por OCR

Estado (2026-10-18): **medición + ancla de control opcional**. La lectura se graba siempre en el
JSONL. Con `TSW6_HUD_OCR_CONTROL=1` (activo en `run_gui.bat`) el HUD **manda sobre la distancia de
parada**: el objetivo es el marcador del juego, no el fin de andén de `TrackData`, que queda de
referencia (§ Ancla de control). Sin validar en juego.

## Por qué

- `DriverAid.TrackData.markers[].distanceToStationCM` es el **fin del andén**, no el tablón de

  parada
  ([DRIVERAID_API.md](../reference/DRIVERAID_API.md) §TrackData). El HUD del juego muestra, bajo el
  icono de la mano, la distancia al **punto de parada** (`1.465 ft (pies)`, `51 ft (pies)`).

- Medido el 2026-10-15 contra el HUD: White Plains 133,4 m (app) frente a 15,5 m (HUD); Hartsdale

481 m frente a ≈ 447 m. El desfase cambia por estación (≈ 35 a ≈ 118 m) y la lectura HTTP llega con
  un refresco de ~4,2 s de mediana ([ANALISIS_PROYECTO § 7](ANALISIS_PROYECTO_2026-10-13.md)).

- [PLAN_V2 § 4.4](PLAN_V2.md) descartó el OCR **como entrada de control** (herencia de Dastsc/TSC:

  lento, frágil). Aquí se usa solo para **medir**; si los datos lo justifican se decide después
  (§ Criterios).

## Qué hace y qué no

| Hace                                                                          | No hace                                                     |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Captura una región del monitor principal cada 0,5 s y lee `N ft (pies)` / `m` | Cambiar el frenado si `TSW6_HUD_OCR_CONTROL` no está activo |
| Convierte a metros y guarda `hud_ocr_m`, `hud_ocr_age_s`, `hud_ocr_raw`       | Funcionar sin el marcador de parada visible                 |
| Evalúa offline «corregir cada N capturas» (`scripts/analyze_hud_ocr.py`)      | Leer otros textos del HUD (nombre, hora)                    |

El HUD solo muestra la distancia cuando el marcador de parada está en pantalla. Fuera de esa zona no
hay lectura y los campos no se escriben.

## Requisitos

```text
```

Además el binario **Tesseract** (Windows: `C:\Program Files\Tesseract-OCR\tesseract.exe`; se
detecta solo, o `TSW6_TESSERACT=<ruta>`). Sin él el agente funciona igual y avisa de que el OCR
queda desactivado.

## Uso

1. **Calibrar la región** (juego abierto, marcador de parada visible):

   ```text
   ```

   Guarda `monitor.png`, `recorte.png` y `recorte_procesado.png` en `logs/v2/hud_ocr_calibration/`
   y muestra la lectura. **Ojo:** `monitor.png` es una captura completa de tu monitor principal;
   bórrala si no quieres conservarla. Si la lectura sale vacía, ajusta la región como fracciones del
   monitor `izquierda,arriba,ancho,alto`:

   ```text
   ```

   (valor por defecto, medido sobre 2560×1440 con el HUD en su sitio habitual).

2. **Grabar una sesión con OCR:** `V2/run_gui.bat` lo activa por defecto (`TSW6_HUD_OCR=1`; para

   desactivarlo, `set TSW6_HUD_OCR=0` antes de lanzarlo). En otros comandos, añade `--hud-ocr` o
   `set TSW6_HUD_OCR=1`:

   ```text
   ```

3. **Analizar** el JSONL resultante:

   ```text
   ```

Variables: `TSW6_HUD_OCR` (1 activa), `TSW6_HUD_OCR_REGION`, `TSW6_HUD_OCR_MONITOR` (índice de
`mss`;
por defecto el principal), `TSW6_HUD_OCR_INTERVAL` (s, 0,5), `TSW6_TESSERACT`.

## Ancla de control (`hud_anchor.py`)

Se activa con `TSW6_HUD_OCR=1` y `TSW6_HUD_OCR_CONTROL=1` (`run_gui.bat` pone ambas; `=0` la apaga):

1. **Cambio de marco** fin de andén → tablón: dos capturas seguidas con el mismo desfase (±12 m,

   dentro de −15…250 m). Una lectura rota («0 m» con el tablón a 1,5 km) no entra.

2. **Seguimiento:** captura a más de 40 m de la estimación = descartada; corrección por captura

   limitada a 15 m. La lectura se lleva a «ahora» restando `v × edad`.

3. **HTTP:** sigue entrando, convertido al marco del tablón restando el desfase aprendido (se afina

   con cada lectura HTTP mientras el ancla es reciente). Al cambiar de estación se descarta.

4. **Sin lectura** (marcador fuera de pantalla, OCR caído, < 3 mph) la distancia sigue por `v×dt`.

El estado se graba por tick en `ocr_anchor` (`wait …` / `board off=<desfase> n=<aceptadas>
c=<corrección>`).
Los umbrales salen de Fleetwood (desfase 95–101 m); otras estaciones sin medir.

## Qué se graba

Por tick con lectura reciente (< 3 s): `hud_ocr_m` (distancia del HUD en metros),
`hud_ocr_age_s` (antigüedad de la captura) y `hud_ocr_raw` (texto OCR, para depurar). El código está
en `V2/tsw6v2/hud_ocr.py`; el cableado, en `AgentLoop.step()` y `trace.py`.

## Cómo se evalúa «corregir cada N capturas»

`hud_ocr_eval.py` trabaja por aproximación a cada estación:

1. Una captura es nueva cuando `hud_ocr_age_s` baja respecto al tick anterior. Se le resta

   `v × edad` para llevarla a «ahora».

2. **Política «ancla cada N»:** en cada N-ésima captura la distancia se fija al valor del HUD y,

   entre anclas, se resta lo recorrido (odometría de `spd_mph`). El error se mide en las capturas
   que **no** son ancla, frente al HUD.

3. Se compara con la distancia actual de la app (`stn_dist_m`), por bandas de distancia

   (0–100, 100–300, 300–1000 m), y se informa el desfase mediano por estación.

La tabla da, por política y banda: nº de muestras, error absoluto medio, sesgo y percentil 95.

## Criterios para decidir (propuestos, a confirmar con datos)

| Resultado en la banda 100–300 m                           | Decisión                                                               |
| --------------------------------------------------------- | ---------------------------------------------------------------------- |
| «app» ≫ «ancla cada N» (p. ej. 35–118 m frente a < 15 m)  | Merece corregir; elegir el N más alto que se mantenga bajo el umbral   |
| El sesgo de «app» es estable por estación                 | Bastaría un desfase por estación (sin OCR en el control)               |
| El sesgo de «app» cambia entre sesiones                   | La corrección debe ser en vivo (OCR o ancla de tablón por coordenadas) |
| Pocas lecturas válidas (`n` bajo)                         | Recalibrar la región, o el OCR no es viable con tu HUD                 |

Antes de llevar el OCR al control habría que diseñar fallos (lectura errónea, HUD oculto, idioma) y
un tope de corrección por tick; no está hecho.

## Límites conocidos (UNKNOWN hasta medir)

- El HUD está localizado («pies»); con otro idioma o escala de interfaz la región y el parser

  pueden fallar.

- El monitor se elige donde esté la ventana visible de «Train Sim World» (Windows); si no se

  encuentra, el principal. `TSW6_HUD_OCR_MONITOR` (índice de `mss`) lo fuerza. En 2026-10-18 una
  calibración eligió el monitor equivocado (1920×1080 en vez del 2560×1440 del juego); la
  detección por ventana se añadió después y no está probada con el juego abierto.

- La frecuencia con la que el HUD refresca el número no está medida; `hud_ocr_age_s` solo cubre el

  retardo propio de la captura.

- Un solo marcador visible: con varias paradas cercanas el número puede ser del siguiente andén.
