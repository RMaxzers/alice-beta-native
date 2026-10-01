"""Validate all manifest paths and digests before restoring anything."""
import hashlib
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath


def validate(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    if manifest.get("format") not in ("alice-backup/1", "alice-backup/2"):
        raise ValueError("Formato desconocido")
    seen = set()
    for item in manifest["files"]:
        name = item["path"]
        rel = PurePosixPath(name)
        if not name or rel.is_absolute() or any(p in ("", ".", "..") for p in name.split("/")) or any(c in name for c in "\\:"):
            raise ValueError("Ruta inválida en manifiesto")
        key = name.casefold()
        if key in seen:
            raise ValueError("Ruta duplicada en manifiesto")
        seen.add(key)
        file = root.joinpath(*rel.parts)
        for part in [file, *file.parents]:
            if part == root:
                break
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Enlace no autorizado en backup")
        if root not in file.resolve().parents or not file.is_file():
            raise ValueError("Archivo fuera del backup")
        with file.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != item["sha256"] or file.stat().st_size != item["bytes"]:
            raise ValueError("Checksum o tamaño distinto")
    # References later consumed by PowerShell must belong to the verified inventory.
    for collection in manifest.get("vector_store", {}).get("collections", {}).values():
        if collection["snapshot"].casefold() not in seen:
            raise ValueError("Snapshot fuera del inventario")
    if manifest.get("memory", {}).get("state") == "included":
        if not {"memory/hindsight.dump", "memory/manifest.json"} <= seen:
            raise ValueError("Memoria incompleta")
    return manifest


if __name__ == "__main__":
    try:
        validate(sys.argv[1])
    except (ValueError, OSError, KeyError):
        print("Backup inválido: manifiesto, rutas o checksums", file=sys.stderr)
        raise SystemExit(2)
