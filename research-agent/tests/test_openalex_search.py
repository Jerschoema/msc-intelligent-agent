import src.tools.openalex_search as openalex_search
from src.tools.openalex_search import _reconstruct_abstract, _to_source, search_openalex


def _fake_work(with_pdf=True, oa_landing=False):
    return {
        "id": "https://openalex.org/W2741809807",
        "title": "  A   Journal   Paper ",
        "publication_date": "2023-05-10",
        "doi": "https://doi.org/10.1000/xyz",
        "authorships": [
            {"author": {"display_name": "A. One"}},
            {"author": {"display_name": "B. Two"}},
        ],
        "abstract_inverted_index": {"the": [0], "cat": [1], "sat": [2], "again": [3]},
        "primary_location": {"source": {"display_name": "Nature Machine Intelligence"}},
        "type": "article",
        "language": "en",
        "best_oa_location": (
            {"pdf_url": "https://x/paper.pdf"} if with_pdf
            else ({"landing_page_url": "https://x/page"} if oa_landing else None)
        ),
    }


def test_reconstruct_abstract_orders_by_position():
    assert _reconstruct_abstract({"sat": [2], "the": [0, 3], "cat": [1]}) == "the cat sat the"
    assert _reconstruct_abstract(None) == ""


def test_to_source_maps_open_pdf_work():
    s = _to_source(_fake_work(with_pdf=True))
    assert s.id == "W2741809807"
    assert s.title == "A Journal Paper"
    assert s.abstract == "the cat sat again"
    assert s.authors == ["A. One", "B. Two"]
    assert s.source_db == "openalex"
    assert s.file_type == "pdf" and s.restricted is False
    assert s.journal == "Nature Machine Intelligence"
    assert s.doi == "10.1000/xyz"
    assert s.document_type == "article"
    assert s.language == "en"


def test_to_source_html_landing_page_is_open_html():
    s = _to_source(_fake_work(with_pdf=False, oa_landing=True))
    assert s.file_type == "html" and s.restricted is False
    assert s.full_text_url == "https://x/page"


def test_to_source_paywalled_work_is_restricted():
    s = _to_source(_fake_work(with_pdf=False))
    assert s.restricted is True
    assert s.abstract


def test_search_returns_empty_on_error(monkeypatch):
    def boom(*a, **kw):
        raise OSError("network down")

    monkeypatch.setattr(openalex_search.urllib.request, "urlopen", boom)
    assert search_openalex("anything") == []
