import src.tools.research_tools as tools_mod
from tests.conftest import make_source

from src.tools.research_tools import make_research_tools


def _tools(bb, topic="the topic"):
    return {t.name: t for t in make_research_tools(bb, topic)}


def test_search_saves_new_sources_with_provenance(bb, monkeypatch):
    monkeypatch.setattr(tools_mod, "search_arxiv", lambda q: [make_source(topic="", query="")])
    listing = _tools(bb)["search_papers"].invoke({"query": "first query"})
    assert "id=2401.1v1" in listing
    source = bb.get_source("2401.1v1")
    assert source.topic == "the topic"
    assert source.query == "first query"


def test_search_never_saves_the_same_source_twice(bb, monkeypatch):
    monkeypatch.setattr(tools_mod, "search_arxiv", lambda q: [make_source(topic="", query="")])
    search = _tools(bb)["search_papers"]
    search.invoke({"query": "first query"})
    search.invoke({"query": "second query"})
    assert len(bb.sources()) == 1
    assert bb.get_source("2401.1v1").query == "first query"


def test_search_with_no_results_steers_the_model(bb, monkeypatch):
    monkeypatch.setattr(tools_mod, "search_arxiv", lambda q: [])
    out = _tools(bb)["search_papers"].invoke({"query": "obscure topic"})
    assert "broader" in out
    assert any(d["content"]["kind"] == "error" for d in bb.posts("decision"))


def test_search_rejects_a_single_generic_word(bb, monkeypatch):
    monkeypatch.setattr(tools_mod, "search_arxiv", lambda q: [make_source()])
    out = _tools(bb)["search_papers"].invoke({"query": "transformer"})
    assert "too generic" in out
    assert bb.sources() == []
    assert any(d["content"]["kind"] == "error" for d in bb.posts("decision"))


def test_fetch_downloads_pdf_onto_the_source(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source())
    monkeypatch.setattr(tools_mod, "download_pdf", lambda url, dest: dest)
    out = _tools(bb)["fetch_paper"].invoke({"paper_id": "2401.1v1"})
    assert "Downloaded" in out and "parsed next" in out
    assert bb.get_source("2401.1v1").file_path.endswith("2401.1v1.pdf")


def test_fetch_is_idempotent(bb):
    bb.save_source(make_source(file_path="already/there.pdf"))
    out = _tools(bb)["fetch_paper"].invoke({"paper_id": "2401.1v1"})
    assert "already downloaded" in out


def test_fetch_unknown_id_tells_the_model(bb):
    out = _tools(bb)["fetch_paper"].invoke({"paper_id": "nope"})
    assert "Unknown paper id" in out


def test_fetch_restricted_source_degrades_to_abstract(bb):
    bb.save_source(make_source(sid="r1", restricted=True))
    out = _tools(bb)["fetch_paper"].invoke({"paper_id": "r1"})
    assert "restricted access" in out
    assert any(d["content"]["kind"] == "restricted" for d in bb.posts("decision"))
    assert not bb.get_source("r1").file_path


def test_fetch_html_saves_page_text(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(sid="h1", file_type="html", full_text_url="http://open.example/h1"))
    monkeypatch.setattr(tools_mod, "fetch_html", lambda url: ("ok", "page text " * 50))
    out = _tools(bb)["fetch_paper"].invoke({"paper_id": "h1"})
    assert "Downloaded the web page" in out
    source = bb.get_source("h1")
    assert "page text" in open(source.file_path, encoding="utf-8").read()


def test_fetch_captcha_is_recorded_on_the_source(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(sid="h1", file_type="html", full_text_url="http://guarded.example/h1"))
    monkeypatch.setattr(tools_mod, "fetch_html", lambda url: ("captcha", ""))
    out = _tools(bb)["fetch_paper"].invoke({"paper_id": "h1"})
    assert "CAPTCHA" in out
    assert bb.get_source("h1").captcha is True
    assert any(d["content"]["kind"] == "captcha" for d in bb.posts("decision"))


def test_fetch_download_failure_becomes_a_skip(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source())
    monkeypatch.setattr(tools_mod, "download_pdf", lambda url, dest: None)
    out = _tools(bb)["fetch_paper"].invoke({"paper_id": "2401.1v1"})
    assert "different paper" in out
    assert any(d["content"]["kind"] == "skip" for d in bb.posts("decision"))
