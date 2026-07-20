import urllib.error

import src.tools.semanticscholar_search as s2_search_mod
from src.tools.semanticscholar_search import _to_source, search_semanticscholar


def _fake_paper(with_pdf=True):
    return {
        "paperId": "abc123",
        "title": " A   Conference   Paper ",
        "abstract": " findings here ",
        "year": 2022,
        "publicationDate": "2022-03-01",
        "venue": "NeurIPS",
        "authors": [{"name": "A. One"}],
        "externalIds": {"DOI": "10.1000/abc", "ArXiv": "2203.00001"},
        "openAccessPdf": {"url": "https://x/p.pdf"} if with_pdf else None,
    }


def test_to_source_maps_open_paper():
    s = _to_source(_fake_paper())
    assert s.id == "abc123"
    assert s.title == "A Conference Paper"
    assert s.abstract == "findings here"
    assert s.source_db == "semanticscholar"
    assert s.restricted is False and s.full_text_url == "https://x/p.pdf"
    assert s.journal == "NeurIPS"
    assert s.doi == "10.1000/abc"
    assert s.citations == 0
    assert s.url.endswith("abc123")


def test_to_source_without_pdf_is_restricted():
    s = _to_source(_fake_paper(with_pdf=False))
    assert s.restricted is True
    assert s.abstract == "findings here"


def test_rate_limit_returns_empty_not_exception(monkeypatch):
    def throttled(*a, **kw):
        raise urllib.error.HTTPError("url", 429, "Too Many Requests", None, None)

    monkeypatch.setattr(s2_search_mod.urllib.request, "urlopen", throttled)
    assert search_semanticscholar("anything") == []
