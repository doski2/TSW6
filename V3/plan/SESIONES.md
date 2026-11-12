# Bitácora de sesiones (planificación V3)

Qué se hizo en cada sesión y por dónde seguir. Lo más reciente va arriba.

---

## 2026-11-13

**Hecho:**

- Se creó `V3/` en este repo para la base nueva desde cero (PREGUNTAS § D.3 respondida).
- Los documentos del PR #4 (`claude/project-thread-nc3odx`, que los dejaba en `plan/` en la raíz)
  se copiaron a `V3/plan/`. El PR sigue abierto en GitHub: queda por decidir si se cierra o se
  actualiza.
- Se decidió **empezar por el mod Lua** (propuesta del usuario). Documentos nuevos:
  - [investigaciones/R-10-revision-mod-lua.md](investigaciones/R-10-revision-mod-lua.md): qué hay
    en el mod de V2, lecciones y problemas a largo plazo.
  - [documentacion/mod-lua.md](documentacion/mod-lua.md): visión del mod V3 (contrato versionado,
    `hello`/`vehicle_config`/`tick`/`cmd`, hoja de ruta M0–M7).
  - [decisiones/0002-empezar-por-el-mod-lua.md](decisiones/0002-empezar-por-el-mod-lua.md):
    `Propuesta`.
  - [PREGUNTAS § H](PREGUNTAS.md#h-mod-lua): H.1–H.8.
- Rutas actualizadas a `V3/` en el README, el PLAN_DE_TRABAJO y `documentacion/README.md`.

**Acordado: forma de trabajar.** Se revisa documento a documento. El usuario comenta (citando la
sección o en texto libre) y Claude clasifica cada cosa:

| Tipo                       | Destino              |
| -------------------------- | -------------------- |
| Decisión                   | `decisiones/`        |
| Duda u opción              | `PREGUNTAS.md`       |
| Medir o probar en el juego | `investigaciones/`   |
| Idea futura                | `ideas/`             |
| Diseño de documentación    | `documentacion/`     |
| Orden o fases              | `PLAN_DE_TRABAJO.md` |
| Corrección de un hecho     | R-10 (o el documento que corresponda) |

**Orden de lectura:**

1. R-10.
2. `mod-lua.md`.
3. PREGUNTAS § H.
4. El resto de PREGUNTAS y el PLAN_DE_TRABAJO.

**Siguiente sesión:** el usuario lee **R-10** y comenta. Se empieza por ahí.

**Pendiente:**

- Sin commit: `V3/` está sin seguimiento en `main`.
- Decidir qué se hace con el PR #4.
