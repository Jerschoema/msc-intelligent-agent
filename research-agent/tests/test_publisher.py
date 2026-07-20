from tests.conftest import FakeStructuredLLM, make_source

from src.agents.publisher import PublisherAgent
from src.models import Claim

_NARRATIVE = "Narrative about the topic (One, 2024).\nWhat does question one leave open?"


def _enriched_source(bb):
    bb.save_source(make_source(
        title="Cited Paper", content="[page 1]\ntext", pages=1,
        summary="summary body",
        claims=[Claim(text="a claim", evidence="quote", page=2)],
        ranking="medium", ranking_note="preprint server", citations=12,
    ))


def test_report_has_every_section(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _enriched_source(bb)
    bb.post("SupervisorAgent", "criteria", {"min_words": 300, "min_sources": 2})
    bb.post("ResearchAgent", "decision", {"made_by": "ResearchAgent", "kind": "skip",
                                          "reason": "bad pdf", "payload": {}})
    bb.post("ResearchAgent", "tool_call", {"tool": "search_papers", "args": {"query": "my query"}})
    bb.post("ResearchAgent", "note", {"text": "picked the review because it was most cited"})
    path = PublisherAgent(bb, FakeStructuredLLM(chat_text=_NARRATIVE)).run("My Topic", "Why does it matter?")
    md = open(path, encoding="utf-8").read()

    assert "# Research Brief: My Topic" in md
    assert "**Research question:** Why does it matter?" in md
    assert "## Introduction" in md and "Narrative about the topic (One, 2024)." in md
    assert "## Summary" in md and "## Conclusion" in md
    assert "## Further research" in md and "question one" in md
    assert "### 1. Cited Paper" in md
    assert "summary body (One, 2024)" in md
    assert "_Source reputation: medium — preprint server_" in md
    assert "- a claim (One, 2024, p. 2)" in md
    assert "## Claims and hypotheses" in md
    assert "[reputation: medium]" in md and "[citations: 12]" in md
    assert "[access: open]" in md
    assert "## Limitations" in md and "bad pdf" in md
    assert "## Appendix: run log" in md
    assert "contract: min_words=300, min_sources=2" in md
    assert "called `search_papers(query='my query')`" in md
    assert "picked the review because it was most cited" in md
    assert "**skip** — bad pdf" in md


def test_report_filename_says_what_is_inside(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _enriched_source(bb)
    path = PublisherAgent(bb, FakeStructuredLLM()).run("Federated Learning: privacy risks?")
    assert path.endswith("test-run-federated-learning-privacy-risks.md")


def test_report_pdf_next_to_markdown_and_pointer_on_the_board(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _enriched_source(bb)
    PublisherAgent(bb, FakeStructuredLLM(chat_text=_NARRATIVE)).run("Topic")
    report = bb.posts("report")[0]["content"]
    assert report["pdf_path"].endswith(".pdf")
    assert open(report["pdf_path"], "rb").read(5) == b"%PDF-"
    assert "markdown" not in report


def test_access_labels_tell_the_reader_why_content_is_missing(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(sid="c1", title="Blocked Paper", captcha=True))
    bb.save_source(make_source(sid="r1", title="Paywalled Paper", restricted=True))
    path = PublisherAgent(bb, FakeStructuredLLM()).run("Topic")
    md = open(path, encoding="utf-8").read()
    assert "[access: blocked by CAPTCHA — content not collected]" in md
    assert "[access: restricted — abstract only]" in md


def test_abstract_based_findings_are_marked(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(restricted=True, summary="from the abstract"))
    path = PublisherAgent(bb, FakeStructuredLLM()).run("Topic")
    md = open(path, encoding="utf-8").read()
    assert "_Based on the abstract only — the full text was not accessible._" in md


def test_report_survives_narrative_failure(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(summary="body"))
    path = PublisherAgent(bb, FakeStructuredLLM(chat_text="")).run("Topic")
    md = open(path, encoding="utf-8").read()
    assert "## Introduction" not in md
    assert "body" in md
    assert any("rejected" in d["content"]["reason"] for d in bb.posts("decision"))


def test_boilerplate_sections_are_rejected_never_published(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(summary="body"))
    llm = FakeStructuredLLM(chat_text="This section provides a brief overview.")
    path = PublisherAgent(bb, llm).run("Topic")
    md = open(path, encoding="utf-8").read()
    assert "This section provides" not in md
    assert "## Introduction" not in md and "## Summary" not in md
    assert "body" in md
    rejections = [d for d in bb.posts("decision") if "rejected (boilerplate)" in d["content"]["reason"]]
    assert len(rejections) == 6


def test_echoed_instructions_are_rejected(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(summary="body"))
    llm = FakeStructuredLLM(chat_text="Write the introduction: one paragraph framing the topic.")
    path = PublisherAgent(bb, llm).run("Topic")
    md = open(path, encoding="utf-8").read()
    assert "Write the introduction" not in md
    assert "## Introduction" not in md


def test_echoed_source_material_is_rejected(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.save_source(make_source(summary="body"))
    llm = FakeStructuredLLM(
        chat_text="Topic: something\n\nPaper One — cite as (One, 2024)\nSummary: body",
    )
    path = PublisherAgent(bb, llm).run("Topic")
    md = open(path, encoding="utf-8").read()
    assert "cite as" not in md
    assert "## Introduction" not in md and "## Conclusion" not in md


def test_no_summaries_means_no_narrative_call(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llm = FakeStructuredLLM(chat_text=_NARRATIVE)
    PublisherAgent(bb, llm).run("Topic")
    assert llm.calls == []


def test_report_notes_when_minimums_not_met(bb, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bb.post("SupervisorAgent", "decision", {
        "made_by": "SupervisorAgent", "kind": "converge",
        "reason": "10/300 words, 0/2 reputable sources; minimums NOT met; loop limit reached (1/1) -> publishing",
        "payload": {"met": False},
    })
    path = PublisherAgent(bb, FakeStructuredLLM()).run("Topic")
    md = open(path, encoding="utf-8").read()
    assert "**Published below the requested minimums**" in md
