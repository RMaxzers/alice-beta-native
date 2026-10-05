"""Create one opt-in VAPID key pair for Alice on Ubuntu; never prints the private key."""
from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path.home() / 'alice-home-state' / 'storage')
    parser.add_argument('--container-path', default='/app/storage/secrets/webpush-vapid.pem',
                        help='ruta de la clave dentro del contenedor Alice')
    args = parser.parse_args()
    if os.name != 'posix' or os.geteuid() == 0:
        raise SystemExit('Ejecuta como usuario eva2, sin sudo, en Ubuntu.')
    secret = args.state / 'secrets'
    secret.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(secret, 0o700)
    path = secret / 'webpush-vapid.pem'
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise SystemExit(f'Ya existe {path}; se conserva. Guarda la clave anterior antes de rotarla.')
    with os.fdopen(fd, 'wb') as stream:
        stream.write(pem)
    public = key.public_key().public_bytes(serialization.Encoding.X962,
                                            serialization.PublicFormat.UncompressedPoint)
    encoded = base64.urlsafe_b64encode(public).decode().rstrip('=')
    print(f'Clave privada protegida creada: {path} (modo 600)')
    print(f'ALICE_PUSH_ENABLED=true\nALICE_PUSH_PRIVATE_KEY={args.container_path}\nALICE_PUSH_PUBLIC_KEY={encoded}')
    print(f'Archivo de clave en el host (respaldo protegido): {path}')
    print('ALICE_PUSH_SUBJECT=https://eva01.tail3f8e85.ts.net:8444/')
    print('La clave pública no es secreta. Registra subscriptions después del reinicio.')


if __name__ == '__main__':
    main()

