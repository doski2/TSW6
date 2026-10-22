# Trenes del DLC instalado vs paquetes V2 (2026-10-23)

Fuente: `steamapps\appmanifest_3656800.acf` (63 DLC instaladas) y los paks de `Content\DLC`.
Solo lo **instalado**; lo comprado y sin descargar no aparece. La columna «familia» es una
**hipótesis por el nombre** hasta sondear el tren con `GetData` (ver `VEHICLE_LAB.md`).

## Paquetes que existen

| Paquete `data/vehicles/` | Match                               | Layout                                                        | Perfil aprendido (`logs/profiles/`) |
| ------------------------ | ----------------------------------- | ------------------------------------------------------------- | ----------------------------------- |
| `class_323.json`         | `RVM_BCC_WRM_Class323_DMS_A_C`      | `combined`, muescas                                           | `…Class323_DMS_A_C`, `…dms_b_c`     |
| `m3a_mnr.json`           | `RVM_NYH_MNR_M3a` (A/B por prefijo) | `combined`, eje analógico (`brake_input` 0,72/0,64/0,45/0,27) | `m3a-a_c`, `m3a-b_c`                |

Deuda conocida: `m3a_mnr.json` aún hereda `physics` de la 323 («pendiente de medir en M3A»).

## Trenes instalados sin paquete

| Tren / ruta (DLC)                             | Familia probable                                                   | Riesgo para la interfaz actual                 |
| --------------------------------------------- | ------------------------------------------------------------------ | ---------------------------------------------- |
| Class 700, Class 220 (UK)                     | combinada por muescas, cercana a la 323                            | bajo: dato nuevo, mismo adaptador              |
| Class 20, 33, 52, 66 (UK diésel)              | acelerador + freno independiente                                   | **medio**: tracción y freno separados          |
| SD40, F7, F59PH, P36PH, ALP45DP (EE. UU.)     | throttle por muescas + freno independiente (+ dinámico en algunas) | **alto**: freno dinámico y neumático separados |
| BR 155, 182, 363, 294, 204, 423, Vectron (DE) | tracción/freno separados, freno eléctrico                          | **alto**                                       |
| LIRR (EE. UU.)                                | probable M7: analógico como el M3a                                 | bajo-medio                                     |
| Bakerloo (metro)                              | controlador propio                                                 | desconocido                                    |

## Rutas instaladas

- **EE. UU.:** Harlem Line, Long Island Rail Road, Boston–Providence, Boston–Worcester,

  Cajon Pass, Clinchfield, Morristown, Sand Patch Grade, Sherman Hill, Metrolink Antelope Valley,
  SF–San Jose.

- **UK:** London–Brighton, London–Faversham, Leeds–Manchester, Cardiff Commuter,

  Darlington–Saltburn, Glasgow Cathcart, Cross City Line, EastCoastway, Paddington–Reading,
  West Somerset Railway, Bakerloo.

- **DE/EU:** Dresden–Leipzig, Dresden–Riesa, Hamburg–Lübeck, Köln–Aachen, Leipzig S-Bahn,

  Main–Spessart, Maintalbahn, Mannheim–Kaiserslautern, Munich–Augsburg, Rhine–Ruhr Nord,
  Wuppertal, Semmeringbahn, Zwolle–Groningen, Marseille–Avignon, Riviera Line.

## Para decidir «archivo por tren» o «por familia»

Sondear **un representante por familia** antes de separar código:

1. Diésel EE. UU. con freno dinámico (F59PH o SD40).
2. Eléctrico alemán (BR 155 o Vectron).
3. Metro (Bakerloo) o unidad UK combinada (Class 700).

Por cada uno: capturar controles (`VEHICLE_LAB.md`), anotar si el mando cabe en `NotchAdapter` /
`MCAdapter`. Criterio: **operación nueva → adaptador nuevo; solo números nuevos → JSON**.
