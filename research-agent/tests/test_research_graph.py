import src.agents.parser as parser_mod
import src.agents.researcher as researcher_mod
import src.tools.parse_tools as parse_tools_mod
import src.tools.research_tools as research_tools_mod
from tests.conftest import FakeStructuredLLM, ScriptedParseAgent, ScriptedResearchAgent, make_source

from main import main
from src.memory.blackboard import Blackboard
from src.memory.vector_store import VectorStore
from src.workflows.research_graph import build_research_graph

_SUMMARY = {
    "summary": "A useful summary.",
    "claims": [{"text": "c", "evidence": "a finding", "page": 1}],
    "justification": "read the text",
}


def _state(tmp_path, topic, llm, run_id="g", min_words=1, min_sources=0):
    bb = Blackboard(run_id, str(tmp_path / "bb.db"))
    bb.post("SupervisorAgent", "criteria", {"min_words": min_words, "min_sources": min_sources})
    return {
        "run_id": run_id,
        "topic": topic,
        "research_question": f"what about {topic}?",
        "loop_count": 0,
        "useful_count": 0,
        "term_count": 0,
        "blackboard": bb,
        "vector_store": VectorStore(str(tmp_path / "chroma")),
        "llm": llm,
        "publish": False,
    }


def _patch_scripted_agents(monkeypatch):
    monkeypatch.setattr(researcher_mod, "create_agent",
                        lambda model, tools, system_prompt=None: ScriptedResearchAgent(tools))
    monkeypatch.setattr(parser_mod, "create_agent",
                        lambda model, tools, system_prompt=None: ScriptedParseAgent(tools))


def test_full_source_lifecycle_produces_the_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _patch_scripted_agents(monkeypatch)
    monkeypatch.setattr(research_tools_mod, "search_arxiv",
                        lambda q: [make_source(topic="", query="")])
    monkeypatch.setattr(research_tools_mod, "download_pdf", lambda url, dest: dest)
    monkeypatch.setattr(parse_tools_mod, "extract_text",
                        lambda path: [(1, "a finding about transformers")])
    llm = FakeStructuredLLM(parsed=_SUMMARY)

    state = _state(tmp_path, "transformers", llm, run_id="happy")
    build_research_graph().invoke(state)

    bb = state["blackboard"]
    source = bb.get_source("2401.1v1")
    assert source.parsed and source.summarised and source.ranked and source.indexed
    hits = state["vector_store"].query("transformers", source_id="2401.1v1")
    assert hits and hits[0].page == 1
    md = open(bb.posts("report")[0]["content"]["path"], encoding="utf-8").read()
    assert "A useful summary." in md
    tools_used = {p["content"]["tool"] for p in bb.posts("tool_call")}
    assert {"search_papers", "fetch_paper", "parse_basic"} <= tools_used


def test_finding_nothing_still_publishes_a_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _patch_scripted_agents(monkeypatch)
    monkeypatch.setattr(research_tools_mod, "search_arxiv", lambda q: [])
    state = _state(tmp_path, "obscure topic", FakeStructuredLLM(),
                   run_id="retry", min_words=50, min_sources=1)
    build_research_graph().invoke(state)

    bb = state["blackboard"]
    kinds = [d["content"]["kind"] for d in bb.posts("decision")]
    assert "retry" in kinds and "converge" in kinds
    md = open(bb.posts("report")[0]["content"]["path"], encoding="utf-8").read()
    assert "**Published below the requested minimums**" in md
    assert "search exhausted" in md


def test_cli_requires_a_topic():
    assert main([]) == 1
    assert main([""]) == 1
    assert main(["   "]) == 1


def test_code_sweeps_still_collect_and_parse_everything(tmp_path, monkeypatch):
    from langchain_core.messages import AIMessage

    class _SearchOnly:
        def __init__(self, tools):
            self.tools = {t.name: t for t in tools}

        def invoke(self, payload, config=None):
            self.tools["search_papers"].invoke({"query": "search query"})
            return {"messages": [AIMessage(content="searched, fetched nothing")]}

    class _GivesUp:
        def invoke(self, payload, config=None):
            return {"messages": [AIMessage(content="could not decide on a parser")]}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(researcher_mod, "create_agent",
                        lambda model, tools, system_prompt=None: _SearchOnly(tools))
    monkeypatch.setattr(parser_mod, "create_agent",
                        lambda model, tools, system_prompt=None: _GivesUp())
    monkeypatch.setattr(research_tools_mod, "search_arxiv",
                        lambda q: [make_source(topic="", query="")])
    monkeypatch.setattr(research_tools_mod, "download_pdf", lambda url, dest: dest)
    monkeypatch.setattr(parse_tools_mod, "extract_text",
                        lambda path: [(1, "rescued by the sweep")])

    state = _state(tmp_path, "topic", FakeStructuredLLM(parsed=_SUMMARY), run_id="sweep")
    build_research_graph().invoke(state)

    source = state["blackboard"].get_source("2401.1v1")
    assert source.file_path
    assert source.parsed and "rescued by the sweep" in source.content
    assert source.indexed


def test_only_useful_sources_count_as_progress(tmp_path, monkeypatch):
    from src.workflows.research_graph import _useful_source
    from tests.conftest import make_source

    assert _useful_source(make_source(ranking="medium"))
    assert not _useful_source(make_source(ranking="low"))
    assert not _useful_source(make_source(ranking="medium", captcha=True))

    import src.workflows.research_graph as graph_mod
    from types import SimpleNamespace
    monkeypatch.setattr(graph_mod, "settings", SimpleNamespace(min_year=2015))
    assert not _useful_source(make_source(ranking="high", publication_date="1998-01-01"))
    assert _useful_source(make_source(ranking="high", publication_date="2024-01-01"))
