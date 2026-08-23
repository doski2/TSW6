#!/usr/bin/env python3
"""Entry point: python tsw_monitor.py"""
import runpy

if __name__ == "__main__":
    runpy.run_module("tsw6.telemetry.tsw_monitor", run_name="__main__")
