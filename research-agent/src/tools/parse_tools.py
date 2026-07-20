"""The parser tools available to the ParseAgent

Each tool fills the source's content ([page N] markers) and pages. The model
picks the parser that fits: GROBID for academic PDFs, unstructured for messy
layouts, parse_basic as the always-works fallback.


"""

import ssl
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import certifi
from langchain_core.tools import tool
from pypdf import PdfReader

from src.config.settings import settings
from src.tools.pdf_parser import extract_text, pages_to_text

try:
    from unstructured.partition.auto import partition
except ImportError:
    partition = None  # optional dependency; parse_basic covers every case

_NAME = "ParseAgent"
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _grobid_pages(pdf_path: str) -> list[tuple[int, str]]:
    """Send the PDF to GROBID, return its text as one page.

    TEI output has no page mapping, so it all lands on page 0.
    """
    with open(pdf_path, "rb") as f:
        body = f.read()
    boundary = "----research-agent"
    payload = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="input"; filename="doc.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + body + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{settings.grobid_url.rstrip('/')}/api/processFulltextDocument",
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=60, context=_SSL_CONTEXT) as resp:
        tei = resp.read().decode("utf-8", errors="replace")
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    paragraphs = [p.text or "" for p in ET.fromstring(tei).iter("{http://www.tei-c.org/ns/1.0}p")]
    text = "\n\n".join(p for p in paragraphs if p.strip())
    return [(0, text)] if text.strip() else []


def basic_parse(blackboard, source) -> bool:
    """Plain per-page text extraction, no LLM. Shared by parse_basic and the
    graph's fallback sweep, so no downloaded document is ever left unparsed.
    Returns False when no text could be extracted.
    """
    if source.file_type == "html":
        pages = [(0, Path(source.file_path).read_text(encoding="utf-8"))]
    else:
        pages = extract_text(source.file_path)
    if not any(text.strip() for _, text in pages):
        return False
    source.content = pages_to_text(pages)
    source.pages = len(pages)
    blackboard.save_source(source)
    return True


def make_parse_tools(blackboard) -> list:
    """Build the parser toolset bound to this run's blackboard."""

    def _store(source_id: str, pages: list[tuple[int, str]], parser: str) -> str:
        """Write the parsed text onto the source — the one way every parser ends."""
        if not any(text.strip() for _, text in pages):
            return f"No text could be extracted from {source_id}. Try a different parser."
        source = blackboard.get_source(source_id)
        source.content = pages_to_text(pages)
        source.pages = len(pages)
        blackboard.save_source(source)
        return f"Parsed {source_id} with {parser}: {len(pages)} page(s). Move on to the next document."

    @tool
    def inspect_document(source_id: str) -> str:
        """Look at a downloaded document before choosing a parser: its type,
        size, and a sample of its text."""
        source = blackboard.get_source(source_id)
        if source is None or not source.file_path:
            return f"No downloaded document for {source_id!r}."
        if source.file_type == "html":
            text = Path(source.file_path).read_text(encoding="utf-8")
            return f"Web page text, {len(text)} chars. Sample: {text[:400]}"
        reader = PdfReader(source.file_path)
        sample = (reader.pages[0].extract_text() or "")[:400]
        return f"PDF, {len(reader.pages)} pages. First page sample: {sample}"

    @tool
    def parse_with_grobid(source_id: str) -> str:
        """Parse an academic PDF with GROBID (structure-aware: understands
        sections, references, headers). The best choice for scholarly PDFs
        when available."""
        source = blackboard.get_source(source_id)
        if source is None or not source.file_path or source.file_type != "pdf":
            return f"No downloaded PDF for {source_id!r}."
        if not settings.grobid_url:
            return "GROBID is not available here. Use parse_basic instead."
        try:
            pages = _grobid_pages(source.file_path)
        except Exception as exc:  # noqa: BLE001
            return f"GROBID failed ({exc}). Use parse_basic instead."
        if not pages:
            return "GROBID returned no text. Use parse_basic instead."
        return _store(source_id, pages, "grobid")

    @tool
    def parse_with_unstructured(source_id: str) -> str:
        """Parse a PDF with the unstructured library (good for messy or
        non-academic layouts: reports, slides)."""
        source = blackboard.get_source(source_id)
        if source is None or not source.file_path or source.file_type != "pdf":
            return f"No downloaded PDF for {source_id!r}."
        if partition is None:
            return "The unstructured library is not installed. Use parse_basic instead."
        try:
            elements = partition(filename=source.file_path)
        except Exception as exc:  # noqa: BLE001
            return f"unstructured failed ({exc}). Use parse_basic instead."
        by_page: dict[int, list[str]] = {}
        for el in elements:
            page = getattr(el.metadata, "page_number", None) or 0
            by_page.setdefault(page, []).append(str(el))
        pages = [(n, "\n".join(parts)) for n, parts in sorted(by_page.items())]
        return _store(source_id, pages, "unstructured")

    @tool
    def parse_basic(source_id: str) -> str:
        """Reliable fallback parser: plain per-page text extraction. Works for
        every PDF and for downloaded web pages."""
        source = blackboard.get_source(source_id)
        if source is None or not source.file_path:
            return f"No downloaded document for {source_id!r}."
        if not basic_parse(blackboard, source):
            return f"No text could be extracted from {source_id}."
        return f"Parsed {source_id} with parse_basic: {source.pages} page(s). Move on to the next document."

    return [inspect_document, parse_with_grobid, parse_with_unstructured, parse_basic]
