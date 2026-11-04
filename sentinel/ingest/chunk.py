"""Two chunking strategies: structure-aware (sections) and recursive (paragraph packing)."""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel

from sentinel.ingest.parse import ParsedDoc, split_sections

SENTENCE = re.compile(r"(?<=[.!?])\s+")


class Chunk(BaseModel):
    id: str
    source: str
    page: int  # first page containing the text (0 for Markdown)
    section: str | None
    text: str
    access_label: str


def _pack_unit(units: list[str], target: int, overlap: int) -> list[str]:
    out: list[str] = []
    buf = ""
    for u in units:
        if len(buf) + len(u) + 1 <= target:
            buf = f"{buf} {u}".strip() if buf else u
        else:
            if buf:
                out.append(buf)
            buf = u
            while len(buf) > target:
                out.append(buf[:target])
                buf = buf[target - overlap :]
    if buf:
        out.append(buf)
    return out


def chunk_structure(doc: ParsedDoc, target: int = 900, overlap: int = 150) -> list[Chunk]:
    """Chunk per recognized section; across pages, keep first page of the section."""
    chunks: list[Chunk] = []
    seen_first_page: dict[str, int] = {}
    body: dict[str, list[str]] = {}
    order: list[str] = []
    for page in doc.pages:
        for title, text in split_sections(page.text):
            key = title or text[:40]
            if key not in body:
                body[key] = []
                order.append(key)
                seen_first_page[key] = page.page
            if text:
                body[key].append(text)
    for key in order:
        text = "\n".join(body[key]).strip()
        if not text:
            continue
        paragraphs = text.split("\n")
        for i, piece in enumerate(_pack_unit(paragraphs, target, overlap)):
            chunks.append(
                Chunk(
                    id=_cid(doc.source, piece, i, key),
                    source=doc.source,
                    page=seen_first_page[key],
                    section=key if key != text[:40] else None,
                    text=piece,
                    access_label=doc.access_label,
                )
            )
    return chunks


def chunk_recursive(doc: ParsedDoc, target: int = 900, overlap: int = 150) -> list[Chunk]:
    """Fallback: split paragraphs/sentences to ~target chars, no section awareness."""
    chunks: list[Chunk] = []
    for page in doc.pages:
        pieces = _pack_unit(page.text.split("\n"), target, overlap)
        for i, piece in enumerate(pieces):
            chunks.append(
                Chunk(
                    id=_cid(doc.source, piece, i, "recursive"),
                    source=doc.source,
                    page=page.page,
                    section=None,
                    text=piece,
                    access_label=doc.access_label,
                )
            )
    return chunks


def chunk_all(docs: list[ParsedDoc], strategy: str, **kw) -> list[Chunk]:
    fn = chunk_structure if strategy == "structure" else chunk_recursive
    return [c for doc in docs for c in fn(doc, **kw)]


def _cid(source: str, text: str, i: int, key: str) -> str:
    h = hashlib.sha1(f"{source}|{key}|{i}|{text[:64]}".encode()).hexdigest()[:16]
    return h
