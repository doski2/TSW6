"""Fix relative links in docs/v2/*.md after move from docs/."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "docs" / "v2"
KEEP = {"PLAN_V2.md"}


def fix_links(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        url = match.group(1)
        if url.startswith(("#", "http://", "https://", "../")):
            return match.group(0)
        if url.startswith("assets/"):
            return "](" + "../" + url + ")"
        base = url.split("#", 1)[0]
        if base in KEEP:
            return match.group(0)
        if base.endswith(".md"):
            return "](" + "../" + url + ")"
        return match.group(0)

    text = re.sub(r"\]\(([^)]+)\)", repl, text)
    return text.replace("[assets/", "[../assets/")


def main() -> None:
    for path in sorted(V2.glob("*.md")):
        if path.name == "README.md":
            continue
        original = path.read_text(encoding="utf-8")
        updated = fix_links(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            print(f"updated {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
