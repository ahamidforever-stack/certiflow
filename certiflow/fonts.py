"""Licensed office fonts (e.g. Sakkal Majalla) for the PDF build.

The font files are supplied by the office and never committed. ``install``
copies them into the user font directory so LibreOffice uses them; the
Builder falls back to each profile's ``pdf_font_fallback`` where a font is
not installed.
"""
from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

FONT_DIR = Path.home() / ".local" / "share" / "fonts" / "certiflow"


def install(src_dir: Path) -> list[str]:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    done = []
    for f in sorted(src_dir.iterdir()):
        if f.suffix.lower() in (".ttf", ".otf", ".ttc"):
            shutil.copy(f, FONT_DIR / f.name)
            done.append(f.name)
    subprocess.run(["fc-cache", "-f", str(FONT_DIR)], capture_output=True)
    installed_families.cache_clear()
    return done


@lru_cache
def installed_families() -> frozenset[str]:
    res = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True)
    fams = set()
    for line in res.stdout.splitlines():
        for name in line.split(","):
            fams.add(name.strip().lower())
    return frozenset(fams)


def available(family: str) -> bool:
    return family.lower() in installed_families()
