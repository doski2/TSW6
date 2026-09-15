# TSW6 — Cursor Composer 2.5 Pack

Pack de agentes y reglas para el proyecto TSW6.

## Instalación

Copia el contenido de `.cursor/` en la raíz del repositorio TSW6:

```text
TSW6/
└── .cursor/
    ├── agents/
    └── rules/
```

No elimina ni sustituye `.github/agents/`; esos agentes pueden mantenerse para GitHub Copilot.

## Qué cambia

### Rules
- `00-tsw6-core.mdc`: reglas globales.
- `10-architecture.mdc`: fronteras de arquitectura.
- `20-python-v2.mdc`: Python V2.
- `30-telemetry.mdc`: telemetría.
- `40-braking-p1.mdc`: frenado P1.
- `50-validation.mdc`: validación.
- `60-documentation.mdc`: documentación.

### Agents
- `tsw6-architect`
- `tsw6-domain-expert`
- `tsw6-telemetry-engineer`
- `tsw6-braking-engineer`
- `tsw6-python-engineer`
- `tsw6-researcher`
- `tsw6-validation-engineer`
- `tsw6-debugger`
- `tsw6-reviewer`

## Flujo recomendado

Petición compleja:
Architect → Domain/Telemetry/Braking → Python Engineer → Validation → Reviewer.

Bug:
Debugger → Python Engineer → Validation → Reviewer.

Investigación:
Researcher → Architect/Domain → implementación solo cuando la evidencia sea suficiente.

## Nota

El pack está diseñado para complementar la documentación existente del repositorio, no para sustituir `PLAN_V2.md`, `CODIGO_V2.md`, `MANTENIMIENTO.md` ni `REGLAS_FRENOS_P1.md`.
