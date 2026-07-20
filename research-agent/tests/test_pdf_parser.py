from pathlib import Path

from src.models import Source
from src.tools.pdf_parser import chunk_text, extract_text, pages_to_text, text_to_pages

_SAMPLE_PDF = Path("src/tools/samples/academic_paper_pdf_with_abstract_sample_1.pdf")


def test_extract_text_on_real_sample_paper():
    pages = extract_text(str(_SAMPLE_PDF))
    assert len(pages) == 21
    first_page_text = pages[0][1]
    assert "Artificial intelligence research in finance" in first_page_text
    chunks = chunk_text(pages, "sample1")
    assert len(chunks) > 20
    assert all(c.page >= 1 for c in chunks)


def test_chunking_count_size_overlap_and_ids():
    pages = [(1, "a" * 250), (2, "b" * 100)]
    chunks = chunk_text(pages, "p1", size=100, overlap=20)
    assert len(chunks) == 4
    assert [c.id for c in chunks] == ["p1:0", "p1:1", "p1:2", "p1:3"]
    assert [c.chunk_index for c in chunks] == [0, 1, 2, 3]
    assert all(len(c.text) <= 100 for c in chunks)


def test_chunking_propagates_page_numbers():
    pages = [(1, "x" * 150), (7, "y" * 50)]
    chunks = chunk_text(pages, "p1", size=100, overlap=20)
    assert chunks[0].page == 1
    assert chunks[-1].page == 7


def test_chunks_overlap_by_configured_amount():
    pages = [(1, "abcdefghijklmnopqrstuvwxyz")]
    chunks = chunk_text(pages, "p1", size=10, overlap=4)
    assert chunks[0].text[-4:] == chunks[1].text[:4]


def test_page_markers_round_trip_exactly():
    pages = [(1, "first page text"), (7, "later page\nwith two lines")]
    assert text_to_pages(pages_to_text(pages)) == pages


def test_text_without_markers_becomes_page_zero():
    assert text_to_pages("just some text") == [(0, "just some text")]
