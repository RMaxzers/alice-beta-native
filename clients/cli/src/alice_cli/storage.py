from __future__ import annotations

import ctypes
import ipaddress
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def endpoint(value):
    u = urlsplit(value)
    if u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
        raise ValueError("Usa una URL base sin credenciales, ruta, consulta ni fragmento")
    try:
        local = ipaddress.ip_address(u.hostname or "").is_loopback
    except ValueError:
        local = u.hostname == "localhost"
    if not u.hostname or (u.scheme != "https" and not (u.scheme == "http" and local)):
        raise ValueError("Se requiere HTTPS; HTTP solo se permite en loopback")
    return value.rstrip("/")


def protect(data, decrypt=False):
    if os.name != "nt":
        return data
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data)
    src = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    dst = Blob()
    dll = ctypes.WinDLL("crypt32", use_last_error=True)
    fun = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    fun.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fun.restype = wintypes.BOOL
    if not fun(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst)):
        raise ValueError("No se pudo proteger/leer la sesión con DPAPI del usuario actual")
    try:
        return ctypes.string_at(dst.data, dst.size)
    finally:
        kernel = ctypes.WinDLL("kernel32")
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(dst.data, ctypes.c_void_p))


class Storage:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("ALICE_CLI_CONFIG_HOME", Path.home() / ".config" / "alice"))

    def file(self, profile, suffix):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", profile):
            raise ValueError("Nombre de perfil inválido")
        return self.path / (profile + suffix)

    def write(self, path, data):
        self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.path, 0o700)
        fd, temporary = tempfile.mkstemp(dir=self.path)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def url(self, profile):
        path = self.file(profile, ".json")
        if path.exists():
            return endpoint(json.loads(path.read_text(encoding="utf-8"))["url"])
        if profile == "local":
            return endpoint("http://127.0.0.1:8000")
        raise ValueError(f"Perfil {profile} sin configurar. Ejecuta alice profile set {profile} --url URL_PRIVADA_HTTPS")

    def set_url(self, profile, url):
        self.write(self.file(profile, ".json"), json.dumps({"url": endpoint(url)}).encode())
        self.clear(profile)

    def session(self, profile, url):
        path = self.file(profile, ".session")
        if not path.exists():
            return {}
        data = json.loads(protect(path.read_bytes(), decrypt=True))
        if data.get("url") != url:
            raise ValueError("La sesión pertenece a otro endpoint; inicia sesión otra vez")
        return data

    def save(self, profile, data):
        self.write(self.file(profile, ".session"), protect(json.dumps(data).encode()))

    def clear(self, profile):
        self.file(profile, ".session").unlink(missing_ok=True)
