# Plan de Calibración del Autopilot — Class 323

## Objetivo

Recopilar datos reales del tren para calibrar las constantes físicas del `speed_governor.py`
y validar (o corregir) los valores actuales asumidos:

| Constante actual     | Valor supuesto  | Necesita validar   |
|----------------------|-----------------|--------------------|
| `MAX_DECEL_MS2`      | 0.90 m/s²       | ⚠️ Alta prioridad  |
| `TARGET_ACCEL_MS2`   | 0.55 m/s²       | ⚠️ Alta prioridad  |
| `TARGET_DECEL_MS2`   | 0.70 m/s²       | ⚠️ Alta prioridad  |
| `COAST_DECEL_MS2`    | 0.15 m/s²       | 🔵 Media prioridad |
| Corrección gradiente | `g * slope/100` | 🔵 Media prioridad |

---

## Modo Pasivo — `profiler.py`

**El usuario conduce manualmente. El profiler solo escucha y registra.**

### Ventajas

- No interfiere con el juego en ningún momento
- Se puede ejecutar en paralelo con el autopilot o completamente sin él
- Seguro: solo lee datos, nunca envía teclas ni modifica el estado del tren
- Datos reales de conducción normal en condiciones de juego auténticas
- Acumula estadísticas a lo largo de varias sesiones
- Cuanto más se conduce, más precisa es la calibración

### Desventajas

- Depende de que el usuario conduzca en los rangos de interés (frenadas largas, aceleraciones mantenidas)
- No garantiza cobertura de todos los gradientes ni de todos los notches
- Los datos llegan con la cadencia del SSE (~0.2 s), no de forma continua

---

### Cómo funciona

#### 1. Conexión y escucha

El profiler se conecta al endpoint SSE de RailBridge (`GET /events`) y procesa
cada evento en tiempo real. No necesita polling: el servidor empuja los datos.

profiler.py  →  GET <http://HOST:PORT/events>  →  stream de eventos JSON

#### 2. Máquina de estados por evento

Cada muestra recibida se clasifica según la posición del handle (`notch`):

| Notch | Estado detectado | Constante a medir                    |
|-------|------------------|--------------------------------------|
| 0–3   | FRENADO          | `MAX_DECEL_MS2`, `TARGET_DECEL_MS2`  |
| 4     | NEUTRO / INERCIA | `COAST_DECEL_MS2`                    |
| 5–8   | ACELERACIÓN      | `TARGET_ACCEL_MS2`                   |

Transiciones relevantes:

- `>4 → ≤3` : inicio de evento de frenado
- `≤3 → 4`  : fin de evento de frenado
- `4 → ≥5`  : inicio de evento de tracción
- `≥5 → 4`  : fin de evento de tracción

#### 3. Registro por evento

Durante cada evento se captura, muestra a muestra:

| Campo            | Fuente API           | Descripción                                      |
|------------------|----------------------|--------------------------------------------------|
| `t`              | timestamp local      | Tiempo relativo al inicio del evento (s)         |
| `v`              | `speed_ms`           | Velocidad en m/s                                 |
| `grad`           | `gradient_pct`       | Gradiente de la vía en %                         |
| `notch`          | `handle_position`    | Posición del handle (0–8)                        |
| `dist_delta`     | integrado            | `v * Δt` acumulado (m)                           |
| `next_stop`      | `stations[0].name`   | Nombre de la próxima parada programada           |
| `next_stop_dist` | `stations[0].dist_m` | Distancia restante a esa parada (m)              |
| `speed_limit`    | `limit_mph`          | Límite de velocidad activo en ese instante (mph) |
| `next_limit`     | `next_limit_mph`     | Próximo límite de velocidad (mph)                |
| `service`        | `service_name`       | Nombre del servicio (ej. 2T34 Bham→Lichfield)    |

#### 4. Cálculo de aceleración

Al cerrar un evento (cambio de notch o velocidad ~0):

a = (v_final - v_inicial) / (t_final - t_inicial)   [m/s²]

La integración trapezoidal da la distancia recorrida:

$$d = \sum_{i} \frac{v_i + v_{i+1}}{2} \cdot \Delta t_i$$

#### 5. Agrupación por gradiente

Los eventos se agrupan en bandas de gradiente para aislar el efecto de la pendiente:

| Banda         | Rango         |
|---------------|---------------|
| Plano         | ±0.5%         |
| Subida leve   | +0.5% a +1.5% |
| Subida fuerte | >+1.5%        |
| Bajada leve   | -0.5% a -1.5% |
| Bajada fuerte | <-1.5%        |

Dentro de cada banda se calculan: media, desviación estándar, mínimo y máximo.

#### 6. Filtros de calidad

Se descartan eventos que no cumplen:

- Duración mínima: **3 s** (evitar cambios de notch accidentales)
- Δv mínimo: **2 m/s** (evitar mediciones con muy poca variación)
- Velocidad inicial mínima: **5 m/s** (evitar arranques desde parado con deslizamiento)
- Gradiente constante: variación `< 0.3%` durante el evento (evitar tramos mixtos)

#### 7. Registro de paradas y contexto de ruta

Además de las constantes físicas, el profiler aprovecha que la API ya expone
las paradas programadas en cada snapshot para construir **automáticamente**
un perfil de la ruta sin ningún script adicional.

**Lo que se captura en cada parada detectada** (cuando `stations[0].distance_m < 50 m` y `speed < 2 mph`):

| Dato | Fuente API | Descripción |
|------|------------|-------------|
| Nombre de la parada | `stations[0]["name"]` | Etiqueta real del andén (ej. "Blake Street") |
| Longitud del andén | `stations[0]["platform_length_m"]` | Metros del andén (disponible si la API lo expone) |
| Posición odométrica | integrada `∫v dt` desde el inicio de sesión | Posición absoluta en la ruta (m) |
| Tiempo de permanencia | `doors_open` → `doors_closed` | Segundos entre apertura y cierre de puertas |
| Distancia de frenado real | desde inicio del último FRENADO hasta parada | Metros recorridos durante el frenado de entrada |
| Gradiente del tramo de entrada | `grad_avg` del evento FRENADO | Pendiente media durante el frenado |
| Velocidad de aproximación | `v_start` del evento FRENADO | Velocidad al inicio del frenado de entrada (mph) |
| Nombre del servicio | `service_name` | Identificador del trayecto (ej. "2T34") |

**Límites de velocidad**: en cada muestra se registra `limit_mph` y `next_limit_mph`.
Al final de la sesión se genera automáticamente una **tabla de límites por tramo**
agrupando los cambios de límite por posición odométrica.

**Salida adicional generada por la sesión**:

PARADAS VISITADAS (sesión):

  1. Blake Street          odo=12 450 m   andén=110 m   permanencia=32 s
     Frenado entrada: dist=380 m  v_ini=27.4 mph  grad=-0.1%
  2. Lichfield City        odo=24 120 m   andén=180 m   permanencia=41 s
     Frenado entrada: dist=510 m  v_ini=59.8 mph  grad=+0.3%
  3. Lichfield Trent Valley odo=26 890 m  andén=160 m   permanencia=28 s
     Frenado entrada: dist=420 m  v_ini=44.1 mph  grad=+0.8%

LÍMITES DE VELOCIDAD detectados:
  odo=    0–1 200 m   →  20 mph
  odo= 1 200–8 400 m  →  60 mph
  odo= 8 400–9 000 m  →  30 mph
  odo= 9 000–16 500 m →  60 mph

---

### Uso

```bash
python profiler.py --host 127.0.0.1 --port 51160
python profiler.py --host 127.0.0.1 --port 51160 --min-duration 5 --min-dv 3
python profiler.py --host 127.0.0.1 --port 51160 --output-dir logs/calibration/
```

#### Argumentos

| Argumento        | Default     | Descripción                          |
|------------------|-------------|--------------------------------------|
| `--host`         | `127.0.0.1` | Host de RailBridge                   |
| `--port`         | `51160`     | Puerto de RailBridge                 |
| `--min-duration` | `3.0`       | Duración mínima de evento (s)        |
| `--min-dv`       | `2.0`       | Δv mínimo del evento (m/s)           |
| `--output-dir`   | `logs/`     | Carpeta de salida para CSV y resumen |

---

### Salida en pantalla

=== SESIÓN DE CALIBRACIÓN — profiler.py ===
Servicio: 2T34  |  Conectado a <http://127.0.0.1:51160/events>

[12:03:41] FRENADO iniciado  v=22.1 m/s  notch=2  grad=+0.2%  → Blake Street (1 840 m)
[12:03:47] FRENADO cerrado   v=8.3 m/s   Δt=6.2s  a=-2.22 m/s²  ← DESCARTADO (|a|>2.0)
[12:04:15] FRENADO iniciado  v=19.4 m/s  notch=1  grad=-0.1%  → Blake Street (380 m)
[12:04:23] FRENADO cerrado   v=4.1 m/s   Δt=7.8s  a=-1.96 m/s²  → OK  grupo=Plano
[12:04:28] ★ PARADA  Blake Street  permanencia...
[12:05:01] ★ SALIDA  Blake Street  dwell=33 s  odo=12 450 m
[12:08:02] NEUTRO iniciado   v=15.2 m/s  notch=4  grad=+0.0%
[12:08:19] NEUTRO cerrado    v=13.6 m/s  Δt=17.1s a=-0.09 m/s²  → OK  grupo=Plano
...

=== RESUMEN PARCIAL (sesión activa) ===
FRENADOS válidos : 8   descartados: 3
ACELERACIONES    : 5   descartadas: 1
NEUTROS          : 4   descartados: 0
PARADAS visitadas: 2  (Blake Street, Lichfield City)

### Salida al cerrar (Ctrl+C)

=== SESIÓN DE CALIBRACIÓN COMPLETADA ===

FRENADOS registrados: 12
  Notch 0 (freno máx):
    Plano (±0.5%):      a_media = -0.87 m/s²  σ=0.04  (n=4)
    Bajada leve (-1%):  a_media = -0.71 m/s²  σ=0.06  (n=2)
    Subida leve (+1%):  a_media = -1.03 m/s²  σ=0.05  (n=3)
  Notch 1–2 (freno parcial):
    Plano (±0.5%):      a_media = -0.52 m/s²  σ=0.08  (n=3)

ACELERACIONES registradas: 8
  Notch 8 (tracción máx):
    Plano (±0.5%):      a_media = +0.61 m/s²  σ=0.05  (n=3)
    Subida leve (+1%):  a_media = +0.44 m/s²  σ=0.07  (n=2)

INERCIA (Notch 4):
    Plano (±0.5%):      a_media = -0.09 m/s²  σ=0.02  (n=4)

CONSTANTES RECOMENDADAS:
  MAX_DECEL_MS2    = 0.87   (actualmente 0.90)  ← reducir un 3%
  TARGET_ACCEL_MS2 = 0.61   (actualmente 0.55)  ← aumentar un 11%
  TARGET_DECEL_MS2 = 0.52   (actualmente 0.70)  ← reducir un 26%
  COAST_DECEL_MS2  = 0.09   (actualmente 0.15)  ← reducir un 40%
  Factor gradiente medido = 0.082 m/s²/%  (teórico 0.098)

---

### Archivos generados

| Archivo                                        |        Contenido                    |
|------------------------------------------------|-------------------------------------|
| `logs/calibration_YYYYMMDD_HHMMSS.csv` | Una fila por muestra: `t, v, notch, grad, next_stop, next_stop_dist,limit_mph, event_id` |
| `logs/calibration_events_YYYYMMDD_HHMMSS.csv`  | Una fila por evento cerrado con todos los campos de aceleración |
| `logs/calibration_stops_YYYYMMDD_HHMMSS.csv`   | Una fila por parada visitada con nombre, posición, dwell y frenado de entrada |
| `logs/calibration_limits_YYYYMMDD_HHMMSS.csv`  | Cambios de límite de velocidad con posición odométrica |
| `logs/calibration_summary_YYYYMMDD_HHMMSS.txt` | Resumen legible con constantes recomendadas + perfil de ruta |

#### Formato CSV de eventos (`calibration_events_*.csv`)

```csv
type,notch,grad_band,v_ini_ms,v_fin_ms,dt_s,accel_ms2,dist_m,next_stop,valid,reject_reason
BRAKING,1,flat,19.4,4.1,7.8,-1.963,91.0,Blake Street,True,
BRAKING,0,flat,22.1,8.3,6.2,-2.226,93.0,Blake Street,False,|a|>2.0
COAST,4,flat,15.2,13.6,17.1,-0.094,248.3,Lichfield City,True,
ACCEL,8,flat,2.1,16.8,28.3,+0.519,265.1,Lichfield City,True,
```

#### Formato CSV de paradas (`calibration_stops_*.csv`)

```csv
station_name,odo_m,platform_length_m,dwell_s,approach_dist_m,approach_v_mph,approach_grad_pct,service
Blake Street,12450,110,33,380,27.4,-0.1,2T34
Lichfield City,24120,180,41,510,59.8,+0.3,2T34
Lichfield Trent Valley,26890,160,28,420,44.1,+0.8,2T34
```

---

## Datos de ruta a recopilar

Además de las constantes físicas, sería útil generar un **perfil de ruta** con:

| Dato                                  | Fuente                      | Uso en el código                      |
|---------------------------------------|-----------------------------|---------------------------------------|
| Posición km de cada parada            | API `distance_m` + odómetro | Mejorar detección manual              |
| Gradiente entre paradas               | Log `grad=`                 | Pre-cargar en `should_brake_for_next` |
| Límites de velocidad por tramo        | Log `lim=`                  | Anticipar frenados                    |
| Distancia de frenado real por tramo   | Logs                        | Validar P1                            |

### Script: `route_profiler.py`

python route_profiler.py --log logs/autopilot_*.log --route "Cross-City"

Genera `routes/cross_city.json`:

```json
{
  "route": "Cross-City Birmingham",
  "stations": [
    {"name": "Lichfield City", "milepost": 0.0, "platform_length_m": 180},
    {"name": "Rugeley Trent Valley", "milepost": 6.9, "platform_length_m": 165}
  ],
  "speed_limits": [
    {"from_m": 0, "to_m": 500, "limit_mph": 20},
    {"from_m": 500, "to_m": 8000, "limit_mph": 60}
  ],
  "gradients": [
    {"from_m": 0, "to_m": 2000, "pct": +0.3},
    {"from_m": 2000, "to_m": 5000, "pct": +1.0}
  ]
}
```

Este archivo de ruta permitiría al autopilot **anticipar** gradientes futuros
en el cálculo de frenado, no solo reaccionar al gradiente actual.

---

## Notas adicionales

- La corrección de gradiente ya está implementada en `braking_distance()` con el factor teórico `9.81 * gradient_pct / 100`. Los datos de calibración dirán si el factor real es distinto.
- El `SAFETY_MARGIN = 1.40` (+40%) actualmente compensa la incertidumbre en `MAX_DECEL_MS2`. Con valores calibrados se podría reducir a 1.20-1.25, mejorando el confort.
- Para la Class 323, los valores típicos de referencia en la literatura son:
  - Frenado de servicio: 0.8–1.0 m/s²
  - Tracción máxima (arranque): 0.7–1.1 m/s² (cae rápido con la velocidad)
  - Tracción en crucero (60 mph): 0.3–0.5 m/s²
