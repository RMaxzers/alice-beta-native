"""Local extraction. Documents are data: nothing in them is executed or followed."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader

KINDS = {".pdf": "pdf", ".md": "markdown", ".markdown": "markdown", ".txt": "text", ".log": "log",
         ".csv": "csv", ".xlsx": "xlsx"}
UNSUPPORTED_HINT = {".epub": "EPUB aún no soportado", ".docx": "DOCX aún no soportado", ".doc": "DOC no soportado",
                    ".json": "JSON aún no soportado", ".xls": "XLS antiguo no soportado; guarde como XLSX"}


class ExtractionError(Exception):
    pass


@dataclass
class Segment:
    location: str
    text: str


def detect_kind(filename: str, head: bytes) -> str:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext in UNSUPPORTED_HINT:
        raise ExtractionError(UNSUPPORTED_HINT[ext])
    kind = KINDS.get(ext)
    if kind is None:
        raise ExtractionError(f"Formato no soportado: {ext or 'sin extensión'}")
    # Verify the real type matches the extension.
    if kind == "pdf" and not head.startswith(b"%PDF"):
        raise ExtractionError("El archivo no es un PDF válido")
    if kind == "xlsx" and not head.startswith(b"PK"):
        raise ExtractionError("El archivo no es un XLSX válido")
    if kind in ("markdown", "text", "log", "csv") and b"\x00" in head:
        raise ExtractionError("Archivo de texto con contenido binario")
    return kind


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("No se pudo decodificar el texto")


def extract_pdf(data: bytes, max_pages: int) -> list[Segment]:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ExtractionError("PDF cifrado/protegido: no se procesa (no se elude DRM)")
    if len(reader.pages) > max_pages:
        raise ExtractionError(f"PDF con {len(reader.pages)} páginas supera el límite de {max_pages}")
    segs = [Segment(f"página {i}", (p.extract_text() or "").strip()) for i, p in enumerate(reader.pages, start=1)]
    segs = [s for s in segs if s.text]
    if sum(len(s.text) for s in segs) < 20:
        raise ExtractionError("El PDF no contiene texto utilizable: requiere OCR (no soportado en Beta)")
    return segs


def extract_markdown(text: str) -> list[Segment]:
    segs, heading, buf = [], "inicio", []
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            if "".join(buf).strip():
                segs.append(Segment(f"sección: {heading}", "\n".join(buf).strip()))
            heading, buf = m.group(2).strip()[:80], []
        else:
            buf.append(line)
    if "".join(buf).strip():
        segs.append(Segment(f"sección: {heading}", "\n".join(buf).strip()))
    return segs


def extract_text(text: str) -> list[Segment]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return [Segment(f"párrafo {i}", p) for i, p in enumerate(paras, start=1)]


def chunk(segments: list[Segment], size: int = 900, overlap: int = 150) -> list[Segment]:
    out = []
    for s in segments:
        t = s.text
        if len(t) <= size:
            out.append(s)
            continue
        start = 0
        while start < len(t):
            out.append(Segment(s.location, t[start:start + size]))
            start += size - overlap
    return out
