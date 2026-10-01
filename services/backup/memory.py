"""Hindsight PostgreSQL: pg_dump with an exported snapshot, never a live file copy.

Credentials remain in subprocess environment. Every table count and job-state
count uses the very same PostgreSQL snapshot as the dump. Restore starts only a
new local PostgreSQL cluster under an explicit empty destination, without workers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path


class BackupError(Exception):
    pass


def run(command, env=None, input=None, timeout=300):
    # File-backed output avoids Windows pipe-reader threads hanging when a
    # PostgreSQL child inherits a captured standard handle.
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as output:
        result = subprocess.run([str(x) for x in command], env=env, input=input,
                                stdin=subprocess.DEVNULL if input is None else None, text=True,
                                stdout=output, stderr=subprocess.DEVNULL, timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        output.seek(0)
        stdout = output.read().strip()
    if result.returncode:
        # PostgreSQL errors may contain connection credentials/data: never echo stderr.
        raise BackupError(f"Falló {Path(command[0]).name} (código {result.returncode}); revisar configuración y servicio")
    return stdout


def exe(pg_bin, name):
    path = Path(pg_bin) / (name + (".exe" if os.name == "nt" else ""))
    if not path.is_file():
        raise BackupError(f"Falta la herramienta {name} en el directorio PostgreSQL indicado")
    return path


def quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def pg_env(metadata):
    required = ("port", "username", "password", "database", "data_dir", "installation_dir")
    if any(k not in metadata for k in required):
        raise BackupError("Metadatos pg0 incompletos")
    env = dict(os.environ)
    env.update(PGHOST="127.0.0.1", PGPORT=str(int(metadata["port"])), PGUSER=metadata["username"],
               PGPASSWORD=metadata["password"], PGDATABASE=metadata["database"], PGCONNECT_TIMEOUT="10")
    # Do not inherit a service/connection override from an unrelated PostgreSQL installation.
    for key in ("PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
        env.pop(key, None)
    return env


def query(pg_bin, env, sql, snapshot=None):
    prefix = "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; "
    if snapshot:
        if not re.fullmatch(r"[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9A-Fa-f]+", snapshot):
            raise BackupError("Snapshot PostgreSQL inválido")
        prefix += f"SET TRANSACTION SNAPSHOT '{snapshot}'; "
    return run([exe(pg_bin, "psql"), "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", prefix + sql], env=env)


def inventory(pg_bin, env, snapshot=None):
    tables = json.loads(query(pg_bin, env,
        "SELECT COALESCE(json_agg(json_build_array(table_schema,table_name)), '[]'::json) FROM information_schema.tables "
        "WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema');", snapshot))
    counts, jobs = {}, {}
    for schema, table in tables:
        name = quote(schema) + "." + quote(table)
        counts[name] = int(query(pg_bin, env, f"SELECT count(*) FROM {name};", snapshot))
        if any(x in table.lower() for x in ("task", "operation", "job")):
            cols = json.loads(query(pg_bin, env,
                "SELECT COALESCE(json_agg(attname), '[]'::json) FROM pg_attribute WHERE attrelid="
                f"'{name.replace(chr(39), chr(39)*2)}'::regclass AND attnum>0 AND NOT attisdropped;", snapshot))
            if "status" in cols:
                jobs[name] = json.loads(query(pg_bin, env,
                    f"SELECT COALESCE(json_object_agg(status,n), '{{}}'::json) FROM (SELECT status::text,count(*) n "
                    f"FROM {name} GROUP BY status) s WHERE status IS NOT NULL;", snapshot))
    return {"counts": counts, "job_states": jobs}


def dump(instance_file, destination, pg_bin=None):
    metadata = json.loads(Path(instance_file).read_text(encoding="utf-8-sig"))
    env = pg_env(metadata)
    pg_bin = Path(pg_bin or Path(metadata["installation_dir"]) / "bin")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    # Redirect the snapshot value to a private file: on Windows, reading a
    # long-lived psql stdout pipe can block while that session holds the
    # exported snapshot open.
    snapshot_file = destination / f".snapshot-{secrets.token_hex(8)}.txt"
    process = subprocess.Popen([str(exe(pg_bin, "psql")), "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-f", "-"],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               text=True, env=env, cwd=destination,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        process.stdin.write("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n")
        process.stdin.write(f"SELECT pg_export_snapshot() \\g {snapshot_file.name}\n")
        process.stdin.flush()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if snapshot_file.is_file() and snapshot_file.stat().st_size:
                break
            if process.poll() is not None:
                raise BackupError("PostgreSQL no está disponible para exportar un snapshot")
            time.sleep(0.05)
        else:
            raise BackupError("PostgreSQL tardó demasiado en exportar un snapshot")
        snapshot = snapshot_file.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9A-Fa-f]+", snapshot):
            raise BackupError("PostgreSQL no está disponible para exportar un snapshot")
        info = inventory(pg_bin, env, snapshot)
        archive = destination / "hindsight.dump"
        run([exe(pg_bin, "pg_dump"), "--format=custom", "--no-owner", "--no-privileges", "--snapshot", snapshot,
             "--file", archive], env=env, timeout=1800)
        info.update(format="alice-memory/1", method="pg_dump/exported-snapshot", database=metadata["database"],
                    source_data_dir=metadata["data_dir"], source_port=metadata["port"],
                    postgres_version=query(pg_bin, env, "SHOW server_version;", snapshot),
                    dump_version=run([exe(pg_bin, "pg_dump"), "--version"]),
                    archive="hindsight.dump", sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                    pending_jobs="Included at snapshot; no workers started by restore. Review pending/processing jobs before enabling Hindsight.")
        (destination / "manifest.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        return info
    finally:
        if process.poll() is None:
            try:
                process.communicate("ROLLBACK;\n\\q\n", timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        snapshot_file.unlink(missing_ok=True)


def restore(source, destination, pg_bin, port=55432):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8-sig"))
    archive = source / "hindsight.dump"
    if manifest.get("format") != "alice-memory/1" or hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["sha256"]:
        raise BackupError("Archivo de memoria inválido o checksum distinto")
    if not (1024 <= port <= 65535) or port == int(manifest["source_port"]):
        raise BackupError("Se requiere un puerto aislado distinto del original")
    if destination.exists() and any(destination.iterdir()):
        raise BackupError("El destino de memoria debe estar vacío")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))
    destination.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(32)
    pwfile = destination / "init-password"
    fd = os.open(pwfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(password)
    data = destination / "data"
    try:
        run([exe(pg_bin, "initdb"), "-D", data, "-U", "alice_restore", "--auth=scram-sha-256", "--pwfile", pwfile])
    finally:
        pwfile.unlink(missing_ok=True)
    env = pg_env({"port": port, "username": "alice_restore", "password": password, "database": "postgres",
                  "data_dir": str(data), "installation_dir": str(Path(pg_bin).parent)})
    started = False
    try:
        run([exe(pg_bin, "pg_ctl"), "-D", data, "-l", destination / "postgres.log", "-o",
             f"-h 127.0.0.1 -p {port}", "-w", "start"], timeout=60)
        started = True
        run([exe(pg_bin, "pg_restore"), "--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges",
             "--dbname=postgres", archive], env=env, timeout=1800)
        got = inventory(pg_bin, env)
        if got["counts"] != manifest["counts"] or got["job_states"] != manifest["job_states"]:
            raise BackupError("Recuentos o estados de trabajos restaurados no coinciden")
        proof = {"verified": True, **got, "workers_started": False, "port": port,
                 "note": "Cluster de prueba detenido; para uso posterior configura credenciales y versión de Hindsight compatibles"}
        (destination / "restore-proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
        return proof
    finally:
        if started:
            run([exe(pg_bin, "pg_ctl"), "-D", data, "-m", "fast", "-w", "stop"], timeout=60)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("dump")
    b.add_argument("--instance", required=True)
    b.add_argument("--destination", required=True)
    b.add_argument("--pg-bin")
    r = sub.add_parser("restore")
    r.add_argument("--source", required=True)
    r.add_argument("--destination", required=True)
    r.add_argument("--pg-bin", required=True)
    r.add_argument("--port", type=int, default=55432)
    a = p.parse_args()
    try:
        result = dump(a.instance, a.destination, a.pg_bin) if a.command == "dump" else restore(a.source, a.destination, a.pg_bin, a.port)
        print(json.dumps(result))
    except (BackupError, OSError, ValueError, subprocess.SubprocessError) as e:
        print(str(e) if isinstance(e, BackupError) else "Fallo de respaldo/restauración de memoria; no se verificó", file=__import__("sys").stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
