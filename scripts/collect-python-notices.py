"""Retain full-build licensing metadata and every referenced license file."""
import json
from pathlib import Path
import shutil
import sys

source = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2])
supplements = Path(sys.argv[3]).resolve()
metadata = source / "PYTHON.json"
data = json.loads(metadata.read_text())
paths = set()


def references(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"license_path", "license_paths"}:
                items = [child] if isinstance(child, str) else child
                if not isinstance(items, list) or not all(isinstance(p, str) for p in items):
                    raise ValueError(f"Unsupported license metadata: {key}")
                paths.update(items)
            else:
                references(child)
    elif isinstance(value, list):
        for child in value:
            references(child)


references(data)
if not paths:
    raise SystemExit("No license paths in full-build metadata; refusing incomplete distribution")
# Retain additional upstream license/notice files, even if not directly referenced.
for path in source.rglob("*"):
    if path.is_file() and any(word in path.name.lower() for word in ("license", "licence", "copying", "notice")):
        paths.add(path.relative_to(source).as_posix())
target.mkdir(parents=True, exist_ok=True)
shutil.copy2(metadata, target / "PYTHON.json")
for name in sorted(paths):
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit(f"Invalid upstream license path: {name}")
    path = (source / relative).resolve()
    if not path.is_relative_to(source):
        raise SystemExit(f"Invalid upstream license path: {name}")
    if not path.is_file():
        path = (supplements / relative).resolve()
        if not path.is_relative_to(supplements) or not path.is_file():
            raise SystemExit(f"Missing upstream license with no audited supplement: {name}")
    destination = target / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
(target / "inventory.json").write_text(json.dumps(sorted(paths), indent=2) + "\n")
