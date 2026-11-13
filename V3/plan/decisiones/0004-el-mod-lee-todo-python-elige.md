# 0004 — El mod lee todo lo posible; cada tren elige qué usa

- **Estado:** Aceptada (2026-11-13)
- **Fecha:** 2026-11-13
- **Pregunta de origen:** PREGUNTAS.md § H.9 (comentario del usuario al revisar `mod-lua.md`, 2026-11-13)
- **Investigaciones relacionadas:** R-10, R-05

## Contexto

Comentario del usuario (2026-11-13):

> Lo mejor es que [el mod] pueda leer todo lo posible y ya luego decidimos si usarlo o si se usa
> para ese tren, ya que según el tren se describe de distinta manera, y si es necesario investigar.

Datos:

- FACT (R-10): cada tren expone lo mismo con nombres y formas distintos (palanca combinada con
  peldaños en la 323, MC analógica en la M3A, enums de señal por región, nombres de puertas).
- FACT (R-10): en V2, un campo nuevo exige tocar el probe. Así cada investigación acaba en un
  cambio de Lua.
- FACT (`mod-lua.md`, principio 5): el ciclo caliente tiene que costar ≤ 1 ms. Recorrer objetos
  (`pairs()`, `FindAllOf`, introspección) en cada tick da tirones.
- INFERENCE: «leer todo» y «≤ 1 ms» son compatibles si se leen en momentos distintos.

## Opciones consideradas

1. **Leer todo en cada tick.** Es lo más simple, pero rompe el presupuesto de 1 ms y llena los
   logs.
2. **Leer solo una lista fija de campos (como V2).** Es barato, pero cada tren o campo nuevo obliga
   a tocar el mod.
3. **Catálogo + suscripción + canal ancho lento.** El mod descubre todo una vez, Python dice qué
   quiere en el ciclo y el resto se registra despacio para investigarlo.

## Decisión

Opción 3, en tres niveles:

| Nivel | Cuándo | Qué hace el mod | Coste |
| ----- | ------ | --------------- | ----- |
| **Catálogo** (`catalog`) | Una vez al cargar el tren, fuera del ciclo | Recorre lo que expone el tren (mandos, HUD, DriverAid, Simulation…) y publica cada campo: ruta, tipo, valor de muestra y rango si lo hay | Alto, una sola vez |
| **Suscripción** (`tick`, ~20 Hz) | Siempre | Lee solo los campos que pide `vehicle_config`, con las rutas ya resueltas y cacheadas | ≤ 1 ms |
| **Canal ancho** (`wide`, ~1 Hz) | Activado por defecto hasta validar el tren; Python lo apaga | Lee todos los campos baratos del catálogo y los manda al log | Repartido entre ticks |

- **El tren decide qué significa cada cosa.** El paquete del tren (`trenes/<id>/`, ver
  [0003](0003-estructura-por-tren-y-familia.md)) une cada nombre genérico (`speed`, `signal_stop`,
  `brake_cyl`…) con la ruta concreta del catálogo de ese tren. El mod no sabe qué es «velocidad»:
  solo lee la ruta que le dicen.
- **Investigar no exige tocar Lua.** Si un campo puede servir, se activa el canal ancho, se graba
  una sesión y se analiza. Si sirve, se añade a la suscripción del tren. Solo es un cambio de datos.
- **Respuestas a H.9 (2026-11-13):** el catálogo se hace en cada carga del tren; el canal ancho va
  activado por defecto hasta que el tren esté validado; el laboratorio sigue aparte, pero solo para
  la introspección profunda.
- **Los datos no se usan en bruto.** Lo que sale del catálogo y del canal ancho se **clasifica** y
  se **analiza a fondo** antes de entrar en un tren (ver
  [investigaciones/README § Después de recoger datos](../investigaciones/README.md#después-de-recoger-datos)).
- **El catálogo se guarda** en la carpeta del tren. Si cambia entre versiones del juego, el cambio
  se detecta comparando catálogos.

## Consecuencias

- Más fácil: añadir trenes, investigar campos y soportar trenes que «se describen distinto».
- Más difícil: el contrato necesita dos mensajes nuevos (`catalog` y `wide`) y una forma de nombrar
  rutas que no cambie entre sesiones.
- Hay que medir (R-03): cuánto tarda el catálogo al cargar y si el canal ancho repartido se nota.
- Afecta a H.6 (¿hace falta el mod laboratorio aparte?) y a la regla D2 de `mod-lua.md` («un campo
  entra en `tick` solo con versión de contrato nueva»): con suscripción, un campo nuevo es un dato,
  no una versión nueva.
