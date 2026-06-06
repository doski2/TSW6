import unittest
import time
from speed_governor import SpeedGovernor

class TestSpeedGovernor(unittest.TestCase):
    def test_stuck_at_station_acceleration(self):
        # Simula un tren atascado saliendo de la estación por culpa de una 
        # TARGET_ACCEL_MS2 envenenada
        gov = SpeedGovernor(target_mph=20.0)
        
        # Envenenar la calibración como pasó en el log
        gov.target_accel_ms2 = 0.132 
        
        # Inicializar el tren en salida
        gov.station_state = "DEPARTING"
        gov.throttle.notch = 1 # Tracción 1 en el Class 323 (notch interno 1)
        gov.brake.notch = 0
        
        # Simular lectura de la telemetría (tren parado, no puede arrancar)
        gov._api_accel = 0.0
        
        action = gov.decide(
            speed_mph=0.0,
            limit_mph=20.0,
            next_limit_mph=None,
            distance_next_m=None,
        )
        
        # Con el nuevo parche, la acción debe ser ACCELERATE, no HOLD
        # porque está a < 1.0 mph, a < 0.1 y no debe conformarse con Tracción 1.
        self.assertEqual(action, "ACCELERATE", 
                         "El tren se ha quedado atascado en HOLD al salir de la estación.")

    def test_p1_no_hardbrake_for_higher_limit(self):
        # Simula el bug donde el tren frenaba en emergencia al acercarse
        # a un límite superior al actual
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 4
        gov.brake.notch = 0
        gov._api_accel = 0.2
        
        # Velocidad 54 mph, acercándose a 55 mph
        # En el bug, esto causaba HARDBRAKE
        action = gov.decide(
            speed_mph=54.2,
            limit_mph=58.6,
            next_limit_mph=55.0,
            distance_next_m=20.0,
        )
        
        self.assertNotIn(action, ["HARDBRAKE", "BRAKE"], 
                         "El tren no debe frenar al acercarse a un límite mayor.")

    def test_p1_no_premature_hardbrake(self):
        # Simula el bug donde frenaba en emergencia al acercarse a un límite
        # inferior, pero estando aún a distancia prudencial (solo debería
        # frenar en servicio o coast, no HARDBRAKE)
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 5
        gov.brake.notch = 0
        gov._api_accel = 0.0
        
        # spd=51.9 next_lim=50.0 dist=83m bd=24m
        # En el log corrupto 23:07 causaba HARDBRAKE porque bd+react_m
        # era mayor que la distancia actual
        action = gov.decide(
            speed_mph=51.9,
            limit_mph=55.1,
            next_limit_mph=50.0,
            distance_next_m=83.0,
        )
        self.assertNotIn(action, ["HARDBRAKE"], 
                         "El tren no debe aplicar HARDBRAKE si todavía hay margen suficiente para el freno de servicio.")
        
    def test_ack_required_holds_brakes(self):
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 2
        gov.last_action = "BRAKE"
        
        action = gov.decide(
            speed_mph=52.0,
            limit_mph=50.0,
            next_limit_mph=50.0,
            distance_next_m=100.0,
            ack_required=True
        )
        self.assertIn(action, ["BRAKE", "HOLD"], 
                      "Durante un ACK activo, el tren debe seguir frenando si excede el límite")

    def test_ack_required_holds_speed_when_safe_below_limit(self):
        """Si se requiere ACK pero vamos a velocidad segura por debajo del límite de velocidad y sin freno activo, no debe frenar absurdamente."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 0
        gov.last_action = "HOLD"
        
        action = gov.decide(
            speed_mph=39.5,
            limit_mph=50.0,
            next_limit_mph=50.0,
            distance_next_m=100.0,
            ack_required=True
        )
        self.assertEqual(action, "HOLD", 
                         "Durante un ACK activo, si vamos a velocidad segura y sin freno metido, se debe mantener HOLD (no clavar frenos).")

    def test_downhill_no_brake_when_below_limit(self):
        # Simula el bug del 23:25 donde el tren iba a 41.5 mph en zona de 44.3
        # acercándose a 35.0 mph en bajada (-1.0%). Antes P1 bajaba effective_limit
        # a 35.0 de golpe y P2 frenaba en emergencia. Ahora effective_limit sigue
        # el perfil suave (~40.8) y el freno es gradual (BRAKE, no HARDBRAKE).
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 0
        gov._api_accel = 0.1
        
        # spd=41.5 lim=44.3 next_lim=35.0 dist=114m grad=-1.0%
        # El tren debe frenar suavemente (BRAKE) para seguir el perfil,
        # pero NUNCA en emergencia (HARDBRAKE).
        action = gov.decide(
            speed_mph=41.5,
            limit_mph=44.3,
            next_limit_mph=35.0,
            distance_next_m=114.0,
            gradient_pct=-1.0,
        )
        self.assertNotIn(action, ["HARDBRAKE"], 
                         "El tren no debe frenar en emergencia al aproximarse a un límite inferior en bajada.")
        # Verificar que effective_limit sigue el perfil, no salta a 35.0
        self.assertGreater(gov.effective_limit, 35.0,
                           "effective_limit debe seguir el perfil gradual, no bajar de golpe a 35.0")

    def test_braking_distance_accounts_for_acceleration(self):
        """Con aceleración positiva, la distancia de frenado debe ser mayor."""
        gov = SpeedGovernor(target_mph=60.0)
        # Sin aceleración
        d_static = gov.braking_distance(50.0, 30.0)
        # Con aceleración (el tren sigue ganando velocidad durante la transición)
        d_accel = gov.braking_distance(50.0, 30.0, current_accel_ms2=0.5)
        self.assertGreater(d_accel, d_static,
                           "La distancia de frenado debe ser mayor si el tren está acelerando.")

    def test_braking_distance_zero_accel_same_as_none(self):
        """Con aceleración 0 o None, la distancia debe ser igual."""
        gov = SpeedGovernor(target_mph=60.0)
        d_none = gov.braking_distance(50.0, 30.0)
        d_zero = gov.braking_distance(50.0, 30.0, current_accel_ms2=0.0)
        d_neg  = gov.braking_distance(50.0, 30.0, current_accel_ms2=-0.5)
        self.assertEqual(d_none, d_zero)
        self.assertEqual(d_none, d_neg)

    def test_p2_tsm_holds_when_already_decelerating(self):
        """En TSM/overspeed, si ya se está decelerando suficiente, no añadir más freno."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 2
        gov._api_accel = -0.5  # ya decelerando a -0.5 m/s² (> TARGET_DECEL)
        gov.target_decel_ms2 = 0.433 # Forzar constante para independizar del disco
        
        action = gov.decide(
            speed_mph=52.0,
            limit_mph=50.0,
            next_limit_mph=50.0,
            distance_next_m=200.0,
            supervision="tsm",
        )
        self.assertEqual(action, "HOLD",
                         "No debe añadir más freno si ya decelera a TARGET_DECEL o más.")

    def test_p2_downhill_holds_when_already_decelerating(self):
        """En bajada con overspeed, si ya decelera suficiente, no añadir más freno."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 1
        gov._api_accel = -0.5
        gov.target_decel_ms2 = 0.433 # Forzar constante para independizar del disco
        
        action = gov.decide(
            speed_mph=45.0,
            limit_mph=44.0,
            next_limit_mph=35.0,
            distance_next_m=200.0,
            gradient_pct=-1.5,
        )
        self.assertEqual(action, "HOLD",
                         "En bajada, no debe añadir más freno si ya decelera suficiente.")

    def test_cruise_recovers_when_losing_speed(self):
        """En crucero, si la velocidad cae por debajo del límite, debe acelerar suavemente."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 0
        gov._api_accel = -0.1  # perdiendo velocidad lentamente
        
        action = gov.decide(
            speed_mph=58.5,
            limit_mph=60.0,
            next_limit_mph=60.0,
            distance_next_m=500.0,
        )
        self.assertEqual(action, "ACCELERATE",
                         "Debe acelerar suavemente si está perdiendo velocidad por debajo del límite.")

    def test_cruise_coasts_when_slightly_above_limit(self):
        """En crucero, ligeramente por encima del límite debe cortar tracción."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 2
        gov.brake.notch = 0
        gov._api_accel = 0.2
        
        action = gov.decide(
            speed_mph=60.5,
            limit_mph=60.0,
            next_limit_mph=60.0,
            distance_next_m=500.0,
        )
        self.assertEqual(action, "COAST",
                         "Ligeramente por encima del límite debe cortar tracción.")

    def test_p1_passes_acceleration_to_braking_distance(self):
        """P1 debe pasar la aceleración actual a braking_distance."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 4
        gov.brake.notch = 0
        gov._api_accel = 0.4  # acelerando fuerte
        
        # Con aceleración positiva, bd es mayor → debería frenar antes
        action = gov.decide(
            speed_mph=55.0,
            limit_mph=60.0,
            next_limit_mph=40.0,
            distance_next_m=250.0,
        )
        # A 55 mph con 0.4 m/s² de aceleración, bd debería ser mayor
        # y posiblemente disparar COAST o BRAKE
        self.assertIn(action, ["COAST", "BRAKE", "HOLD"],
                      "P1 debe considerar la aceleración actual en su decisión.")

    def test_stopped_coldstart_timeout_when_doors_stuck_open(self):
        """Cold-start con doors_dmi=True debe hacer timeout en 3s y pasar a DEPARTING."""
        import time as _time
        gov = SpeedGovernor(target_mph=60.0)
        # Simular cold-start: el tren ya está en el andén
        gov.station_state = "STOPPED"
        gov.station_name = "Test Station"
        gov._we_stopped = False
        gov._doors_opened = True  # doors_dmi ya era True al arrancar
        gov._stopped_at = _time.time() - 4.0  # hace 4 segundos que entró
        
        _ = gov.decide(
            speed_mph=0.0,
            limit_mph=20.0,
            next_limit_mph=45.0,
            distance_next_m=271.0,
            stations=[{"name": "Test Station", "distance_m": 47, "platform_length_m": 227}],
            doors_dmi=True,  # puertas siguen abiertas según DMI
            doors_open=False,
        )
        self.assertEqual(gov.station_state, "DEPARTING",
                         "Cold-start con doors_dmi=True > 3s debe hacer timeout y pasar a DEPARTING.")

    def test_creep_to_station_when_stopped_before_platform(self):
        """Si el tren se detiene antes del andén en APPROACHING, debe activar creep y acelerar lentamente a 10 mph max."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = "APPROACHING"
        gov.station_name = "Test Station"
        gov.throttle.notch = 0
        gov.brake.notch = 0
        gov._api_accel = 0.0
        
        # El tren está parado antes del andén (distancia 120m, andén mide 100m, ventana es 50m)
        action = gov.decide(
            speed_mph=0.0,
            limit_mph=30.0,
            next_limit_mph=30.0,
            distance_next_m=800.0,
            stations=[{"name": "Test Station", "distance_m": 120.0, "platform_length_m": 100.0}],
            doors_open=False,
        )
        
        self.assertTrue(gov._creep_to_station, "Debe activar el modo creep si se para antes del andén.")
        self.assertEqual(gov.effective_limit, 10.0, "Durante el creep la velocidad límite debe limitarse a 10 mph max.")
        self.assertEqual(action, "ACCELERATE", "Debe pedir acelerar para iniciar el avance lento hacia el andén.")
        
        # Simular que el tren empieza a moverse (spd=2.0 > 1.5), el creep debe mantenerse (histéresis)
        action2 = gov.decide(
            speed_mph=2.0,
            limit_mph=30.0,
            next_limit_mph=30.0,
            distance_next_m=800.0,
            stations=[{"name": "Test Station", "distance_m": 110.0, "platform_length_m": 100.0}],
            doors_open=False,
        )
        self.assertTrue(gov._creep_to_station, "El creep debe mantenerse activo por histéresis mientras no entre en el andén.")
        self.assertEqual(gov.effective_limit, 10.0, "La velocidad límite de creep debe mantenerse a 10 mph.")

    def test_p1_critico_fullstop(self):
        """P1-CRITICO: dist ≤ 20m con exceso > 10mph → FULLSTOP."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 0
        gov._api_accel = 0.0

        action = gov.decide(
            speed_mph=55.0,
            limit_mph=60.0,
            next_limit_mph=40.0,
            distance_next_m=15.0,  # < 20m
        )
        self.assertEqual(action, "FULLSTOP",
                         "P1-CRITICO debe devolver FULLSTOP con dist ≤ 20m y exceso > 10mph.")

    def test_p1_emergencia_hardbrake(self):
        """P1-EMERGENCIA: dist ≤ 50m con exceso > 5mph → HARDBRAKE."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 0
        gov._api_accel = 0.0

        action = gov.decide(
            speed_mph=48.0,
            limit_mph=60.0,
            next_limit_mph=40.0,
            distance_next_m=45.0,  # < 50m, exceso = 8 > 5
        )
        self.assertEqual(action, "HARDBRAKE",
                         "P1-EMERGENCIA debe devolver HARDBRAKE con dist ≤ 50m y exceso > 5mph.")

    def test_p1_servicio_progressive(self):
        """P1-SERVICIO: dist ≤ bd → COAST/BRAKE progresivo (no HARDBRAKE directamente)."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 3
        gov.brake.notch = 0
        gov._api_accel = 0.0

        # dist=70: > 50m (no EMERGENCIA por dist), > bd*0.5=44 (no EMERGENCIA por bd)
        # but ≤ bd=88.7 → P1-SERVICIO zone
        action = gov.decide(
            speed_mph=52.0,
            limit_mph=55.0,
            next_limit_mph=45.0,
            distance_next_m=70.0,
        )
        self.assertIn(action, ["COAST", "BRAKE"],
                      "P1-SERVICIO ciclo 1 debe ser COAST o BRAKE, no HARDBRAKE.")
        self.assertNotEqual(action, "HARDBRAKE")

    def test_notch_8_stuck_handle_desync(self):
        """Si estamos en Notch 8 pero no aceleramos, el mando atascado debe dispararse (incluso en HOLD)."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.throttle.notch = 4  # Max power
        gov.brake.notch = 0
        gov._last_accel_notch = 4
        gov.last_action = "HOLD"  # El governor dice HOLD porque ya estamos a tope
        gov._api_accel = -0.1  # Decelerando a pesar de estar a tope
        
        # Simular force_neutral
        force_neutral_called = False
        def mock_force_neutral(hwnd, conn=None):
            nonlocal force_neutral_called
            force_neutral_called = True
        gov.force_neutral = mock_force_neutral
        
        hwnd = 12345
        
        # Ciclo 1-4: No debería disparar todavía (umbral = 4)
        for i in range(3):
            gov.last_control = 0
            # Simulamos que decide() devuelve HOLD porque ya estamos al máximo notch
            gov.apply_action("HOLD", hwnd, None)
            self.assertFalse(force_neutral_called, f"Ciclo {i+1}: No debería resetear aún")
        
        # Ciclo 4 -> Debe disparar porque seguimos en Notch 8 sin aceleración efectiva
        gov.last_control = 0
        gov.apply_action("HOLD", hwnd, None)
        
        self.assertTrue(force_neutral_called, 
                        "El sistema debería haber detectado que Notch 8 no da potencia (en HOLD) y resetear.")

    def test_force_neutral_cooldown(self):
        """Verifica que tras un force_neutral se ignora el atasco durante 5 segundos."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.throttle.notch = 4
        gov._last_accel_notch = 4
        gov._api_accel = -0.1
        
        # Simular que acabamos de hacer un sync
        gov._last_sync_t = time.time()
        
        # Mock de force_neutral para detectar si se llama OTRA VEZ
        force_neutral_called = False
        def mock_force_neutral(hwnd, conn=None):
            nonlocal force_neutral_called
            force_neutral_called = True
        gov.force_neutral = mock_force_neutral
        
        # Intentar disparar atasco (4 ciclos)
        for _ in range(5):
            gov.last_control = 0
            gov.apply_action("HOLD", 123, None)
            
        self.assertFalse(force_neutral_called, 
                         "No debería haber disparado un segundo reset durante el cooldown.")

    def test_force_neutral_anti_loop(self):
        """Verifica que tras 3 reseteos fallidos se deja de intentar (anti-loop)."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.throttle.notch = 4
        gov._last_accel_notch = 4
        gov._api_accel = -0.1
        
        force_neutral_calls = 0
        def mock_force_neutral(hwnd, conn=None):
            nonlocal force_neutral_calls
            force_neutral_calls += 1
            # Simular lo que hace force_neutral: incrementar contadores y setear tiempos
            gov._force_neutral_count += 1
            gov._last_force_neutral_t = time.time()
            gov._last_sync_t = time.time()
        
        gov.force_neutral = mock_force_neutral
        
        # Simular 4 intentos de reset (cada uno requiere 4 ciclos de atasco)
        # El 4º intento no debería ocurrir por el límite de 3
        for attempt in range(4):
            # Forzar que NO estemos en cooldown para que el primer ciclo sea procesado
            gov._last_sync_t = 0 
            for _ in range(4):
                gov.last_control = 0
                # Usamos un hwnd ficticio para que apply_action lo pase a force_neutral
                gov.apply_action("HOLD", 123, None)
        
        self.assertEqual(force_neutral_calls, 3, 
                         "Debería haber parado tras 3 intentos de reset.")

    def test_p1_reset_cycles_on_limit_change(self):
        """P1 debe resetear p1_nomarker_cycles cuando next_limit cambia > 2 mph."""
        gov: SpeedGovernor = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 0
        gov._api_accel = 0.0

        # First call with next_limit=45
        gov.decide(speed_mph=52.0, limit_mph=55.0,
                   next_limit_mph=45.0, distance_next_m=40.0)
        # Cycles incremented
        cycles_after_first = gov.p1_nomarker_cycles

        # Second call with next_limit=30 (change > 2 mph) → should reset
        gov.decide(speed_mph=52.0, limit_mph=55.0,
                   next_limit_mph=30.0, distance_next_m=40.0)
        # The reset happens before the new P1 logic runs, so a fresh cycle count
        # This tests that the counter doesn't carry over from a different limit
        self.assertLessEqual(gov.p1_nomarker_cycles, 1,
                             "Cycles debe resetearse cuando next_limit cambia > 2 mph")

    def test_p1_gradient_scales_react_m(self):
        """En pendiente, react_m debe ser mayor (escalado por gradiente)."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 0
        gov._api_accel = 0.0

        # Sin pendiente: action at certain distance
        action_flat = gov.decide(
            speed_mph=50.0, limit_mph=60.0,
            next_limit_mph=40.0, distance_next_m=200.0,
            gradient_pct=0.0,
        )
        elim_flat = gov.effective_limit

        # Con bajada: effective_limit debe ser menor (más conservador)
        gov2 = SpeedGovernor(target_mph=60.0)
        gov2.station_state = None
        gov2.throttle.notch = 0
        gov2.brake.notch = 0
        gov2._api_accel = 0.0
        action_hill = gov2.decide(
            speed_mph=50.0, limit_mph=60.0,
            next_limit_mph=40.0, distance_next_m=200.0,
            gradient_pct=-2.0,
        )
        elim_hill = gov2.effective_limit

        self.assertLessEqual(elim_hill, elim_flat,
                             "En bajada, effective_limit debe ser menor (más conservador).")

    def test_p2_over_critico_hardbrake(self):
        """P2 OVER-CRITICO: speed > limit + 3 → HARDBRAKE."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 0
        gov._api_accel = 0.0

        action = gov.decide(
            speed_mph=64.0,
            limit_mph=60.0,
            next_limit_mph=60.0,
            distance_next_m=500.0,
        )
        self.assertEqual(action, "HARDBRAKE",
                         "P2 OVER-CRITICO debe devolver HARDBRAKE cuando speed > limit + 3.")

    def test_p2_rain_tightens_bands(self):
        """En lluvia, P2 OVER-CRITICO se activa antes (2 mph menos)."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 0
        gov._api_accel = 0.0
        gov.set_rain_intensity(0.8)

        # Con lluvia, over_critico = (3.0 - 2.0) * 1.0 = 1.0
        # speed = 61.5 > limit(60) + 1.0 → HARDBRAKE
        action = gov.decide(
            speed_mph=61.5,
            limit_mph=60.0,
            next_limit_mph=60.0,
            distance_next_m=500.0,
        )
        self.assertEqual(action, "HARDBRAKE",
                         "En lluvia, OVER-CRITICO se activa con exceso menor.")

    def test_p2_critical_gradient_hardbrake(self):
        """Gradiente crítico (effective_decel < 0.3) fuerza HARDBRAKE."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 0
        gov.brake.notch = 0
        gov._api_accel = 0.1  # no decelerating

        # grad=-3.5%: g_comp = -0.343, eff_decel = max(1.071-0.343, 0.095) = 0.728
        # Not critical. Use rain to lower eff_decel further.
        gov.set_rain_intensity(0.95)
        # eff_max_decel = 1.071 * (1 - 0.95*0.35) = 1.071 * 0.6675 = 0.715
        # with grad=-4.5%: g_comp = -0.441, eff = max(0.715-0.441, 0.095) = 0.274 < 0.3 → critical!
        action = gov.decide(
            speed_mph=48.0,
            limit_mph=45.0,
            next_limit_mph=45.0,
            distance_next_m=500.0,
            gradient_pct=-4.5,
        )
        self.assertEqual(action, "HARDBRAKE",
                         "Gradiente crítico con lluvia debe forzar HARDBRAKE.")

    def test_p3_gradient_compensation(self):
        """P3 debe ajustar target_accel por gradiente (en subida necesita más potencia)."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 1
        gov.brake.notch = 0
        # Accel below normal target (0.298) but above adjusted for uphill
        gov._api_accel = 0.20

        # En subida +2%: target_accel_adj = 0.298 + 9.81*2/100 = 0.298 + 0.196 = 0.494
        # a(0.20) < 0.494 - 0.18 = 0.314 → should want more throttle
        action = gov.decide(
            speed_mph=30.0,
            limit_mph=60.0,
            next_limit_mph=60.0,
            distance_next_m=500.0,
            gradient_pct=2.0,
        )
        self.assertEqual(action, "ACCELERATE",
                         "En subida P3 debe pedir más tracción para compensar el gradiente.")

    def test_p3_proximity_ceiling(self):
        """P3 cuando error < 3 mph debe limitar aceleración a 0.15 m/s²."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 2
        gov.brake.notch = 0
        # Aceleración actual 0.25 > target ajustado 0.15 (proximity ceiling)
        gov._api_accel = 0.25

        # error = 60 - 58 = 2.0 < 3.0 → ceiling at 0.15
        # a(0.25) > 0.15 + 0.18 = 0.33? No, 0.25 < 0.33 → HOLD
        # Actually: a(0.25) > target(0.15) + tolerance(0.18) = 0.33? No
        # a(0.25) < target(0.15) - tolerance(0.18)? 0.25 < -0.03? No
        # So target_t = current notch (2) → HOLD (error ≤ 1.5 path handles this)
        # Let me use error = 2.5 to hit the acceleration phase
        action = gov.decide(
            speed_mph=57.5,
            limit_mph=60.0,
            next_limit_mph=60.0,
            distance_next_m=500.0,
        )
        # With error=2.5 < 3, ceiling=0.15, a=0.25 > 0.15+0.18=0.33? No
        # But 0.25 > 0.15 and within tolerance → HOLD (notch stays)
        # With throttle=2 and target_t=2 → HOLD (correct behavior: not accelerating more)
        self.assertNotEqual(action, "ACCELERATE",
                            "Cerca del límite, P3 no debe pedir más aceleración si ya supera el techo.")

    def test_p3_anti_oscillation(self):
        """P3 anti-oscilación: no debe cambiar dirección inmediatamente."""
        gov = SpeedGovernor(target_mph=60.0)
        gov.station_state = None
        gov.throttle.notch = 3
        gov.brake.notch = 0
        # High accel → target_t would be 2 (wants to reduce = "down")
        gov._api_accel = 0.55  # > 0.298 + 0.18 = 0.478 → reduce notch
        gov._p3_last_direction = "up"  # was going up before
        gov._p3_direction_hold = 0

        # error = 55 - 50 = 5.0, within caps: error ≤ 8 → max notch 2
        # accel high → target_t = max(3-1, 0) = 2, cap: min(2,2)=2
        # throttle(3) > target_t(2) → wants COAST (direction = "down")
        # anti-oscillation: last was "up", now "down" → HOLD
        action = gov.decide(
            speed_mph=50.0,
            limit_mph=60.0,
            next_limit_mph=60.0,
            distance_next_m=500.0,
        )
        self.assertEqual(action, "HOLD",
                         "Anti-oscilación debe impedir cambio de dirección inmediato.")

if __name__ == '__main__':
    unittest.main()
