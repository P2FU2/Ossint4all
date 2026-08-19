"""Raiz do projeto (templates/static), mesmo fora do editable install."""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[2], here.parents[1], Path.cwd()]
    if len(here.parents) > 3:
        candidates.insert(0, here.parents[3])
    for parent in candidates:
        if (parent / "templates").is_dir() and (parent / "static").is_dir():
            return parent
    return Path.cwd()
