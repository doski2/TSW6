import unittest
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

if __name__ == '__main__':
    unittest.main()
