# TSW6 Autopilot — Guía rápida de uso

Instrucciones básicas para recordar qué hace cada herramienta y en qué orden usarlas.

---

## Requisitos previos

1. **Train Sim World 6** con la **API HTTP** activa (`-HTTPAPI` al arrancar el juego).
2. Estar **en cabina**, tren encendido.
3. **Python 3.9+** (los `.bat` lo detectan solos).

> **RailBridge ya no se usa.** El código companion está en `archive/railbridge/`.

---

## Los 4 lanzadores (`.bat`)

| Archivo                 | Qué hace                                                             |
| ----------------------- | -------------------------------------------------------------------- |
| `diag_controles.bat`    | Diagnóstico de mandos — lanza `tsw_monitor.py` (API TSW)             |
| `aprender.bat`          | Calibración guiada — aprende cuánto acelera/frena cada muesca        |
| `iniciar_autopilot.bat` | Autopiloto — conduce usando el perfil ya calibrado                   |
| `iniciar_monitor.bat`   | Monitor de la API TSW (depuración, sin autopiloto)                   |

---

## Flujo habitual

```text
```

- **Tren UK** (Class 323, 350…): puedes ir directo a `aprender.bat` opción **1**.
- **Tren freight NA** (SD40-2, SD70, ES44…): opcional `diag_controles` la primera vez; calibrar con

  `aprender.bat` opción **2**.

---

## 1. `diag_controles.bat` — Diagnóstico (Fase 0)

**No calibra.** Valida que la API TSW lee velocidad y mandos en cabina.

1. Arranca TSW6 con `-HTTPAPI` y sube al tren.
2. El monitor muestra tracción, frenos y velocidad en vivo.
3. Mueve **un mando a la vez** y comprueba que cambian los valores.
4. **Ctrl+C** al terminar.

> El diagnóstico antiguo vía RailBridge está en `archive/railbridge/diag_controles.bat`.

El nombre del tren se detecta de `ObjectClass` en la API.

---

## 2. `aprender.bat` — Calibración

Conduces **manualmente**; el monitor captura aceleración/frenado por muesca y banda de velocidad.

| Opción   | Modo                                                       |
| -------- | ---------------------------------------------------------- |
| **1**    | Continuar — **pasajeros** (handle UK 0–8, vel. mín. 5 mph) |
| **2**    | Continuar — **mercancías** NA (4 mandos, vel. mín. 2 mph)  |
| **3**    | Empezar de cero — pasajeros (borra el perfil de ese tren)  |
| **4**    | Empezar de cero — mercancías                               |
| **5**    | Salir                                                      |

### Durante la sesión

- Objetivo: **8 muestras** por celda (muesca × banda 0–30 / 30–60 / 60+ mph).
- Mantén **un solo mando estable ~2 s** mientras captura.
- Velocidad mínima: 5 mph (UK) o 2 mph (freight).
- Pendiente fuerte (>2 %): prioriza frenos; evita calibrar tracción.
- Autoguardado cada 5 s.

**Guarda el perfil en:** `logs/profiles/<Tren>.json`

### UK vs freight NA

| Tipo                | Mandos                                 | Opción `aprender`   |
| ------------------- | -------------------------------------- | ------------------- |
| UK EMU (Class 323…) | Handle combinado 0=freno … 8=tracción  | **1**               |
| Diesel NA (SD40-2…) | Tracción + freno auto + ind + dinámico | **2**               |

---

## 3. `iniciar_autopilot.bat` — Conducir

Usa el perfil en `logs/profiles/`. **No calibra** por defecto.

| Opción   | Modo                               |
| -------- | ---------------------------------- |
| **1**    | Autopilot — sigue el límite de vía |
| **2**    | Velocidad máxima personalizada     |
| **3**    | Solo monitorizar (no envía mandos) |
| **4**    | Manual por teclado                 |
| **5**    | Monitor de telemetría              |

Necesitas: CMP activo + perfil calibrado para ese tren.

---

## 4. `iniciar_monitor.bat` — API TSW

Herramienta de depuración (dashboard, discover, snapshot JSON). No usa calibración ni autopiloto.

---

## Dónde se guarda cada cosa

```text
```

Ejemplos:

- `logs/profiles/BNSF_SD40_2_C.json` — SD40-2 calibrado
- `logs/profiles/RVM_BCC_WRM_Class323_DMS_A_C.json` — Class 323

---

## Resumen en una frase

| Herramienta         | Pregunta que responde              |
| ------------------- | ---------------------------------- |
| `diag_controles`    | ¿Este tren manda bien los mandos?  |
| `aprender`          | ¿Cuánto acelera/frena cada muesca? |
| `iniciar_autopilot` | Conduce usando ese conocimiento    |

---

## Más detalle técnico

- Plan freight NA (fases 0–6): `FREIGHT_NA_PLAN.md`
- **API directa V2 (solo frenos, sin RailBridge):** `TSW_API_V2.md`
- Esquema plantilla diesel NA: `logs/control_schemas/freight_na_railbridge_v3.json`
