"""Download a PDF, pull out its text, and cut it into Chunks.

pypdf, pure Python, no OCR needed. Every function fails soft (returns empty)
rather than raising, so one broken PDF doesn't kill the run.

A chunk never crosses a page boundary, so page numbers stay accurate for
citations.
"""

import re
import ssl
import urllib.request
from pathlib import Path

import certifi
from pypdf import PdfReader

from src.config.settings import settings
from src.models import Chunk

# Verify HTTPS against certifi's CA bundle. A stock Python on macOS often has no
# system certificates, so without this every arxiv.org download fails with
# CERTIFICATE_VERIFY_FAILED.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def download_pdf(url: str, dest: str) -> str | None:
    try:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "research-agent/0.1"})
        with urllib.request.urlopen(request, timeout=30, context=_SSL_CONTEXT) as resp:
            data = resp.read()
        Path(dest).write_bytes(data)
        return dest
    except Exception as exc:  # noqa: BLE001
        # Any download problem just means we skip this paper.
        print(f"[pdf_parser] download failed for {url!r}: {exc}")
        return None


def extract_text(pdf_path: str) -> list[tuple[int, str]]:
    """Return [(page_number, text)] for pages that have extractable text."""
    try:
        reader = PdfReader(pdf_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[pdf_parser] could not open {pdf_path!r}: {exc}")
        return []
    pages: list[tuple[int, str]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""  # one bad page, skip it and carry on with the others
        if text.strip():
            pages.append((page_number, text))
    return pages


def chunk_text(
    pages: list[tuple[int, str]],
    source_id: str,
    size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """Sliding-window chunks (per page) with character overlap to preserve context."""
    size = size or settings.chunk_size
    overlap = overlap or settings.chunk_overlap
    step = max(1, size - overlap)
    chunks: list[Chunk] = []
    index = 0
    for page_number, text in pages:
        start, length = 0, len(text)
        while start < length:
            piece = text[start : start + size]
            chunks.append(
                Chunk(
                    id=f"{source_id}:{index}",
                    source_id=source_id,
                    text=piece,
                    page=page_number,
                    chunk_index=index,
                )
            )
            index += 1
            if start + size >= length:
                break
            start += step
    return chunks


def pages_to_text(pages: list[tuple[int, str]]) -> str:
    """Join extracted pages into one string with [page N] markers.

    The markers are how page numbers survive the trip through the source's
    content field — text_to_pages() reverses this exactly, so citations keep
    pointing at real pages.
    """
    return "\n\n".join(f"[page {number}]\n{text}" for number, text in pages)


def text_to_pages(content: str) -> list[tuple[int, str]]:
    """Split marked-up content back into [(page_number, text)]."""
    pages: list[tuple[int, str]] = []
    number, parts = 0, []
    for line in content.splitlines():
        match = re.fullmatch(r"\[page (\d+)\]", line.strip())
        if match:
            if parts and "".join(parts).strip():
                pages.append((number, "\n".join(parts).strip()))
            number, parts = int(match.group(1)), []
        else:
            parts.append(line)
    if parts and "".join(parts).strip():
        pages.append((number, "\n".join(parts).strip()))
    return pages
