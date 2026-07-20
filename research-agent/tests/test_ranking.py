import json
from pathlib import Path

from tests.conftest import FakeStructuredLLM, make_source

from src.agents.ranking import RankingAgent


def test_registry_hit_needs_no_llm(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(journal="arxiv.org"))
    llm = FakeStructuredLLM(parsed={"tier": "high", "justification": "should not be asked"})
    RankingAgent(bb, llm).run()
    source = bb.get_source("2401.1v1")
    assert source.ranking == "medium"
    assert llm.calls == []
    assert "[registry]" in bb.posts("decision")[-1]["content"]["reason"]


def test_unknown_venue_asks_llm_and_caches_the_verdict(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(journal="Obscure Quarterly"))
    llm = FakeStructuredLLM(parsed={"tier": "low", "justification": "no editorial review found"})
    RankingAgent(bb, llm).run()
    source = bb.get_source("2401.1v1")
    assert source.ranking == "low"
    assert source.ranking_note == "no editorial review found"
    cache = json.loads(Path("data/registry-cache.json").read_text())
    assert cache["Obscure Quarterly"]["tier"] == "low"


def test_cached_venue_skips_the_llm(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    Path("data/registry-cache.json").write_text(
        json.dumps({"Obscure Quarterly": {"tier": "low", "note": "cached verdict"}})
    )
    bb.save_source(make_source(journal="Obscure Quarterly"))
    llm = FakeStructuredLLM(parsed={"tier": "high", "justification": "should not be asked"})
    RankingAgent(bb, llm).run()
    assert bb.get_source("2401.1v1").ranking_note == "cached verdict"
    assert llm.calls == []


def test_cache_entries_from_older_versions_still_work(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    Path("data/registry-cache.json").write_text(
        json.dumps({"Old Journal": {"tier": "high", "description": "old-format note", "rationale": "r"}})
    )
    bb.save_source(make_source(journal="Old Journal"))
    RankingAgent(bb, FakeStructuredLLM()).run()
    source = bb.get_source("2401.1v1")
    assert source.ranking == "high"
    assert source.ranking_note == "old-format note"


def test_llm_failure_degrades_to_unknown_and_is_not_cached(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(journal="Obscure Quarterly"))
    RankingAgent(bb, FakeStructuredLLM(raw_text="??")).run()
    assert bb.get_source("2401.1v1").ranking == "unknown"
    assert not Path("data/registry-cache.json").exists()


def test_never_ranks_twice(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(ranking="high", ranking_note="done"))
    llm = FakeStructuredLLM(parsed={"tier": "low", "justification": "should not be asked"})
    RankingAgent(bb, llm).run()
    assert llm.calls == []
    assert bb.get_source("2401.1v1").ranking == "high"
