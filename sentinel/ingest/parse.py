"""Parse PDF/Markdown sources into ParsedDoc with page-tracked text."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

MD_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
PDF_HEADING = re.compile(r"^\s*((\d+(\.\d+)?)|([A-Z]\d))\s+[A-Z][^\n]{0,90}$")


class Page(BaseModel):
    page: int  # 1-based for PDFs; 0 for Markdown (pageless)
    text: str


class ParsedDoc(BaseModel):
    source: str
    kind: str  # pdf | md
    access_label: str = "public"
    pages: list[Page] = Field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


def parse_pdf(path: Path, access_label: str) -> ParsedDoc:
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(Page(page=i, text=text.strip()))
    return ParsedDoc(source=path.name, kind="pdf", access_label=access_label, pages=pages)


def parse_md(path: Path, access_label: str) -> ParsedDoc:
    text = path.read_text(encoding="utf-8")
    return ParsedDoc(
        source=path.name,
        kind="md",
        access_label=access_label,
        pages=[Page(page=0, text=text.strip())],
    )


def parse_dir(directory: Path, manifest: Path | None = None) -> list[ParsedDoc]:
    """Parse every supported file in a folder. Access labels come from manifest.json
    (keyed by file name) when present, else default to public."""
    manual = {}
    if manifest and manifest.exists():
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        manual = {d["file"]: d["access_label"] for d in doc.get("documents", [])}
    out = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        access = manual.get(path.name, "public")
        if path.suffix.lower() == ".pdf":
            out.append(parse_pdf(path, access))
        elif path.suffix.lower() in {".md", ".markdown"}:
            out.append(parse_md(path, access))
    return out


def split_sections(text: str) -> list[tuple[str | None, str]]:
    """Split text into (section_title, body) pairs. PDF numbered headings and
    markdown #-headings are recognized; leading text has section None."""
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines():
        md = MD_HEADING.match(line)
        if md and md.group(2).strip():
            sections.append((md.group(2).strip(), []))
            continue
        stripped = line.strip()
        if _looks_like_pdf_heading(stripped):
            sections.append((stripped, []))
            continue
        sections[-1][1].append(line)
    return [(title, "\n".join(body).strip()) for title, body in sections if title or body]


def _looks_like_pdf_heading(line: str) -> bool:
    """Short numbered title line, not a sentence or data row: '1 Operating limits'."""
    if len(line) >= 60 or any(ch in line for ch in ",:."):
        return False
    if not any(c.islower() for c in line):  # '27 A' is data, not a heading
        return False
    first = line.split(" ", 1)[0]
    if not re.fullmatch(r"[1-9](\.\d+)*|[A-Z]\d", first):  # major number must be 1-8 digit
        return False
    return bool(PDF_HEADING.match(line))
