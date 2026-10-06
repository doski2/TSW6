# Sesión lab — ApiExplorer

Copia este archivo a `data/lab_exports/exports/<SESSION_ID>/notas_sesion.md` al empezar.

| Campo | Valor |
| --- | --- |
| session_id | (carpeta timestamp, p. ej. 20261005T…) |
| vehicle_class | |
| Ruta / escenario | (p. ej. GCT-MNR White Plains) |
| Variante coches | (p. ej. M3a 8-car, cabina A_C) |
| Build ApiExplorer | |
| Build TelemetryProbe | |
| Fecha / jugador | |

## Objetivo de esta sesión

- [ ] Barrido L0 completo (F5–F7 + Shift)
- [ ] Solo mandos (F6)
- [ ] Solo aire MC (L0.6g)
- [ ] Señales US (L0.4b)
- [ ] Puertas (F6 hijos / F7 DMI)

## Capturas F5 (renombrar `hud_batch.json` antes del siguiente F5)

| Archivo | Estado MC / freno | Velocidad | Notas |
| --- | --- | --- | --- |
| hud_batch_00_reposo.json | neutro | 0 | |
| hud_batch_01_B1.json | B1 | 0 | |
| hud_batch_02_B2.json | B2 | 0 | |
| hud_batch_03_B3.json | B3 | 0 | |
| hud_batch_04_traccion.json | tracción mínima | ~25 mph | |

## RailBridge (mismo día)

Copiar exports a `railbridge/` en esta carpeta:

- [ ] `tsw-api-export-CurrentDrivableActor-*.json`
- [ ] `tsw-api-export-DriverInput-*.json`
- [ ] `tsw-api-export-CurrentFormation-*.json`
- [ ] `tsw-api-export-Player-*.json`

## Hallazgos (qué expone este tren y otro no)

- Puertas (`PassengerDoor_*` / DMI):
- Señal adelante (`signalAspectClass`):
- Manómetro vs cilindro HTTP:
- Controles F6 no vistos en 323:

## Siguiente paso PC

```bat
python scripts\tools\api_correlator.py --formation data\lab_exports\exports\<SESSION_ID>
python scripts\tools\vehicles_json_from_lab.py data\lab_exports\exports\<SESSION_ID> --vehicle-id m3a_mnr
```

M3a: `python scripts\tools\build_m3a_profile_from_exports.py` (ajustar rutas dumps en el script).
