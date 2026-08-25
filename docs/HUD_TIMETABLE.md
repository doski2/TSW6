# Horarios TSW HUD (`tsw_hud.db`)

Integración opcional con el extractor del proyecto [TSW
HUD](<https://www.trainsimcommunity.com/mods/c3-train-sim-world/c75-utilities/i7169-tsw-hud-timetable-extractor>)
(`tsw_projects-main/hud`).

**Estado (2026-08-23):** ✅ planning de paradas integrado · 🔄 parada exacta en tablón (frenado)
pendiente

---

## Qué hace hoy el autopilot

Con `-HTTPAPI` y `tsw_hud.db` disponible:

1. Lee `currentServiceName` + `geoLocation` de `DriverAid.PlayerInfo`.
2. Busca el horario en SQLite (`find_active_timetable`, desambiguación por geo).
3. Filtra paradas del servicio (solo **STOP**, ignora `GO VIA`).
4. Construye la lista de estaciones con `merge_schedule_stations`:
   - Si `TrackData.markers` coincide por nombre → distancia along-track de DriverAid.
   - Si no coincide (p. ej. andenes de dirección equivocada) → distancia desde **`car_stop_signs`**

        (`source: hud_geo`).

5. Expone en telemetría/GUI: `schedule_source=hud_db`, `hud_timetable_id`, próxima parada.

Si no hay BD o no hay match → fallback a `timetable.json` → sin filtro (todos los markers).

---

## Qué aporta frente a otras fuentes

| Fuente | Paradas | Paso sin parar | Posición tablón |
| --- | --- | --- | --- |
| `timetable.json` | Manual por headcode | No | No |
| `DriverAid.TrackData` | Andenes adelante (a veces dirección incorrecta) | No | Fin de andén |
| **`tsw_hud.db`** | Horario del servicio/escenario | Sí (`GO VIA`) | ✅ `car_stop_signs` (planning) · 🔄 frenado FSM |

---

## Instalación de la BD

### BD semilla (obligatoria para extraer)

El clone de GitHub **no incluye** `tsw_hud.db` (`.gitignore`). Sin ella, `hud.exe` falla con:

```text
```

1. Descarga [TSW HUD & Timetable Extractor

v4.0.2](<https://www.trainsimcommunity.com/mods/c3-train-sim-world/c75-utilities/i7169-tsw-hud-timetable-extractor>)
   (`2-July-2026-hud-rust.zip`, ~770 MB).

2. Dentro del ZIP: `hud\resources\db\tsw_hud.db`
3. Copia a `…\tsw_projects-main\tsw_projects-main\hud\resources\db\tsw_hud.db`
4. O ejecuta `preparar_db_hud.bat` en TSW6 (puede extraer del ZIP automáticamente).

### Extraer horarios de tus DLCs

| Script | Función |
| --- | --- |
| `extraer_horario_hud.bat` | Compila `hud.exe` si hace falta (Rust + VS Build Tools) |
| `preparar_db_hud.bat` | Copia/sincroniza `tsw_hud.db` semilla y al autopilot |
| `abrir_hud_extraccion.bat` | Abre `hud.exe` → pestaña **Extraction** → **Load my DLCs** |
| `instalar_rust_hud.bat` | Instala Rust (winget) |
| `refrescar_path_rust.bat` | Refresca PATH de `cargo` |

Tras cada extracción en `hud.exe`, ejecuta `preparar_db_hud.bat` para sincronizar la BD más
reciente.

### Rutas donde el autopilot busca la BD

| Prioridad | Ruta |
| --- | --- |
| 1 | Variable de entorno `TSW_HUD_DB` |
| 2 | **`hud/src-tauri/target/release/resources/db/tsw_hud.db`** — BD completa tras extracción DLCs (~4 GB) |
| 3 | `TSW6/tsw_hud.db` (copia local) |
| 4 | `TSW6/data/tsw_hud.db` |
| 5 | `hud/resources/db/tsw_hud.db` (semilla del mod) |

Tras extraer en `hud.exe`, la BD de **release** es la referencia; `preparar_db_hud.bat` también
copia a `TSW6/tsw_hud.db` como respaldo.

### Verificar

```bat
```

Debe mostrar `[OK] BD encontrada` y, si extrajiste Cross-City, un horario `2R17` con paradas STOP.

---

## Campos de telemetría

| Campo | Valores / uso |
| --- | --- |
| `schedule_source` | `hud_db` · `timetable_json` · `trackdata` |
| `hud_timetable_id` | ID SQLite cuando `hud_db` |
| `hud_route_name` | Nombre de ruta (ej. Birmingham Cross-City) |
| `next_stop_name` | Próxima parada programada |
| `next_stop_distance_m` | Distancia (TrackData o `hud_geo`) |
| `next_stop_arrival` | Hora llegada programada (HUD DB) |
| `next_stop_departure` | Hora salida programada (HUD DB) |
| `stations[].arrival` / `departure` | Horario por fila en planning |
| `stations[].source` | `hud_geo` cuando la distancia viene de `car_stop_signs` |

En la GUI (pestaña **Planning**): horas `arr` / `dep` en próxima parada y tabla de estaciones.

---

## `car_stop_signs` — qué es

Tabla en `tsw_hud.db` con la **posición GPS del tablón de parada** en cada andén (`latitude`,
`longitude`, `platform_name`, `route_id`).

| Uso | Detalle |
| --- | --- |
| **Planning** | Si TrackData trae andenes incorrectos, distancia haversine tren → tablón (`source: hud_geo`). |
| **Frenado** | 🔄 El tablón marca dónde debe quedar el tren parado; P1 aún no frena exactamente ahí (falta OCR/GPS cada tick). |

No es cartel de velocidad ni semáforo: es el **punto de parada comercial** del horario en el mundo.

---

## Módulos Python

| Archivo | Rol |
| --- | --- |
| `hud_timetable.py` | `HudTimetableStore` — lectura SQLite, `car_stop_signs`, merge estaciones |
| `driver_aid_parser.py` | `filter_stations_by_stop_names`, `parse_track_data_stations` |
| `tsw_telemetry_source.py` | `_apply_station_filter`, `_attach_schedule_meta`, hilo `tsw-planning` |
| `verificar_hud_db.py` | Comprobación rápida de la BD |
| `test_hud_timetable.py` | Tests unitarios |

Conexión SQLite **thread-local** (hilo principal + `tsw-planning` no comparten conexión).

---

## Validar in-game

1. TSW6 con **`-HTTPAPI`**, servicio comercial (ej. **2R17** Cross-City, Class 323).
2. `iniciar_autopilot.bat` → pestaña **Planning**.
3. Comprobar:
   - `Próxima parada: Four Oaks … [horario HUD #…]` (no Shenstone/Lichfield si no están en el

     horario).

   - Columnas **Llegada** / **Salida** en la tabla de estaciones (horario comercial).
   - Barra superior: `Estaciones: HTTP`.

**Estado (2026-08-24):** horarios y arr/dep en GUI validados in-game. Pendiente: frenado fino en
andén y uso de `station_eta` en v2.

---

## Limitaciones actuales (parada exacta)

| Pieza | Estado |
| --- | --- |
| Lista de paradas correcta (horario HUD) | ✅ |
| Coordenadas `car_stop_signs` en planning | ✅ |
| Distancia `hud_geo` (haversine) si TrackData no coincide | ✅ |
| Horas llegada/salida en telemetría/GUI | ✅ (validado in-game 2026-08-24) |
| Recalcular distancia cada tick con GPS | ❌ (odometría entre polls HTTP ~2 s) |
| Frenado planificado `planBrakeForStation` | ❌ (FSM usa perfil simple) |
| OCR «DETÉNGASE EN EL LUGAR» | ❌ (opcional: `pip install mss pytesseract`) |

**Resumen:** el planning sabe **qué** parada y **dónde** está el tablón; el frenado fino en el
último tramo es el siguiente bloque de trabajo ([DASTSC_PARITY.md](DASTSC_PARITY.md)).

---

## Referencias

- [DRIVERAID_API.md](DRIVERAID_API.md) — `PlayerInfo.geoLocation`, `TrackData.markers`
- [DASTSC_PARITY.md](DASTSC_PARITY.md) — `planBrakeForStation` pendiente
- [GUIA.md](GUIA.md) — scripts `.bat` y requisitos
