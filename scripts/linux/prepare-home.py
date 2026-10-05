#!/usr/bin/env python3
"""Create an isolated home profile; never overwrite existing credentials or data."""
from __future__ import annotations

import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "infra/home"


def exclusive(path: Path, content: str, mode: int = 0o600) -> bool:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
        file.write(content)
    return True


def main() -> None:
    if os.getuid() == 0:
        raise SystemExit("Ejecuta este paso como eva2, sin sudo.")
    os.umask(0o077)
    state = Path.home() / "alice-home-state"
    state.mkdir(mode=0o700, exist_ok=True)
    for name in ("data", "storage", "logs", "work", "homepage"):
        (state / name).mkdir(mode=0o700, exist_ok=True)
    for source in (PROFILE / "homepage").glob("*.yaml"):
        dest = state / "homepage" / source.name
        exclusive(dest, source.read_text(encoding="utf-8"))
    password = secrets.token_urlsafe(24)
    pihole = secrets.token_urlsafe(24)
    content = (f"PUID={os.getuid()}\nPGID={os.getgid()}\nALICE_HOME_DATA={state}\n"
               f"ALICE_USERNAME=eva2\nALICE_PASSWORD={password}\n"
               f"ALICE_SESSION_SECRET={secrets.token_urlsafe(48)}\nPIHOLE_PASSWORD={pihole}\n"
               "DNS_BIND_ADDR=127.0.0.1\nALICE_PUBLIC_ORIGIN=http://127.0.0.1:8330\n")
    created = exclusive(PROFILE / ".env", content)
    if created:
        exclusive(state / "access.txt", f"Alice: usuario eva2\nContraseña: {password}\nPi-hole: {pihole}\n")
    print(f"Perfil {'creado' if created else 'existente, conservado'}: {PROFILE}")
    print(f"Datos: {state}; credenciales locales: {state / 'access.txt'}")
    print("Docker pendiente: sudo bash ~/alice-setup/install-docker.sh eva2")


if __name__ == "__main__":
    main()
