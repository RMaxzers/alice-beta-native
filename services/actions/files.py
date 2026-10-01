from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import socket
import stat
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.api.db import tx
from packages.schemas.models import Privacy
from services.conversations.store import now

TOOL = {"name": "file.create_text", "level": "C1", "extensions": [".txt", ".md"], "max_bytes": 65536}
_executor_lock = threading.Lock()


class ActionError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(detail)


class FileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1, max_length=64)
    client_request_id: str = Field(min_length=8, max_length=100)
    filename: str = Field(min_length=1, max_length=120)
    content: str = Field(max_length=65536)
    privacy: Privacy = Privacy.PRIVATE

    @field_validator("filename")
    @classmethod
    def filename_safe(cls, value):
        # Flat names only; reject ADS, UNC, DOS devices (including superscript COM/LPT),
        # terminal dots/spaces, traversal and control/format characters.
        import unicodedata
        stem = value.split(".", 1)[0].rstrip(" .").upper()
        if (value in (".", "..") or any(c in value for c in '\\/:*?"<>|') or
                value != value.strip() or value.endswith(".") or
                any(unicodedata.category(c).startswith("C") for c in value) or
                re.fullmatch(r"CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[0-9¹²³]", stem) or
                Path(value).suffix.lower() not in TOOL["extensions"]):
            raise ValueError("Nombre .txt/.md inválido; se admite solo un nombre, sin ruta")
        return value

    @field_validator("content")
    @classmethod
    def content_size(cls, value):
        if len(value.encode("utf-8")) > TOOL["max_bytes"]:
            raise ValueError("El contenido supera 65536 bytes UTF-8")
        return value


@contextmanager
def pinned_root(root: Path):
    """Pin every Windows ancestor without FILE_SHARE_DELETE and reject reparse points.

    A rename/junction swap is denied by the kernel while handles are open. File
    creation/open below uses this pinned full path. POSIX uses O_NOFOLLOW dirfds.
    """
    root = Path(os.path.abspath(root))
    if str(root).startswith("\\\\"):
        raise ActionError(403, "La carpeta autorizada debe estar en un disco local")
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handles = []
        try:
            for p in [*reversed(root.parents), root]:
                handle = kernel.CreateFileW(str(p), 0x80000000, 3, None, 3, 0x02200000, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise ActionError(403, "No se pudo bloquear la carpeta autorizada")
                handles.append(handle)
                # All ancestors are pinned by now up to p; no unprotected components before p.
                info = os.lstat(p)
                if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise ActionError(403, "Enlaces o junctions no autorizados")
            yield root, None
        finally:
            for handle in reversed(handles):
                kernel.CloseHandle(handle)
    else:
        fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in root.parts[1:]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            yield root, fd
        finally:
            os.close(fd)


def _open(root, dirfd, name, create):
    if os.name == "nt":
        from ctypes import wintypes
        import msvcrt
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.CreateFileW.restype = wintypes.HANDLE
        # No sharing: nobody can replace, modify or read this file while it is verified.
        h = k.CreateFileW(str(root / name), 0xC0000000 if create else 0x80000000, 0, None,
                          1 if create else 3, 0x00200000, None)
        if h == ctypes.c_void_p(-1).value:
            err = ctypes.get_last_error()
            if err in (80, 183):
                raise FileExistsError(name)
            raise OSError(err, "No se pudo abrir el archivo")
        fd = msvcrt.open_osfhandle(h, os.O_BINARY | (os.O_RDWR if create else os.O_RDONLY))
    else:
        flags = (os.O_RDWR | os.O_CREAT | os.O_EXCL) if create else os.O_RDONLY
        fd = os.open(name, flags | os.O_NOFOLLOW, 0o600, dir_fd=dirfd)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 0x400:
        os.close(fd)
        raise ActionError(403, "El destino no es un archivo regular exclusivo")
    return fd


def identity(fd):
    info = os.fstat(fd)
    return f"{info.st_dev}:{info.st_ino}"


def evidence(fd, expected, size):
    os.lseek(fd, 0, os.SEEK_SET)
    body = os.read(fd, TOOL["max_bytes"] + 1)
    digest = hashlib.sha256(body).hexdigest()
    return {"verified": digest == expected and len(body) == size, "sha256": digest, "bytes": len(body)}


class FileExecutor:
    def __init__(self, con, root, executor_name=""):
        self.con, self.root = con, Path(root) if root else None
        self.executor_name = executor_name or socket.gethostname()

    def get(self, owner, op):
        row = self.con.execute("SELECT * FROM file_operations WHERE operation_id=? AND owner=?", (op, owner)).fetchone()
        if not row:
            raise ActionError(404, "Operación no encontrada")
        return self.public(row)

    @staticmethod
    def public(row):
        d = dict(row)
        for key in ("payload_hash", "content_sha256", "file_identity", "verification_json"):
            d.pop(key, None)
        d["tool"] = TOOL["name"]
        d["verification"] = json.loads(row["verification_json"]) if row["verification_json"] else None
        return d

    def _finish(self, op, status, verification=None, error=None):
        with tx(self.con):
            self.con.execute("UPDATE file_operations SET status=?,verification_json=?,error=?,updated_at=? WHERE operation_id=?",
                             (status, json.dumps(verification) if verification else None, error, now(), op))

    def _reconcile(self, row):
        # Never repeat a write after unknown outcome. Only confirm our recorded inode + bytes.
        try:
            if not self.root or str(self.root.absolute() / row["filename"]) != row["destination"]:
                raise ActionError(409, "La carpeta autorizada cambió")
            with pinned_root(self.root) as (root, dirfd):
                fd = _open(root, dirfd, row["filename"], False)
                try:
                    proof = evidence(fd, row["content_sha256"], row["size_bytes"])
                    if identity(fd) != row["file_identity"] or not proof["verified"]:
                        raise ActionError(409, "No coincide la identidad o el contenido")
                finally:
                    os.close(fd)
            self._finish(row["operation_id"], "done", proof)
        except (OSError, ActionError):
            self._finish(row["operation_id"], "needs_review", error="Resultado desconocido; revisar destino. No se repitió la escritura.")

    def create(self, owner, body: FileInput):
        if not self.root:
            raise ActionError(403, "Configura ALICE_FILE_ROOT para autorizar una carpeta del equipo")
        data = body.content.encode("utf-8")
        digest = hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        # Cross-process safety: BEGIN IMMEDIATE protects the UNIQUE claim; exclusive
        # create protects the effect. An in-flight operation is not reconciled here.
        with _executor_lock:
            with tx(self.con):
                old = self.con.execute("SELECT * FROM file_operations WHERE owner=? AND client_request_id=?", (owner, body.client_request_id)).fetchone()
                if old:
                    if old["payload_hash"] != digest:
                        raise ActionError(409, "client_request_id ya vinculado a otra acción")
                    return self.public(old)
                op, at = uuid.uuid4().hex, now()
                self.con.execute("INSERT INTO file_operations(operation_id,owner,conversation_id,client_request_id,payload_hash,"
                                 "filename,destination,executor_name,privacy,content_sha256,size_bytes,status,created_at,updated_at) "
                                 "VALUES (?,?,?,?,?,?,?,?,?,?,?,'running',?,?)",
                                 (op, owner, body.conversation_id, body.client_request_id, digest, body.filename,
                                  str(self.root.absolute() / body.filename), self.executor_name, body.privacy.value,
                                  hashlib.sha256(data).hexdigest(), len(data), at, at))
            try:
                with pinned_root(self.root) as (root, dirfd):
                    fd = _open(root, dirfd, body.filename, True)
                    try:
                        with tx(self.con):
                            self.con.execute("UPDATE file_operations SET file_identity=? WHERE operation_id=?", (identity(fd), op))
                        with os.fdopen(os.dup(fd), "wb") as f:
                            f.write(data)
                            f.flush()
                            os.fsync(f.fileno())
                        proof = evidence(fd, hashlib.sha256(data).hexdigest(), len(data))
                        if not proof["verified"]:
                            raise ActionError(409, "Falló la verificación del archivo")
                        self._finish(op, "done", proof)
                    finally:
                        os.close(fd)
            except FileExistsError:
                self._finish(op, "failed", error="El archivo ya existe; no se sobrescribió")
            except (OSError, ActionError):
                self._finish(op, "needs_review", error="No se completó la verificación; revisar destino antes de otra solicitud")
            return self.get(owner, op)

    def recover(self):
        # Invoke once at single-worker startup, before accepting requests.
        with _executor_lock:
            for row in self.con.execute("SELECT * FROM file_operations WHERE status='running'"):
                self._reconcile(row)


SAVE = re.compile(r"^\s*guarda (?:este resumen|la (?:última|ultima) respuesta) como ([^\r\n]+?) en mi carpeta de Alice[.!]?\s*$", re.IGNORECASE)


def chat_filename(message):
    match = SAVE.fullmatch(message)
    return match.group(1).strip() if match else None
