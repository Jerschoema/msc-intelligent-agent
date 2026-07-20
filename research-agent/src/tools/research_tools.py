"""The LLM-callable tools the ResearchAgent can choose between.

@tool functions: the model reads each one's name, docstring and args, and
decides which to call. Wrapped in a factory so they close over the
blackboard without exposing it as an argument the model would have to guess.

Fetching stops at download — parsing happens later, in its own stage.
"""

from dataclasses import replace
from pathlib import Path

from langchain_core.tools import tool

from src.config.settings import settings
from src.models import Decision
from src.tools.arxiv_search import search_arxiv
from src.tools.openalex_search import search_openalex as openalex_search
from src.tools.pdf_parser import download_pdf
from src.tools.semanticscholar_search import search_semanticscholar as s2_search
from src.tools.web_fetch import fetch_html

_NAME = "ResearchAgent"


def fetch_source(blackboard, source) -> str:
    """Download one source's full text onto the record.

    Shared by the agent's fetch tool and the collection sweep in the graph:
    the agent decides which papers matter most, the sweep guarantees nothing
    open is left behind. Returns the message the model (or the log) reads.
    """
    if source.file_path:
        return f"{source.id} is already downloaded; no need to fetch it again."

    if source.restricted or not source.full_text_url:
        # Not a failure — the abstract still gets analysed downstream.
        blackboard.post(
            _NAME, "decision",
            Decision(
                _NAME, "restricted",
                f"no full-text access for {source.id}; will analyse its abstract only",
                {"source_id": source.id},
            ).to_dict(),
        )
        return (
            f"{source.id} has restricted access (no full text). Its abstract "
            "will still be analysed — do not retry; consider one more open paper instead."
        )

    # HTML source: fetch the page now, so anti-bot blocks surface here with
    # their own label — the report must distinguish "paywalled" from
    # "blocked by CAPTCHA". We never try to evade a challenge.
    if source.file_type == "html":
        status, text = fetch_html(source.full_text_url)
        if status == "captcha":
            source.captcha = True
            blackboard.save_source(source)
            blackboard.post(
                _NAME, "decision",
                Decision(
                    _NAME, "captcha",
                    f"anti-bot challenge blocked {source.id} at {source.full_text_url}",
                    {"source_id": source.id},
                ).to_dict(),
            )
            return (
                f"{source.id} is protected by a CAPTCHA/anti-bot page and cannot "
                "be collected. Its abstract will still be analysed — pick a "
                "different paper."
            )
        if status != "ok":
            blackboard.post(
                _NAME, "decision",
                Decision(_NAME, "skip", f"could not fetch web page for {source.id}",
                         {"source_id": source.id}).to_dict(),
            )
            return f"Could not fetch {source.id}. Pick a different paper."
        path = Path(settings.data_dir) / "pages" / f"{source.id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        source.file_path = str(path)
        blackboard.save_source(source)
        return f"Downloaded the web page for {source.id}. It will be parsed next."

    # PDF source.
    dest = str(Path(settings.data_dir) / "pdfs" / f"{source.id}.pdf")
    if not download_pdf(source.full_text_url, dest):
        blackboard.post(
            _NAME, "decision",
            Decision(_NAME, "skip", f"could not download PDF for {source.id}",
                     {"source_id": source.id}).to_dict(),
        )
        return f"Could not fetch {source.id}. Pick a different paper."
    source.file_path = dest
    blackboard.save_source(source)
    return f"Downloaded {source.id} (PDF). It will be parsed next."


def make_research_tools(blackboard, topic: str = "") -> list:
    """Build the research toolset bound to this run's blackboard."""

    def _run_search(search_fn, query: str, engine: str) -> str:
        """Every engine returns standard Source objects """
        if len(query.split()) < 2:
            # A bare single word ("transformer") is generic enough to match
            # almost any field
            blackboard.post(
                _NAME, "decision",
                Decision(_NAME, "error",
                         f"query {query!r} is too generic (single word) for {engine}; rejected").to_dict(),
            )
            return (
                "That query is too generic — a single word can match unrelated "
                "fields. Add at least one more term tied to the topic itself "
                "(e.g. the specific task or domain, not just the architecture) "
                "and try again."
            )
        results = search_fn(query)
        if not results:
            blackboard.post(
                _NAME, "decision",
                Decision(_NAME, "error", f"no {engine} results for query {query!r}").to_dict(),
            )
            return "No results found. Try a broader or different query, or a different search engine."
        known = {s.id for s in blackboard.sources()}
        for source in results:
            if source.id not in known:
                # Stamp how it was found — the topic researched and the query
                # that surfaced it stay on the source forever.
                blackboard.save_source(replace(source, topic=topic, query=query))
        return "\n".join(source.describe() for source in results)

    @tool
    def search_papers(query: str) -> str:
        """Search arXiv (open-access preprints: machine learning, computer
        science, physics, maths). All results have retrievable full text.
        Use a concise keyword query, not a full sentence."""
        return _run_search(search_arxiv, query, "arxiv")

    @tool
    def search_openalex(query: str) -> str:
        """Search OpenAlex (~250M scholarly works across every academic field,
        including peer-reviewed journals). A solid default whenever you're
        unsure which engine fits — worth trying even for CS/ML topics, not
        only as a fallback. Some results are restricted: only their abstract
        can be analysed."""
        return _run_search(openalex_search, query, "openalex")

    @tool
    def search_semanticscholar(query: str) -> str:
        """Search Semantic Scholar (~220M papers, strongest for computer
        science; includes peer-reviewed publishers). May be rate-limited: if it
        returns no results, switch to search_papers or search_openalex rather
        than retrying it."""
        return _run_search(s2_search, query, "semanticscholar")

    @tool
    def fetch_paper(paper_id: str) -> str:
        """Download the full text of one paper found by a search tool (its PDF,
        or its web page for html sources). Parsing happens later — just fetch.
        Only fetch papers that are clearly relevant to the research topic."""
        source = blackboard.get_source(paper_id)
        if source is None:
            return f"Unknown paper id {paper_id!r}. Use an id returned by a search tool."
        return fetch_source(blackboard, source)

    return [search_papers, search_openalex, search_semanticscholar, fetch_paper]
