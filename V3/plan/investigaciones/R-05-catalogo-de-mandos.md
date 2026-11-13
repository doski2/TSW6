# R-05 — Catálogo de mandos por tren (nombres de palancas y ejes)

- **Estado:** En curso (primera fuente leída: 2026-11-13)
- **Desbloquea:** B.1, B.2, H.8, paquetes de tren ([0003](../decisiones/0003-estructura-por-tren-y-familia.md)),
  suscripción del mod ([0004](../decisiones/0004-el-mod-lee-todo-python-elige.md))
- **Necesita juego:** para confirmar, sí; esta primera parte no.

## Pregunta

¿Cómo se llama en el juego cada palanca o eje de cada tren, qué rango tiene y si va por peldaños?
Para la v1 (A.3: solo frena) importan sobre todo los **mandos de freno** y las **palancas
combinadas** tracción/freno.

## Fuente 1: `tsw-controller-app` (Liah Martens)

<https://github.com/LiahMartens/tsw-controller-app> (Go + mod UE4SS en C++, activo: último push
2026-10-17). Propuesta por el usuario el 2026-11-13. V2 ya la usaba como **receta** de escritura
(`docs/reference/DRIVERINPUT_API.md`), pero no se había aprovechado su **catálogo de perfiles**.

> ⚠️ **El repositorio no declara licencia.** Se pueden leer y citar los **datos** (nombres, rangos),
> pero **no se copian sus ficheros ni su código** a este repo. La tabla de abajo es un extracto
> hecho por nosotros.

### Qué es un perfil

`shared-profiles/*.tswprofile` (140 perfiles, ~70 trenes distintos) une los botones de un mando
físico con controles del juego. Las asignaciones `direct_control` llevan:

- `controls`: **nombre del control en el juego**. Es el nombre del `VirtualHIDComponent` del tren:
  el mod lo busca con `RailVehicle.FindVirtualHIDComponent(FName(nombre))`.
- `input_value`: `min`, `max` y, si va por peldaños, `steps` (lista) o `step` (tamaño del paso).
- `{SIDE}` en el nombre: se cambia por el lado de cabina (`F`/`B` por defecto), por ejemplo
  `Throttle_F`.
- `rail_class_information` (opcional, solo en 36 de 140): la **clase del juego**
  (p. ej. `RVM_BKR_LUL_72Stock_DM_Mk2_32_C`), que es lo que nuestro `hello` llama `vehicle_class`.

### Resultados

- FACT: **135 nombres de control distintos.** Los más repetidos: `Throttle_{SIDE}`,
  `MasterController`, `TrainBrake_{SIDE}`, `DynamicBrake_{SIDE}`, `Throttle`, `TrainBrake`,
  `DriversBrake_{SIDE}`, `AutomaticBrake`, `IndependentBrake`.
- FACT: **no hay nombres estándar.** El mismo concepto se llama distinto según el tren
  (`TrainBrake`, `DriversBrake`, `AutomaticBrake`, `AutoBrake`, `BrakeController`,
  `Westcode3StepBrake`, `Train_Vacuum_Brake_{SIDE}`…). Confirma
  [0004](../decisiones/0004-el-mod-lee-todo-python-elige.md): el paquete del tren tiene que unir
  el nombre genérico con el nombre real.
- FACT: **la 323 coincide con lo que ya sabemos.** `PowerBrakeHandle`, rango `-0.6..1`, 8 peldaños
  (`-0.6, -0.4, -0.2, 0, 0.25, 0.5, 0.75, 1`). Los negativos son freno.
- FACT: **la M3 usa `MasterController`** (`0.1..1`) y además `BrakeCharging` (botón de cargar
  frenos). Otro perfil de la M3 da 15 peldaños en `0.27..1`.
- FACT: aparecen **familias de mando** que encajan con [0003](../decisiones/0003-estructura-por-tren-y-familia.md):
  palanca combinada con negativos = freno (`PowerHandle` de las 375/377/387/465/390/395, 323),
  freno automático + independiente (locomotoras de EE. UU.), freno de tren + dinámico (BR alemanas
  y ÖBB), `IrregularLever` (palancas con peldaños irregulares).
- FACT (código del mod): escribe con `SetCurrentInputValue`, `SetNormalisedInputValue` o
  `SetPushedState`, y **lee por eventos**: engancha `VirtualHIDComponent:InputValueChanged` en vez
  de leer en cada tick. Esto es interesante para el presupuesto de 1 ms (R-03, H.4).
- INFERENCE: los rangos son los que eligió cada autor para **su mando físico**, no siempre el rango
  completo del control. Valen como punto de partida, no como verdad.
- UNKNOWN: qué nombres siguen vigentes en TSW6. Muchos perfiles son de TSW4/TSW5.

### Tabla: mandos de freno y combinados por perfil

Sin variantes de mando físico concreto (Logitech, Zuiki, carpetas de autores). Los valores son
los de la primera asignación `direct_control` del perfil.

| Perfil | Clase del juego (si el perfil la da) | Mandos de freno / combinados [min..max, peldaños] |
| ------ | ----------------------------------- | ------------------------------------------------- |
| `1972mk2tubestock` | `RVM_BKR_LUL_72Stock_DM_Mk2_32_C` | `TractionBrakeController` [-0.45..0.35, 8 peldaños] |
| `acela` | `RVM_BPE_AMTK_Acela_PowerCar_A_C` | `AutomaticBrakeLever` [0..0.75] |
| `acs64` | `RVM_NYT_AMTK_ACS-64_C` | `MasterController_{SIDE} (IrregularLever)` [0..1]; `AutomaticBrake_{SIDE} (IrregularLever)` [0..0.45]; `IndependentBrake_{SIDE} (IrregularLever)` [0.1..1] |
| `acs64_boston_sprinter` | `RVM_BPE_AMTK_ACS-64_C` | `MasterController_{SIDE} (IrregularLever)` [0..1]; `AutomaticBrake_{SIDE} (IrregularLever)` [0..0.75]; `IndependentBrake_{SIDE} (IrregularLever)` [0.1..1] |
| `allegra` | `RVM_RhB_ABe_8_12_EWA_C` | `IrregularLever_Throttle_Brake` [0..1]; `IrregularLever_TrainBrake` [0..0.8] |
| `alp45dp` | `RVM_MRT_NJT_ALP45DP_C` | `MasterController` [0..1]; `AutomaticBrake` [0..0.6, paso 0.2]; `IndependentBrake` [0.1..1] |
| `alp46` | `RVM_MRT_NJT_ALP-46_C` | `PowerHandle_{SIDE}` [0.5..1]; `AutomaticBrake_{SIDE}` [0..0.6, paso 0.2]; `IndependentBrake_{SIDE}` [0.1..1] |
| `amfleet_cabcar` | `RVM_NYT_AMTK_CabCar_C` | `AutomaticBrake` [0..0.5] |
| `awc_class805` | `RVM_805_DPTS_C` | `PowerHandle(IrregularLever)` [-0.9..1] |
| `bi_level_cabcar_ctx` | `RVM_SFJ_CT_BiLevelCoach_CabCar_C` | `PowerHandle` [0.199..1, 9 peldaños]; `AutomaticBrake` [0..0.7] |
| `bilevel_rotem_car` | `RVM_ALV_ML_RotemCars_CabCar_C` | `MasterController` [0..1, paso 0.125]; `AutomaticBrake` [0..0.549, 5 peldaños] |
| `bl36` | — | `AutomaticBrake` [0..0.5550000071525574, 3 peldaños]; `ThrottleAndBrakeHandle` [0.125..1.0, 9 peldaños]; `IndependentBrake` [0..1, 3 peldaños] |
| `bnsf_es44c4` | `RVM_CJP_BNSF_ES44C4_C` | `AutomaticBrake(Lever)` [0..0.6]; `IndependentBrake(Lever)` [0.25..1] |
| `bnsf_sd40` | `RVM_CJP_BNSF_SD40-2_C` | `AutomaticBrake` [0..0.7]; `IndependentBrake` [0.25..1] |
| `br110` | `RVM_BRO_DB_BR110_399_C` | `TrainBrake_{SIDE}` [0.1..0.8, 8 peldaños]; `DynamicBrake_{SIDE}` [0..1, 9 peldaños]; `LocoBrake_{SIDE}` [0..1] |
| `br111` | `RVM_SRM_DB_BR111_C` | `TrainBrake_{SIDE}` [0.1..0.8, 8 peldaños]; `DynamicBrake_{SIDE}` [0..1, 8 peldaños] |
| `br112` | `RVM_HBK_DB_BR112_C` | `DriversBrake_{SIDE}` [0.1..0.75, 9 peldaños] |
| `br114` | `RVM_FTF_DB_BR114_C` | `DriversBrake_{SIDE}` [0.1..0.75, 9 peldaños] |
| `br143_dresden_leipzig` | `RVM_DLG_DB_BR143_C` | `DriversBrake_{SIDE}` [0.1..0.75, 9 peldaños] |
| `br143_nahverkehr_dresden` | `RVM_DRA_DB_BR143_C` | `DriversBrake_{SIDE}` [0.1..0.8, 11 peldaños] |
| `br146` | — | `TrainBrake_{SIDE}` [0.1..0.8, 10 peldaños]; `DynamicBrake_{SIDE}` [0.1..0.8, 10 peldaños] |
| `br155` | — | `DriversBrake_{SIDE}` [0.1..0.85, 11 peldaños] |
| `br182_185` | `RVM_DLG_DB_BR185_C`, `RVM_DRA_MRCE_BR185-5_C`, `RVM_KWG_DB_BR185_C`, `RVM_MRCE_BR182_C` | `TrainBrake_{SIDE}` [0.1..0.8, 10 peldaños]; `DynamicBrake_{SIDE}` [0.1..0.8, 10 peldaños] |
| `br193` | `RVM_FTF_DB_Vectron_C`, `RVM_FTF_FT_Vectron_C` | `MasterController_{SIDE}` [0..1]; `TrainBrake_{SIDE}` [0.1..0.9, 10 peldaños] |
| `br363_365` | — | `DriversBrakeValve_R` [0.25..0.73, 4 peldaños] |
| `br401` | — | `TrainBrake_{SIDE}` [0.1..0.8] |
| `br411_403_406` | — | `TrainBrake` [0..0.81] |
| `br423_425_430` | — | `MasterController` [0.1..1] |
| `br442_1442` | — | `ThrottleAndBrake (Irregular Lever)` [-1..1]; `TrainBrake (Irregular Lever)` [0..1] |
| `br463_nwagen` | — | `DynamicBrake_{SIDE}` [0..1, 9 peldaños] |
| `br628` | — | `TrainBrake` [0.1..0.8] |
| `br642` | — | `ThrottleAndBrakeHandle` [0.1..1]; `TrainBrakeHandle` [0..1, 3 peldaños] |
| `class08` | — | `DriversBrake` [0..0.8]; `DirectBrake` [0..1] |
| `class101` | — | `DriversBrakeValve` [0..1] |
| `class142` | — | `Westcode3StepBrake` [0..0.75, paso 0.25] |
| `class150` | — | `TrainBrake (Irregular Lever)` [0..0.75, paso 0.25] |
| `class150_gwr` | `RVM_GWR_Class150_DMS_C` | `TrainBrake_IrregularLever` [0..0.75, paso 0.25] |
| `class158` | — | `AutoBrake` [0..0.75, paso 0.25] |
| `class166` | — | `ThrottleAndBrake (Irregular Lever)` [-0.75..1, 11 peldaños] |
| `class170` | — | `IrregularLever_ThrottleBrake` [0.2..1, 11 peldaños] |
| `class20` | — | `TrainBrake_{SIDE} (IrregularLever)` [0.1..0.79]; `LocoBrake_{SIDE} (SimpleLever)` [0..1] |
| `class31` | — | `DriversBrake_{SIDE} (IrregularLever)` [0.1..0.79]; `StraightBrake_{SIDE} (SimpleLever)` [0..1] |
| `class314` | — | `BrakeController` [0..0.75, paso 0.25] |
| `class323` | — | `PowerBrakeHandle` [-0.6..1, 8 peldaños] |
| `class350` | — | `IrregularLever_ThrottleBrake` [0.05..1] |
| `class375_377_387` | — | `PowerHandle` [-0.6..1, 8 peldaños] |
| `class37_40_45_47` | — | `DriversBrake_{SIDE} (IrregularLever)` [0.1..0.79]; `StraightBrake_{SIDE} (SimpleLever)` [0..1] |
| `class390` | — | `PowerHandle` [-0.75..1, 11 peldaños] |
| `class395` | — | `PowerHandle` [-0.9..1, 8 peldaños] |
| `class43_gwr` | — | `TrainBrake (IrregularLever)` [0..6, paso 1] |
| `class465` | — | `PowerHandle` [-0.6..1, 8 peldaños] |
| `class66` | — | `{SIDE}_DirectBrake (Irregular Lever)` [-1..1, paso 1] |
| `class710` | — | `TractionBrakeControl` [-0.75..1] |
| `class800_801` | — | `PowerHandle(IrregularLever)` [-0.9..1] |
| `ctc3_cabcar` | — | `AutomaticBrake_26C` [0..0.7] |
| `db766` | — | `TrainBrake` [0.1..0.8, paso 0.05]; `DynamicBrake` [0.1..0.8, paso 0.05]; `DirectBrake` [0..1, paso 0.5] |
| `emd_f125` | — | `MasterController` [0.5..1, 9 peldaños]; `AutomaticBrakeLever` [0..0.4]; `IndependentBrakeLever` [0.1..1] |
| `f40ph` | — | `AutomaticBrake` [0..0.7]; `IndependentBrake` [0.1..1] |
| `gallery_cabcar` | — | `AutomaticBrake` [0..0.6, paso 0.2]; `DynamicBrake` [0..1] |
| `ge4_4` | — | `Train_Vacuum_Brake_{SIDE}` [0..0.9]; `LocoBrake_{SIDE}` [0..1] |
| `gp38` | — | `AutomaticBrake` [0..0.7]; `IndependentBrake` [0.25..1] |
| `hsp46` | — | `MasterController` [0..1, paso 0.125]; `AutomaticBrake` [0..0.8]; `IndependentBrake` [0.1..1] |
| `icm3_koploper` | — | `TrainBrake` [0.3..0.8, 8 peldaños] |
| `m3` | — | `MasterController` [0.1..1]; `BrakeCharging`  |
| `m7` | `RVM_LIRR_M7-A_C`, `RVM_NYH_MNR_M7a-A_C` | `MasterController` [0.1..1, 7 peldaños]; `BrakeCharging`  |
| `m9` | `RVM_LIRREX_M9-A_C` | `MasterController` [0.1..1] |
| `mp36` | — | `AutomaticBrake` [0..0.8]; `IndependentBrake` [0.1..1] |
| `multilevel_cabcar_njt` | — | `MasterController` [0..1, paso 0.1]; `AutomaticBrake` [0..0.6, paso 0.2] |
| `njt-arrow3` | `RVM_MRT_NJT_ArrowIII_CabCarBase_C` | `AutomaticBrake_26C` [0..1] |
| `obb1116` | — | `TrainBrake_{SIDE}` [0.1..0.8, 10 peldaños]; `DynamicBrake_{SIDE}` [0.1..0.8, 10 peldaños] |
| `obb4024` | — | `TrainBrake` [0..0.75, paso 0.25]; `MasterController` [0.1..1] |
| `rabe523` | — | `TrainBrake (Irregular Lever)` [0..0.8] |
| `rotem_ctc5` | — | `MasterController` [0..1, paso 0.125]; `AutomaticBrake` [0..0.7]; `IndependentBrake` [0..1] |
| `sng3_sprinter` | — | `MasterController` [-0.9..1] |
| `tgv_duplex` | — | `PowerHandle` [-1..1]; `TrainBrake`  |

## Siguiente paso

1. **Clasificar** (proceso de [investigaciones/README](README.md#después-de-recoger-datos)): cada
   nombre como `candidato` hasta comprobarlo en el juego, agrupado por familia de mando.
2. **Comprobar en el juego** con el catálogo del mod ([0004](../decisiones/0004-el-mod-lee-todo-python-elige.md))
   los trenes que tengas: ¿existe el nombre?, ¿el rango real coincide?
3. Ver si su **cab debugger** (lectura por `InputValueChanged`) sirve de modelo para nuestro
   catálogo y para leer sin gastar tiempo en cada tick.
4. Pendiente: ¿qué trenes tienes tú instalados? Así se prioriza la tabla.
