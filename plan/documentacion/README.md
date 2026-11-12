# Documentación de la base nueva

Aquí se diseña **qué documentación tendrá** el proyecto nuevo y dónde vivirá cada cosa. Los
documentos definitivos se escriben cuando se cierre la fase de arquitectura.

## Documentos previstos

| Documento                 | Contenido                                                             | Público        |
| ------------------------- | --------------------------------------------------------------------- | -------------- |
| `README.md`               | Qué es, instalación rápida, primer uso                                | Usuario        |
| `docs/usuario/`           | Guía de uso, configuración, solución de problemas                     | Usuario        |
| `docs/arquitectura.md`    | Capas, flujo de un tick, contratos entre módulos, diagramas           | Desarrollador  |
| `docs/vehiculos.md`       | Esquema del paquete de tren y cómo añadir uno                         | Desarrollador  |
| `docs/contrato-mod.md`    | Contrato IPC/HTTP con el mod Lua, versionado                          | Desarrollador  |
| `docs/reglas/`            | Una página por política de frenado/tracción con sus ADR y tests       | Desarrollador  |
| `docs/referencia-api/`    | Catálogo de la HTTPAPI y nombres UE (se migra desde `docs/reference/`) | Desarrollador |
| `AGENTS.md`               | Instrucciones únicas para asistentes de IA                            | Agentes        |
| `CHANGELOG.md`            | Cambios por versión                                                   | Todos          |

## Inventario de la documentación actual

`docs/` tiene 65 archivos (~12 300 líneas de Markdown) repartidos en `v1/`, `v2/`, `reference/` y
`assets/`, más `archive/docs/`. Propuesta de destino (a revisar en el debate):

| Origen                                 | Destino propuesto                                    |
| -------------------------------------- | ---------------------------------------------------- |
| `docs/reference/*`                     | Migrar tal cual a `docs/referencia-api/`             |
| `docs/CANAL_CONTROL.md`                | Base del nuevo `docs/contrato-mod.md`                |
| `docs/v2/REGLAS_FRENOS_P1.md`          | Fuente para `docs/reglas/` y para R-01               |
| `docs/v2/TRENES_DLC.md`, `VEHICLE_LAB.md` | Fuente para `docs/vehiculos.md` y R-05            |
| `docs/v2/ANALISIS_*`, `VALIDACION_*`, `PLAN_*` | Archivo histórico (`archive/docs/`)          |
| `docs/v1/*`                            | Archivo histórico                                    |
