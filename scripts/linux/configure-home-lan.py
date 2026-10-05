#!/usr/bin/env python3
"""Set LAN addresses without exposing or replacing existing credentials."""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import sys
import tempfile


def main() -> None:
    if os.getuid() == 0:
        raise SystemExit("Ejecuta la configuración del perfil sin sudo.")
    address = ipaddress.IPv4Address(sys.argv[1])
    if not address.is_private or address.is_loopback or address.is_link_local:
        raise SystemExit("Usa la IP privada de Ubuntu en tu red de casa.")
    profile = Path(__file__).resolve().parents[2] / "infra/home/.env"
    if not profile.is_file() or profile.is_symlink():
        raise SystemExit("Falta el perfil local preparado.")
    replacements = {
        "ALICE_PUBLIC_ORIGIN": f"http://{address}:8000",
        "ALICE_BROWSER_URL": f"http://{address}:8000",
        "HOMEPAGE_ALLOWED_HOSTS": f"{address}:3000,127.0.0.1:8331,localhost:8331,127.0.0.1:3000,localhost:3000",
        "DNS_BIND_ADDR": str(address),
    }
    lines = []
    seen = set()
    for line in profile.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0]
        if key in replacements:
            if key not in seen:
                lines.append(f"{key}={replacements[key]}")
                seen.add(key)
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in replacements.items() if key not in seen)
    fd, temporary = tempfile.mkstemp(prefix=".env-lan-", dir=profile.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write("\n".join(lines) + "\n")
        os.replace(temporary, profile)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"Alice: http://{address}:8000")
    print(f"Panel: http://{address}:3000")
    print(f"Pi-hole: http://{address}:8080/admin/")
    print(f"DNS para un dispositivo de prueba: {address}")
    print("La configuración del router y su DHCP no se ha cambiado.")


if __name__ == "__main__":
    main()
