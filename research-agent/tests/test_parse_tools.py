from pathlib import Path

from tests.conftest import make_source

from src.tools.parse_tools import make_parse_tools

_SAMPLE_PDF = str(Path("src/tools/samples/academic_paper_pdf_with_abstract_sample_1.pdf").resolve())


def _with_downloaded_pdf(bb, sid="p1"):
    bb.save_source(make_source(sid=sid, file_path=_SAMPLE_PDF))


def _tools(bb):
    return {t.name: t for t in make_parse_tools(bb)}


def test_inspect_describes_the_document_for_the_model(bb):
    _with_downloaded_pdf(bb)
    out = _tools(bb)["inspect_document"].invoke({"source_id": "p1"})
    assert "PDF, 21 pages" in out
    assert "Artificial intelligence" in out


def test_grobid_unavailable_redirects_to_the_fallback(bb):
    _with_downloaded_pdf(bb)
    out = _tools(bb)["parse_with_grobid"].invoke({"source_id": "p1"})
    assert "not available" in out and "parse_basic" in out


def test_unstructured_unavailable_redirects_to_the_fallback(bb):
    _with_downloaded_pdf(bb)
    out = _tools(bb)["parse_with_unstructured"].invoke({"source_id": "p1"})
    assert "not installed" in out and "parse_basic" in out


def test_parse_basic_fills_content_with_page_markers(bb):
    _with_downloaded_pdf(bb)
    out = _tools(bb)["parse_basic"].invoke({"source_id": "p1"})
    assert "21 page(s)" in out
    source = bb.get_source("p1")
    assert source.parsed
    assert source.pages == 21
    assert "[page 1]" in source.content


def test_parse_basic_reads_downloaded_web_pages(bb, tmp_path):
    page = tmp_path / "h1.txt"
    page.write_text("the page text " * 30)
    bb.save_source(make_source(sid="h1", file_type="html", file_path=str(page)))
    out = _tools(bb)["parse_basic"].invoke({"source_id": "h1"})
    assert "1 page(s)" in out
    source = bb.get_source("h1")
    assert source.parsed and source.pages == 1
    assert "[page 0]" in source.content


def test_parsing_something_not_downloaded_tells_the_model(bb):
    bb.save_source(make_source(sid="p1"))
    out = _tools(bb)["parse_basic"].invoke({"source_id": "p1"})
    assert "No downloaded document" in out
