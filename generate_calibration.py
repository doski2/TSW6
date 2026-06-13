#!/usr/bin/env python3
"""
Genera calibration.json procesando logs existentes del autopilot.
"""

import re
import json
from datetime import datetime
from online_learner import EMA_ALPHA, MIN_SAMPLES, MIN_STABLE_S, MIN_DV_MPH, MAX_GRAD_PCT, MIN_SPEED

def parse_log_line(line):
    """Extrae timestamp, spd, notch, grad de una línea de log del autopilot."""
    # Formato: 23:24:57.418 [tsw.autopilot ] DEBUG   spd= 15.4 ... notch=5 ... grad=+0.0%
    match = re.search(r'(\d{2}:\d{2}:\d{2}\.\d{3}).*spd=\s*([\d.]+).*notch=(\d+).*grad=([+-]?[\d.]+)%', line)
    if match:
        timestamp_str = match.group(1)
        speed = float(match.group(2))
        notch = int(match.group(3))
        grad = float(match.group(4))
        # Convertir timestamp a segundos desde midnight
        time_obj = datetime.strptime(timestamp_str, '%H:%M:%S.%f')
        timestamp = time_obj.hour * 3600 + time_obj.minute * 60 + time_obj.second + time_obj.microsecond / 1e6
        return timestamp, speed, notch, grad
    return None

def process_log(log_path, output_path=None):
    """Procesa un log y genera calibration.json."""
    # Leer todas las líneas válidas
    samples = []
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            parsed = parse_log_line(line)
            if parsed:
                samples.append(parsed)
    
    print(f"Leídas {len(samples)} muestras del log")
    
    # Ordenar por timestamp
    samples.sort(key=lambda x: x[0])
    
    # Normalizar timestamps para que empiecen en 0
    if samples:
        base_time = samples[0][0]
        samples = [(t - base_time, s, n, g) for t, s, n, g in samples]
    
    # Implementar lógica del learner directamente con timestamps del log
    _ema = {}
    _n = {}
    _window = []
    
    _BRAKE_NOTCHES = (1, 2, 3)
    _MAX_NOTCH = 0
    _COAST_NOTCH = 4
    _TRACTION_LOW = (5, 6)
    _TRACTION_NOTCHES = (7, 8)
    _OBSERVED = {_MAX_NOTCH, *_BRAKE_NOTCHES, _COAST_NOTCH,
                 *_TRACTION_LOW, *_TRACTION_NOTCHES}
    
    for timestamp, speed, notch, grad in samples:
        _window.append((timestamp, speed, notch, grad, None))
        
        # Purgar entradas antiguas (ventana de MIN_STABLE_S + 1.5 segundos)
        cutoff = timestamp - (MIN_STABLE_S + 1.5)
        _window = [(t, v, n, g, a) for t, v, n, g, a in _window if t >= cutoff]
        
        if len(_window) < 4:
            continue
        
        # Filtro: notch estable en toda la ventana
        notches_in_window = [n for _, _, n, _, _ in _window]
        if len(set(notches_in_window)) != 1:
            continue
        
        # Filtro: solo notches de interés
        if notch not in _OBSERVED:
            continue
        
        # Filtro: duración mínima
        t0 = _window[0][0]
        t1 = _window[-1][0]
        if t1 - t0 < MIN_STABLE_S:
            continue
        
        # Filtro: gradiente plano
        if max(abs(g) for _, _, _, g, _ in _window) > MAX_GRAD_PCT:
            continue
        
        # Filtro: velocidad mínima
        if min(v for _, v, _, _, _ in _window) < MIN_SPEED:
            continue
        
        # Filtro: cambio de velocidad apreciable
        speeds = [v for _, v, _, _, _ in _window]
        dv = speeds[-1] - speeds[0]
        if abs(dv) < MIN_DV_MPH:
            continue
        
        # Medir aceleración
        api_vals = [a for _, _, _, _, a in _window if a is not None]
        if api_vals:
            measured = sum(api_vals) / len(api_vals)
        else:
            measured = dv * 0.44704 / (t1 - t0)
        
        # Actualizar EMA
        if notch not in _ema:
            _ema[notch] = measured
            _n[notch] = 1
        else:
            _ema[notch] = EMA_ALPHA * measured + (1 - EMA_ALPHA) * _ema[notch]
            _n[notch] = min(_n[notch] + 1, 9999)
        
        print(f"Learner notch={notch}  a_medida={measured:.3f}  a_ema={_ema[notch]:.3f}  n={_n[notch]}")
        _window.clear()
    
    # Generar constantes
    def _trusted_abs(notch_val):
        if _n.get(notch_val, 0) >= MIN_SAMPLES and notch_val in _ema:
            return abs(_ema[notch_val])
        return None
    
    def _trusted_avg(notches):
        vals = [v for n in notches if (v := _trusted_abs(n)) is not None]
        return sum(vals) / len(vals) if vals else None
    
    result = {}
    v = _trusted_abs(_MAX_NOTCH)
    if v is not None:
        result["MAX_DECEL_MS2"] = v
    
    v = _trusted_avg(_BRAKE_NOTCHES)
    if v is not None:
        result["TARGET_DECEL_MS2"] = v
    
    v = _trusted_abs(_COAST_NOTCH)
    if v is not None:
        result["COAST_DECEL_MS2"] = v
    
    v = _trusted_avg(_TRACTION_NOTCHES)
    if v is not None:
        result["TARGET_ACCEL_MS2"] = v
    
    print(f"Constantes derivadas: {result}")
    
    # Guardar
    save_path = output_path or "logs/calibration.json"
    import os
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump({
            "ema": {str(k): v for k, v in _ema.items()},
            "n": {str(k): v for k, v in _n.items()},
        }, f, indent=2)
    print(f"Guardado en: {save_path}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python generate_calibration.py <log_file> [output_path]")
        sys.exit(1)
    
    log_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    process_log(log_path, output_path)
