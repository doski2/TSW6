"""Replace docs/ root duplicates with redirect stubs pointing to v1/ or reference/."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

STUBS: dict[str, str] = {
    "GUIA.md": "v1/GUIA.md",
    "ARQUITECTURA.md": "v1/ARQUITECTURA.md",
    "ESTADO.md": "v1/ESTADO.md",
    "PENDIENTE_DYNAMICHUD.md": "v1/PENDIENTE_DYNAMICHUD.md",
    "BRAKE_V2.md": "v1/BRAKE_V2.md",
    "FLUJO_FRENOS.md": "v1/FLUJO_FRENOS.md",
    "FISICA_Y_APRENDIZAJE.md": "v1/FISICA_Y_APRENDIZAJE.md",
    "HUD_TIMETABLE.md": "v1/HUD_TIMETABLE.md",
    "FREIGHT_NA.md": "v1/FREIGHT_NA.md",
    "DASTSC_PARITY.md": "v1/DASTSC_PARITY.md",
    "COMPARATIVA_DASTSC_FLUJO.md": "v1/COMPARATIVA_DASTSC_FLUJO.md",
    "DRIVERAID_API.md": "reference/DRIVERAID_API.md",
    "DRIVERINPUT_API.md": "reference/DRIVERINPUT_API.md",
    "TSW_HTTPAPI_INDEX.md": "reference/TSW_HTTPAPI_INDEX.md",
    "CURRENTFORMATION_API.md": "reference/CURRENTFORMATION_API.md",
    "TIMEOFDAY_API.md": "reference/TIMEOFDAY_API.md",
    "PLAYER_API.md": "reference/PLAYER_API.md",
    "VIRTUALRAILDRIVER_API.md": "reference/VIRTUALRAILDRIVER_API.md",
}


def stub_body(target: str) -> str:
    name = Path(target).name
    return (
        f"# Movido\n\n"
        f"Este documento está en **[{target}]({target})**.\n\n"
        f"Índice: [README.md](README.md).\n"
    )


def main() -> None:
    for name, target in STUBS.items():
        path = DOCS / name
        body = stub_body(target)
        if path.is_file() and path.read_text(encoding="utf-8") == body:
            continue
        path.write_text(body, encoding="utf-8")
        print(f"stub {name} -> {target}")


if __name__ == "__main__":
    main()
