# Logs probe UE4SS — layout

**Grabar:** `probe_ue4ss.bat` · **Analizar amps:** `amp.bat` (última sesión bajo `logs/probe/`).

## Carpetas

```text
logs/
  probe/
    YYYYMMDD_HHMMSS/           # una sesión de campo
      ue4ss_probe_*.txt        # CSV + # raw:
      amp_report.md            # opcional: amp.bat ... --write-report
    informe_combinado_amp.md   # solo si pasas varios logs a amp.py --write-report
  v2/                          # JSONL P1 (run_p1_session)
  profiles/                    # learner
  brake_physics/               # validar_freno
```

Cada nueva sesión probe crea **`logs/probe/<stamp>/`** automáticamente (desde build reader actual).

## Plan amps/puertas M3a (cerrado)

| Carpeta | Contenido |
| ------- | --------- |
| `logs/probe/20261007_001325/` | B_C · amps + puertas (`doors_telem` 0↔1) |
| `logs/probe/20261007_233912/` | A_C · amps (sin ciclo puertas) |
| `logs/probe/informe_combinado_amp.md` | Resumen amps ambas sesiones |

Sesiones abortadas (&lt;1 s) se eliminan; no se archivan.
