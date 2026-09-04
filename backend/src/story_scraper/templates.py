"""Loading of YAML site-argument templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_template(path: Path) -> dict[str, Any]:
    with path.open("r") as f:
        data = yaml.safe_load(f)
    return data or {}


def find_template(name: str, template_dir: Path) -> Path | None:
    candidates = [
        Path(name),
        template_dir / name,
        template_dir / f"{name}.yml",
        template_dir / f"{name}.yaml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def iter_templates(template_dir: Path) -> dict[str, dict[str, Any]]:
    """Load every *.yml/*.yaml file in template_dir, keyed by stem."""
    templates: dict[str, dict[str, Any]] = {}
    for path in sorted(template_dir.glob("*.y*ml")):
        templates[path.stem] = load_template(path)
    return templates
