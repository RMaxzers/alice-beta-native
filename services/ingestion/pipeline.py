"""Ingestion pipeline: validate -> checksum/dedupe -> store raw -> extract -> chunk -> embed -> index -> catalog.
Idempotent: a document is only 'ready' after every step succeeded; failures are recorded, never shown as ready.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from apps.api.db import tx
from packages.schemas.models import Privacy, Verification
from services.ingestion import extract as ex
from services.ingestion.logparse import parse as parse_log
from services.rag.qdrant import Qdrant
from services.structured_data.sql import import_table, read_table, safe_ident


class IngestError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name  # strip any path components
    base = re.sub(r"[^\w.\- ]", "_", base).strip(" .") or "archivo"
    return base[:120]


class Ingestor:
    def __init__(self, con: sqlite3.Connection, data_dir: Path, tables_db: Path, qdrant: Qdrant, embed, embed_model: str,
                 embed_dim: int, max_bytes: int, max_pages: int):
        self.con, self.data_dir, self.tables_db, self.qdrant = con, data_dir, tables_db, qdrant
        self.embed, self.embed_model, self.embed_dim = embed, embed_model, embed_dim
        self.max_bytes, self.max_pages = max_bytes, max_pages
        self.tasks: dict[str, asyncio.Task] = {}

    # ---- synchronous validation + catalog entry --------------------------
    def register(self, filename: str, data: bytes, privacy: Privacy, owner: str, source: str = "upload") -> tuple[dict, bool]:
        if len(data) > self.max_bytes:
            raise IngestError(f"Archivo supera el límite de {self.max_bytes // (1024 * 1024)} MB")
        if not data:
            raise IngestError("Archivo vacío")
        name = safe_filename(filename)
        try:
            kind = ex.detect_kind(name, data[:4096])
        except ex.ExtractionError as e:
            raise IngestError(str(e)) from e
        checksum = hashlib.sha256(data).hexdigest()
        existing = self.con.execute("SELECT * FROM documents WHERE checksum=?", (checksum,)).fetchone()
        if existing:
            return dict(existing), False  # identical copy: dedupe
        prev = self.con.execute("SELECT document_id, version FROM documents WHERE original_name=? AND owner=? ORDER BY version DESC LIMIT 1",
                                (name, owner)).fetchone()
        doc_id = uuid.uuid4().hex[:16]
        raw_dir = self.data_dir / "raw" / doc_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        stored = raw_dir / name
        stored.write_bytes(data)
        row = dict(document_id=doc_id, original_name=name, stored_path=str(stored.relative_to(self.data_dir)), checksum=checksum,
                   size_bytes=len(data), mime=kind, kind=kind, source=source, version=(prev["version"] + 1) if prev else 1,
                   supersedes=prev["document_id"] if prev else None, ingested_at=_now(), privacy=privacy.value,
                   verification=Verification.UNVERIFIED.value, owner=owner, status="pending")
        with tx(self.con):
            self.con.execute(f"INSERT INTO documents({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        return row, True

    def _status(self, doc_id: str, status: str, detail: str | None = None, **extra) -> None:
        sets = ", ".join(["status=?", "status_detail=?"] + [f"{k}=?" for k in extra])
        with tx(self.con):
            self.con.execute(f"UPDATE documents SET {sets} WHERE document_id=?", [status, detail, *extra.values(), doc_id])

    # ---- background processing ---------------------------------------------
    def start(self, doc_id: str) -> None:
        t = asyncio.create_task(self.process(doc_id))
        self.tasks[doc_id] = t
        t.add_done_callback(lambda _: self.tasks.pop(doc_id, None))

    def cancel(self, doc_id: str) -> bool:
        t = self.tasks.get(doc_id)
        return bool(t and t.cancel())

    async def process(self, doc_id: str) -> None:
        doc = dict(self.con.execute("SELECT * FROM documents WHERE document_id=?", (doc_id,)).fetchone())
        self._status(doc_id, "processing")
        try:
            data = (self.data_dir / doc["stored_path"]).read_bytes()
            kind = doc["kind"]
            processed = self.data_dir / "processed" / f"{doc_id}.json"
            processed.parent.mkdir(parents=True, exist_ok=True)
            if kind in ("csv", "xlsx"):
                header, body = await asyncio.to_thread(read_table, kind, data)
                table = f"t_{safe_ident(Path(doc['original_name']).stem)[:40]}_{doc_id[:6]}"
                await asyncio.to_thread(import_table, self.tables_db, table, header, body)
                with tx(self.con):
                    self.con.execute("INSERT OR REPLACE INTO datasets VALUES (?,?,?,?,?,?)",
                                     (table, doc_id, doc["owner"], doc["privacy"], json.dumps(header), len(body)))
                processed.write_text(json.dumps({"table": table, "columns": header, "rows": len(body)}), encoding="utf-8")
                self._status(doc_id, "ready", f"tabla {table}: {len(body)} filas", extractor=kind)
                return
            if kind == "log":
                text = ex.decode_text(data)
                events = parse_log(text)
                with tx(self.con):
                    self.con.execute("DELETE FROM log_events WHERE document_id=?", (doc_id,))
                    self.con.executemany(
                        "INSERT INTO log_events(document_id, line_no, ts, ts_has_tz, severity, template, message) VALUES (?,?,?,?,?,?,?)",
                        [(doc_id, e.line_no, e.ts, int(e.ts_has_tz), e.severity, e.template, e.message) for e in events])
                processed.write_text(json.dumps([e.__dict__ for e in events[:50000]]), encoding="utf-8")
                self._status(doc_id, "ready", f"{len(events)} eventos", extractor="logparse")
                return
            if kind == "pdf":
                segs = await asyncio.to_thread(ex.extract_pdf, data, self.max_pages)
            elif kind == "markdown":
                segs = ex.extract_markdown(ex.decode_text(data))
            else:
                segs = ex.extract_text(ex.decode_text(data))
            chunks = ex.chunk(segs)
            if not chunks:
                raise IngestError("Sin texto utilizable")
            processed.write_text(json.dumps([c.__dict__ for c in chunks], ensure_ascii=False), encoding="utf-8")
            await self.qdrant.ensure_collection(self.embed_dim)
            await self.qdrant.delete_document(doc_id)  # idempotent re-run
            points = []
            for i in range(0, len(chunks), 16):  # small batches: bounded VRAM/RAM
                batch = chunks[i:i + 16]
                vecs = await self.embed([c.text for c in batch])
                for j, (c, v) in enumerate(zip(batch, vecs)):
                    points.append({"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{i + j}")), "vector": v,
                                   "payload": {"document_id": doc_id, "ordinal": i + j, "location": c.location,
                                               "privacy": doc["privacy"], "name": doc["original_name"]}})
            for i in range(0, len(points), 128):
                await self.qdrant.upsert(points[i:i + 128])
            with tx(self.con):
                self.con.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
                self.con.executemany("INSERT INTO chunks VALUES (?,?,?,?,?)",
                                     [(p["id"], doc_id, p["payload"]["ordinal"], p["payload"]["location"], chunks[k].text)
                                      for k, p in enumerate(points)])
            self._status(doc_id, "ready", f"{len(chunks)} fragmentos indexados", extractor=kind, chunks=len(chunks),
                         embedding_model=self.embed_model, embedding_dim=self.embed_dim)
        except asyncio.CancelledError:
            self._status(doc_id, "failed", "cancelado por el usuario")
            raise
        except Exception as e:  # noqa: BLE001 — recorded, never silently 'ready'
            self._status(doc_id, "failed", str(e)[:300])

    # ---- deletion -------------------------------------------------------------
    async def delete(self, doc_id: str) -> None:
        doc = self.con.execute("SELECT * FROM documents WHERE document_id=?", (doc_id,)).fetchone()
        if not doc:
            raise IngestError("Documento no encontrado")
        self.cancel(doc_id)
        await self.qdrant.delete_document(doc_id)
        for ds in self.con.execute("SELECT table_name FROM datasets WHERE document_id=?", (doc_id,)).fetchall():
            c = sqlite3.connect(self.tables_db)
            c.execute(f'DROP TABLE IF EXISTS "{ds["table_name"]}"')
            c.commit()
            c.close()
        with tx(self.con):
            self.con.execute("DELETE FROM documents WHERE document_id=?", (doc_id,))  # cascades chunks/datasets/log_events
        shutil.rmtree(self.data_dir / "raw" / doc_id, ignore_errors=True)
        (self.data_dir / "processed" / f"{doc_id}.json").unlink(missing_ok=True)
