#!/usr/bin/env python3
"""Entry point: python validar_freno.py  (abre GUI por defecto)"""
import sys

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("--gui")
    from tsw6.learning.brake_physics_monitor import main
    main()
