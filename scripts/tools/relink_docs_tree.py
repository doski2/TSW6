"""Rewrite relative markdown links after docs/ tree reorganization."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

# basename -> path relative to docs/
LOCATIONS: dict[str, str] = {
    "CANAL_CONTROL.md": "CANAL_CONTROL.md",
    "PLAN_V2.md": "v2/PLAN_V2.md",
    "README.md": "README.md",
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

LINK_RE = re.compile(r"\]\(([^)#]+)(#[^)]*)?\)")


def rel_link(from_file: Path, target_rel: str) -> str:
    """POSIX relative path from from_file's directory to docs/<target_rel>."""
    start = from_file.parent.resolve()
    end = (DOCS / target_rel).resolve().parent
    try:
        rel = Path(os_path_relpath(end, start)) / Path(target_rel).name
    except ValueError:
        rel = Path(target_rel)
    return rel.as_posix()


def os_path_relpath(path: Path, start: Path) -> str:
    import os

    return os.path.relpath(path, start)


def resolve_target(url: str) -> str | None:
    url = url.strip()
    if not url or url.startswith(("http://", "https://", "mailto:")):
        return None
    if url.startswith("../archive/") or url.startswith("archive/"):
        return None
    if url.startswith("assets/"):
        # from v1/ or v2/ need ../assets/
        return None  # handled separately
    if url.startswith("../assets/"):
        return None
    if url.startswith("v2/") and url.endswith(".md"):
        name = Path(url).name
        return LOCATIONS.get(name, url)
    if url.startswith("reference/") or url.startswith("v1/"):
        return url
    name = Path(url.split("#")[0]).name
    if name in LOCATIONS:
        return LOCATIONS[name]
    if name.endswith(".md"):
        return None
    return None


def fix_assets(url: str, from_file: Path) -> str | None:
    if not url.startswith("assets/") and not url.startswith("../assets/"):
        return None
    name = url.split("#")[0]
    if from_file.parent == DOCS:
        new = name if name.startswith("assets/") else "assets/" + name.split("/")[-1]
    else:
        new = "../assets/" + Path(name).name
    if "#" in url:
        new += "#" + url.split("#", 1)[1]
    return new


def fix_link(from_file: Path, url: str, anchor: str | None) -> str:
    fixed_assets = fix_assets(url, from_file)
    if fixed_assets is not None:
        return fixed_assets + (anchor or "")

    target = resolve_target(url)
    if target is None:
        # ../CANAL_CONTROL already ok from v1; ../v2/ ok
        if url.startswith("../") and Path(url.split("#")[0]).name in LOCATIONS:
            name = Path(url.split("#")[0]).name
            target = LOCATIONS[name]
        else:
            return url + (anchor or "")

    if "#" in url and not anchor:
        anchor = "#" + url.split("#", 1)[1]

    rel = rel_link(from_file, target)
    return rel + (anchor or "")


def process_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    changed = False

    def repl(m: re.Match[str]) -> str:
        nonlocal changed
        url, anchor = m.group(1), m.group(2)
        new_url = fix_link(path, url, anchor)
        if new_url != url + (anchor or ""):
            changed = True
        return f"]({new_url})"

    new_text = LINK_RE.sub(repl, text)
    if changed:
        path.write_text(new_text, encoding="utf-8")
    return changed


def main() -> None:
    targets: list[Path] = []
    targets.extend(DOCS.rglob("*.md"))
    targets.extend(DOCS.rglob("*.html"))
    targets.append(ROOT / "README.md")
    archive_readme = ROOT / "archive" / "docs" / "README.md"
    if archive_readme.is_file():
        targets.append(archive_readme)
    if (ROOT / "archive" / "docs" / "CANAL_CONTROL_HISTORICO.md").is_file():
        targets.append(ROOT / "archive" / "docs" / "CANAL_CONTROL_HISTORICO.md")

    updated = 0
    for p in sorted(set(targets)):
        if process_file(p):
            print(f"updated {p.relative_to(ROOT)}")
            updated += 1
    print(f"done: {updated} files")


if __name__ == "__main__":
    main()
