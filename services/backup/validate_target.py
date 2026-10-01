"""Resolve a restore destination and reject Alice worktrees and reparse paths."""
from __future__ import annotations

import argparse
import ctypes
import os
import stat
import sys
from pathlib import Path


class InvalidDestination(ValueError):
    pass


def canonical_directory(path: str | Path) -> Path:
    candidate = Path(os.path.abspath(path))
    missing: list[str] = []
    existing = candidate
    while not existing.exists():
        if existing == existing.parent:
            raise InvalidDestination("No existe una carpeta ancestro del destino")
        missing.insert(0, existing.name)
        existing = existing.parent
    if not existing.is_dir():
        raise InvalidDestination("El destino y sus ancestros deben ser carpetas")

    # Inspect the original path chain first: resolving a junction and then
    # accepting it would conceal that the restore target crosses a reparse point.
    chain = [existing, *existing.parents]
    for part in chain:
        try:
            info = part.lstat()
        except OSError as exc:
            raise InvalidDestination("No se pudieron comprobar las carpetas del destino") from exc
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise InvalidDestination("No se permite restaurar a través de symlinks o junctions")

    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(existing), 0x80, 7, None, 3, 0x02200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise InvalidDestination("No se pudo resolver el destino final de Windows")
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
            if not size or size >= len(buffer):
                raise InvalidDestination("No se pudo normalizar la ruta Windows")
            raw = buffer.value
            if raw.startswith("\\\\?\\UNC\\"):
                raw = "\\\\" + raw[8:]
            elif raw.startswith("\\\\?\\"):
                raw = raw[4:]
            existing = Path(raw)
        finally:
            kernel.CloseHandle(handle)
    else:
        existing = existing.resolve(strict=True)
    result = existing.joinpath(*missing)
    return Path(os.path.normpath(str(result)))


def is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))).casefold() == str(root).casefold()
    except ValueError:
        return False


def validate_target(destination: str | Path, known_roots: list[str | Path]) -> Path:
    target = canonical_directory(destination)
    for known in known_roots:
        if not str(known).strip():
            continue
        root = canonical_directory(known)
        if is_within(target, root):
            raise InvalidDestination("La ruta de restauración está dentro de una instalación/worktree Alice")
    return target


def main():
    p = argparse.ArgumentParser()
    p.add_argument("destination")
    p.add_argument("--known-root", action="append", default=[])
    args = p.parse_args()
    try:
        print(validate_target(args.destination, args.known_root))
    except (InvalidDestination, OSError):
        print("Destino de restauración inválido o dentro de una instalación Alice", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
