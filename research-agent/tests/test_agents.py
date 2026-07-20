from langchain_core.messages import AIMessage

import src.agents.parser as parser_mod
import src.agents.researcher as researcher_mod
import src.tools.research_tools as research_tools_mod
from tests.conftest import FakeStructuredLLM, ScriptedParseAgent, ScriptedResearchAgent, make_source

from src.agents.keywords import DiscoveryAgent
from src.agents.parser import ParseAgent
from src.agents.researcher import ResearchAgent
from src.agents.summarise import SummariseAgent
from src.models import Claim
from src.tools.pdf_parser import pages_to_text


def test_research_agent_records_its_tool_choices(bb, monkeypatch):
    monkeypatch.setattr(
        researcher_mod, "create_agent",
        lambda model, tools, system_prompt=None: ScriptedResearchAgent(tools),
    )
    monkeypatch.setattr(research_tools_mod, "search_arxiv", lambda q: [make_source(topic="", query="")])
    monkeypatch.setattr(research_tools_mod, "download_pdf", lambda url, dest: dest)
    ResearchAgent(bb, llm=None).run("some topic", "why does it matter?")

    calls = [p["content"]["tool"] for p in bb.posts("tool_call")]
    assert calls == ["search_papers", "fetch_paper"]
    assert len(bb.sources()) == 1
    assert bb.posts("note")


def test_research_agent_fetch_depth_comes_from_the_user_contract(bb, monkeypatch):
    captured = {}

    class _Capture:
        def invoke(self, payload, config=None):
            captured["task"] = payload["messages"][0].content
            return {"messages": [AIMessage(content="done")]}

    monkeypatch.setattr(researcher_mod, "create_agent",
                        lambda model, tools, system_prompt=None: _Capture())
    bb.post("SupervisorAgent", "criteria", {"min_words": 300, "min_sources": 3})
    ResearchAgent(bb, llm=None).run("topic")
    assert "at least 3 reputable sources" in captured["task"]


def test_research_agent_failure_becomes_a_decision_not_a_crash(bb, monkeypatch):
    class _Exploding:
        def invoke(self, payload, config=None):
            raise RuntimeError("recursion limit reached")

    monkeypatch.setattr(researcher_mod, "create_agent",
                        lambda model, tools, system_prompt=None: _Exploding())
    ResearchAgent(bb, llm=None).run("topic")
    assert bb.posts("decision")[-1]["content"]["kind"] == "error"


def test_research_agent_retry_is_briefed_from_the_blackboard(bb, monkeypatch):
    captured = {}

    class _Capture:
        def invoke(self, payload, config=None):
            captured["task"] = payload["messages"][0].content
            return {"messages": [AIMessage(content="done")]}

    monkeypatch.setattr(researcher_mod, "create_agent",
                        lambda model, tools, system_prompt=None: _Capture())
    bb.post("ResearchAgent", "tool_call", {"tool": "search_papers", "args": {"query": "quantum ml"}})
    bb.save_source(make_source(title="Quantum Kernels Paper",
                               discovery={"keywords": ["variational circuits"], "topics": ["quantum computing"]}))

    ResearchAgent(bb, llm=None).run("topic", "question", loop_count=1)
    task = captured["task"]
    assert "Research question: question" in task
    assert "quantum ml" in task
    assert "variational circuits" in task
    assert "Quantum Kernels Paper" in task


def test_parse_agent_parses_every_pending_document(bb, monkeypatch):
    monkeypatch.setattr(parser_mod, "create_agent",
                        lambda model, tools, system_prompt=None: ScriptedParseAgent(tools))
    sample = str(__import__("pathlib").Path(
        "src/tools/samples/academic_paper_pdf_with_abstract_sample_1.pdf").resolve())
    bb.save_source(make_source(sid="p1", file_path=sample))
    ParseAgent(bb, llm=None).run()
    assert bb.get_source("p1").parsed
    assert any(p["content"]["tool"] == "parse_basic" for p in bb.posts("tool_call"))


def test_parse_agent_does_nothing_when_nothing_is_pending(bb):
    bb.save_source(make_source())
    ParseAgent(bb, llm=None).run()
    assert bb.posts("tool_call") == []


def test_summarise_fills_summary_and_claims_with_justification(bb):
    bb.save_source(make_source(content="[page 3]\nthe key finding is here", pages=1))
    llm = FakeStructuredLLM(parsed={
        "summary": "A short summary.",
        "claims": [{"text": "the claim", "evidence": "the key finding is here", "page": 3}],
        "justification": "based on the results section",
    })
    SummariseAgent(bb, llm).run()
    source = bb.get_source("2401.1v1")
    assert source.summary == "A short summary."
    assert source.claims[0].page == 3
    decision = bb.posts("decision")[-1]["content"]
    assert decision["kind"] == "summarised"
    assert decision["reason"] == "based on the results section"


def test_summarise_never_summarises_twice(bb):
    bb.save_source(make_source(summary="already done"))
    llm = FakeStructuredLLM(parsed={"summary": "should never be asked"})
    SummariseAgent(bb, llm).run()
    assert llm.calls == []
    assert bb.get_source("2401.1v1").summary == "already done"


def test_summarise_falls_back_to_the_abstract_with_zeroed_pages(bb):
    bb.save_source(make_source(sid="r1", restricted=True))
    llm = FakeStructuredLLM(parsed={
        "summary": "From the abstract alone.",
        "claims": [{"text": "c", "evidence": "an abstract", "page": 7}],
    })
    SummariseAgent(bb, llm).run()
    source = bb.get_source("r1")
    assert source.summary == "From the abstract alone."
    assert source.claims[0].page == 0
    system, human = llm.calls[0]
    assert "ABSTRACT" in human.content


def test_summarise_keeps_raw_text_when_parsing_fails(bb):
    bb.save_source(make_source(content="[page 1]\ntext"))
    SummariseAgent(bb, FakeStructuredLLM(raw_text="the model rambled")).run()
    assert bb.get_source("2401.1v1").summary.startswith("the model rambled")
    assert any(d["content"]["kind"] == "error" for d in bb.posts("decision"))


def test_summarise_skips_sources_with_nothing_to_read(bb):
    bb.save_source(make_source(abstract="   "))
    llm = FakeStructuredLLM(parsed={"summary": "x"})
    SummariseAgent(bb, llm).run()
    assert llm.calls == []


def test_summarise_batches_long_papers_and_integrates(bb):
    content = pages_to_text([(1, "x" * 7000), (2, "y" * 7000)])
    bb.save_source(make_source(content=content, pages=2))
    llm = FakeStructuredLLM(parsed={
        "summary": "A batch summary.",
        "claims": [{"text": "a claim", "evidence": "x", "page": 1}],
    })
    SummariseAgent(bb, llm).run()
    source = bb.get_source("2401.1v1")
    assert source.summarised
    assert len(llm.calls) == 3
    assert source.summary == "A batch summary."
    assert len(source.claims) == 2


def test_discovery_fills_terms_once_with_justification(bb):
    bb.save_source(make_source(sid="p1"))
    bb.save_source(make_source(sid="p2", discovery={"keywords": ["done"]}))
    llm = FakeStructuredLLM(parsed={
        "keywords": ["term a"], "topics": ["field b"], "justification": "promising directions",
    })
    DiscoveryAgent(bb, llm).run()
    assert len(llm.calls) == 1
    assert bb.get_source("p1").discovery == {"keywords": ["term a"], "topics": ["field b"]}
    assert bb.posts("decision")[-1]["content"]["reason"] == "promising directions"


def test_discovery_failure_degrades_to_a_decision(bb):
    bb.save_source(make_source())
    DiscoveryAgent(bb, FakeStructuredLLM(raw_text="??")).run()
    assert not bb.get_source("2401.1v1").mined
    assert any("discovery failed" in d["content"]["reason"] for d in bb.posts("decision"))
