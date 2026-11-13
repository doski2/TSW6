# Ideas

Backlog sin compromiso. Cualquier idea entra aquí; se revisa al cerrar cada fase y, si se aprueba,
pasa al [plan de trabajo](../PLAN_DE_TRABAJO.md). Formato: título, una o dos frases, de dónde sale.

## Producto

- **Modo asistente.** Mostrar la recomendación (frena ahora, B2 en 300 m) sin tocar mandos. Útil para
  validar el motor y para jugadores que quieren conducir ellos.
- **Conducción por horario.** Ajustar la velocidad para llegar a la hora exacta, no solo "lo antes
  posible".
- **Conducción ecológica.** Minimizar consumo/frenadas usando deriva (coast) antes de cartel.
- **Perfiles de estilo.** Conservador / normal / agresivo (márgenes y deceleración objetivo).
- **Informe post-servicio.** Puntuación de la sesión: precisión de parada, excesos, puntualidad.

## Plataforma

- **Simulador offline.** Ejecutar el motor contra un tren simulado sin abrir el juego, con rutas
  sintéticas (cartel, andén, pendiente).
- **Mapa de ruta por escenario** (usuario, 2026-11-13). Al conducir un escenario, guardar dónde
  están (por odómetro) las paradas, los semáforos/señales, los límites y el desnivel. Varias pasadas
  se juntan en un mapa por ruta (carpeta por ruta, como la de cada tren) y se puede ver como página
  con el perfil de la línea. Usos: frenar antes y mejor en la v1 (pendiente conocida, parada antes
  de que salga en el HUD), revisar sesiones y, más adelante, ser el «escenario» del simulador
  offline. Con mapa + física del tren se podría entrenar **PPO** sin el juego; con mapa + logs de
  conducción se tienen las entradas para **BC** (clonado de conducción). Los datos salen del canal
  ancho ([0004](../decisiones/0004-el-mod-lee-todo-python-elige.md)); falta saber qué expone el
  juego (R-11).
- **Grabación y replay universal.** Toda sesión se graba y se puede reproducir paso a paso en el
  panel web.
- **Asistente para añadir trenes.** Flujo guiado: abrir el lab, capturar mandos, generar el paquete,
  medir deceleración, validar.
- **Plugins de política.** Nuevas reglas (p. ej. PZB) como módulos que se registran, sin tocar el
  árbitro.
- **Panel en el móvil.** Ver el estado del tren desde otro dispositivo de la red local.

## Comunidad (si A.4 = publicable)

- Instalador para Windows, actualizador del mod Lua, catálogo compartido de paquetes de tren.
