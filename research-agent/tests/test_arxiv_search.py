from datetime import datetime
from types import SimpleNamespace

import src.tools.arxiv_search as arxiv_search
from src.tools.arxiv_search import _to_source, search_arxiv


def _fake_result():
    return SimpleNamespace(
        title="  A   Messy   Title \n",
        authors=[SimpleNamespace(name="A. One"), SimpleNamespace(name="B. Two")],
        summary="  an   abstract  with  spacing ",
        published=datetime(2024, 1, 2),
        pdf_url="http://arxiv.org/pdf/2401.00001v1",
        entry_id="http://arxiv.org/abs/2401.00001v1",
        get_short_id=lambda: "2401.00001v1",
    )


def test_to_source_maps_and_normalises_fields():
    s = _to_source(_fake_result())
    assert s.id == "2401.00001v1"
    assert s.title == "A Messy Title"
    assert s.abstract == "an abstract with spacing"
    assert s.authors == ["A. One", "B. Two"]
    assert s.publication_date == "2024-01-02"
    assert s.full_text_url.endswith("2401.00001v1")
    assert s.source_db == "arxiv"
    assert s.restricted is False
    assert s.journal == "arxiv.org"
    assert s.document_type == "preprint"
    assert s.language == "en"


def test_search_maps_client_results(monkeypatch):
    class FakeClient:
        def results(self, search):
            return iter([_fake_result()])

    monkeypatch.setattr(arxiv_search.arxiv, "Search", lambda **kw: object())
    monkeypatch.setattr(arxiv_search.arxiv, "Client", lambda: FakeClient())
    out = search_arxiv("transformers", max_results=1)
    assert len(out) == 1 and out[0].id == "2401.00001v1"


def test_search_error_degrades_to_empty(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(arxiv_search.arxiv, "Client", boom)
    assert search_arxiv("anything") == []
