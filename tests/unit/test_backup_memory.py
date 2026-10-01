import hashlib
import json
import os
import socket

import pytest

from services.backup.memory import BackupError, dump, exe, pg_env, restore, run
from services.backup.validate import validate
from services.backup.validate_target import InvalidDestination, validate_target


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_manifest_rejects_escape_and_corruption(tmp_path):
    file = tmp_path / "sample.txt"
    file.write_bytes(b"sample")
    item = {"path": "sample.txt", "bytes": 6, "sha256": hashlib.sha256(b"sample").hexdigest()}
    manifest = {"format": "alice-backup/2", "files": [item]}
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest))
    validate(tmp_path)
    for unsafe in ("../sample.txt", "C:/sample.txt", "sample.txt:ads", "/sample.txt", "x\\sample.txt"):
        item["path"] = unsafe
        mp.write_text(json.dumps(manifest))
        with pytest.raises(ValueError):
            validate(tmp_path)
    item["path"] = "sample.txt"
    mp.write_text(json.dumps(manifest))
    file.write_bytes(b"change")
    with pytest.raises(ValueError):
        validate(tmp_path)


def test_restore_target_rejects_installation_and_reparse_points(tmp_path):
    install = tmp_path / "alice"
    install.mkdir()
    assert validate_target(tmp_path / "isolated-restore", [install]) == tmp_path / "isolated-restore"
    with pytest.raises(InvalidDestination, match="dentro"):
        validate_target(install / "storage" / "restore", [install])
    junction = tmp_path / "alias"
    try:
        junction.symlink_to(install, target_is_directory=True)
    except OSError:
        pytest.skip("Este usuario no puede crear enlaces en Windows")
    with pytest.raises(InvalidDestination, match="junctions"):
        validate_target(junction / "restore", [install])


@pytest.mark.skipif(not os.environ.get("ALICE_TEST_PG_BIN"), reason="Set ALICE_TEST_PG_BIN for a real isolated PostgreSQL roundtrip")
def test_real_postgres_snapshot_and_isolated_restore(tmp_path):
    pg_bin = os.environ["ALICE_TEST_PG_BIN"]
    root = tmp_path / "source"
    root.mkdir()
    data = root / "data"
    source_port, target_port = port(), port()
    while target_port == source_port:
        target_port = port()
    run([exe(pg_bin, "initdb"), "-D", data, "-U", "alice_test", "--auth=trust"])
    meta = {"port": source_port, "username": "alice_test", "password": "", "database": "postgres",
            "data_dir": str(data), "installation_dir": str(__import__("pathlib").Path(pg_bin).parent)}
    metadata = root / "instance.json"
    metadata.write_text(json.dumps(meta))
    run([exe(pg_bin, "pg_ctl"), "-D", data, "-l", root / "pg.log", "-o", f"-h 127.0.0.1 -p {source_port}", "-w", "start"])
    try:
        run([exe(pg_bin, "psql"), "-X", "-v", "ON_ERROR_STOP=1", "-c",
             "CREATE TABLE memories(id integer, body text); INSERT INTO memories VALUES (1,'synthetic only'); "
             "CREATE TABLE async_operations(id integer,status text); INSERT INTO async_operations VALUES (1,'pending'),(2,'processing');"], env=pg_env(meta))
        archive = tmp_path / "backup"
        manifest = dump(metadata, archive, pg_bin)
        assert manifest["counts"]['"public"."memories"'] == 1
        assert manifest["job_states"]['"public"."async_operations"'] == {"pending": 1, "processing": 1}
        target = tmp_path / "restored"
        proof = restore(archive, target, pg_bin, target_port)
        assert proof["verified"] and not proof["workers_started"]
        assert not (target / "data" / "postmaster.pid").exists()
        with pytest.raises(BackupError):
            restore(archive, target, pg_bin, target_port)
    finally:
        run([exe(pg_bin, "pg_ctl"), "-D", data, "-m", "fast", "-w", "stop"])
