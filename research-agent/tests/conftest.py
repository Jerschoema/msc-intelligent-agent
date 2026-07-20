import pytest
from langchain_core.messages import AIMessage

from src.memory.blackboard import Blackboard
from src.memory.vector_store import VectorStore
from src.models import Source


def make_source(sid="2401.1v1", title="A Paper", **kw):
    """A source the way the researcher would save one — override what you need."""
    defaults = dict(
        id=sid, title=title, authors=["A. One"], abstract="an abstract",
        publication_date="2024-01-01", journal="arxiv.org", source_db="arxiv",
        url="http://x/abs", full_text_url="http://x/pdf",
        topic="the topic", query="the query",
    )
    defaults.update(kw)
    return Source(**defaults)


class FakeStructuredLLM:
    """Stands in for the chat model wherever agents talk to the LLM.

    Scripted, never contacts a model. For structured output, configure either
    `parsed` (a dict matching the schema — the success path) or `raw_text`
    (the model rambled; parsing fails). Honours both calling styles: with
    include_raw=True it returns the {raw, parsed, parsing_error} dict; plain
    it returns the object or raises. For plain chat calls (the publisher's
    narrative), `chat_text` is what the model says back on every call, or
    pass `chat_texts` (a list) to script a different reply per call in order
    — once the list runs out, `chat_text` is used for any further calls.
    """

    def __init__(self, parsed: dict | None = None, raw_text: str = "",
                 chat_text: str = "", chat_texts: list[str] | None = None):
        self.parsed = parsed
        self.raw_text = raw_text
        self.chat_text = chat_text
        self.chat_texts = list(chat_texts) if chat_texts else None
        self.calls: list = []

    def invoke(self, messages, **kwargs):
        self.calls.append(messages)
        if self.chat_texts:
            return AIMessage(content=self.chat_texts.pop(0))
        return AIMessage(content=self.chat_text)

    def with_structured_output(self, schema, include_raw: bool = False):
        fake = self

        class _Runner:
            def invoke(self, messages):
                fake.calls.append(messages)
                error: Exception | None = None
                parsed = None
                if fake.parsed is None:
                    error = ValueError("scripted parse failure")
                else:
                    try:
                        parsed = schema.model_validate(fake.parsed)
                    except Exception as exc:  # noqa: BLE001
                        error = exc
                if include_raw:
                    return {"raw": AIMessage(content=fake.raw_text), "parsed": parsed, "parsing_error": error}
                if error is not None:
                    raise error
                return parsed

        return _Runner()


class ScriptedResearchAgent:
    """Replaces the researcher's ReAct loop in tests: deterministically
    searches once and fetches every result, through the real tools."""

    def __init__(self, tools):
        self.tools = {t.name: t for t in tools}

    def invoke(self, payload, config=None):
        topic = payload["messages"][0].content
        listing = self.tools["search_papers"].invoke({"query": topic})
        messages = [AIMessage(content="", tool_calls=[
            {"name": "search_papers", "args": {"query": topic}, "id": "c1"},
        ])]
        for line in listing.splitlines():
            if line.startswith("- id="):
                paper_id = line.removeprefix("- id=").split(" |")[0].strip()
                self.tools["fetch_paper"].invoke({"paper_id": paper_id})
                messages.append(AIMessage(content="", tool_calls=[
                    {"name": "fetch_paper", "args": {"paper_id": paper_id}, "id": "c2"},
                ]))
        messages.append(AIMessage(content="Retrieved the most relevant papers."))
        return {"messages": messages}


class ScriptedParseAgent:
    """Replaces the parser's loop in tests: basic-parses every pending
    document, through the real tools."""

    def __init__(self, tools):
        self.tools = {t.name: t for t in tools}

    def invoke(self, payload, config=None):
        ids = payload["messages"][0].content.split(": ", 1)[1].split(", ")
        messages = []
        for source_id in ids:
            self.tools["parse_basic"].invoke({"source_id": source_id})
            messages.append(AIMessage(content="", tool_calls=[
                {"name": "parse_basic", "args": {"source_id": source_id}, "id": "p1"},
            ]))
        messages.append(AIMessage(content="Parsed everything with parse_basic."))
        return {"messages": messages}


@pytest.fixture
def bb(tmp_path):
    return Blackboard("test-run", str(tmp_path / "bb.db"))


@pytest.fixture
def vs(tmp_path):
    return VectorStore(str(tmp_path / "chroma"))
