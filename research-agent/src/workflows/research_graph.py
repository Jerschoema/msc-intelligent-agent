"""The research pipeline is a structured workflow:

    START → research → parse → summarise → rank → index → discovery → converge
               ▲                                                         │
               └───────────────── (retry) ──────────────────────────────┤
                                                            (publish) → publish → END

In the design proposal we noted that the academic research process is a structured workflow.
The research pipeline is autonomous in that it decides what to do, which sources to use 
and ultimately the content of the final publication. 

However, the workflow is structured because it makes the process fully auditable which
is important for academic research and because a major design challenge is defining 
the stopping condition for the autonomous research agent and analyzing so much information
within the limited context window size. Therefore, the goal is to retrieve the most relevant
sources and produce a report that is useful to the user.

The pipeline will repeat until the convergence criteria are met by the SupervisorAgent.

"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.keywords import DiscoveryAgent
from src.agents.parser import ParseAgent
from src.agents.publisher import PublisherAgent
from src.agents.ranking import RankingAgent
from src.agents.researcher import ResearchAgent
from src.agents.summarise import SummariseAgent
from src.agents.supervisor import SupervisorAgent
from src.config.settings import settings
from src.models import Decision
from src.tools.parse_tools import basic_parse
from src.tools.pdf_parser import chunk_text, text_to_pages
from src.tools.research_tools import fetch_source


class ResearchState(TypedDict):
    run_id: str
    topic: str
    research_question: str
    loop_count: int
    # What the last convergence check saw — lets the Supervisor tell whether a
    # retry actually made progress (useful sources, new discovery terms).
    useful_count: int
    term_count: int
    # Handles (kept in state so nodes stay pure and tests can inject fakes):
    blackboard: object
    vector_store: object
    llm: object
    # Internal: the convergence verdict, read by the conditional edge.
    publish: bool


def _research(state: ResearchState) -> dict:
    ResearchAgent(state["blackboard"], state["llm"]).run(
        state["topic"], state["research_question"], state["loop_count"]
    )
    return {}


def _parse(state: ResearchState) -> dict:
    bb, llm = state["blackboard"], state["llm"]

    # Cvery open source gets collected. The agent decides which ones are relevant.
   
    for source in bb.sources():
        if not source.file_path and source.full_text_url and not source.restricted and not source.captcha:
            fetch_source(bb, source)

    ParseAgent(bb, llm).run()

    #everything downloaded gets at least the basic parse.
   
    for source in bb.sources():
        if source.file_path and not source.parsed:
            if basic_parse(bb, source):
                bb.post("ParseAgent", "decision", Decision(
                    "ParseAgent", "strategy",
                    f"{source.id}: fallback to parse_basic (sweep)",
                    {"source_id": source.id},
                ).to_dict())
    return {}


def _summarise(state: ResearchState) -> dict:
    SummariseAgent(state["blackboard"], state["llm"]).run(state["topic"], state["research_question"])
    return {}


def _rank(state: ResearchState) -> dict:
    RankingAgent(state["blackboard"], state["llm"]).run()
    return {}


def _index(state: ResearchState) -> dict:
    #Every source will get indexed in the vector store
    bb, vs = state["blackboard"], state["vector_store"]
    for source in bb.sources():
        if not source.parsed or source.indexed:
            continue
        chunks = chunk_text(text_to_pages(source.content), source.id)
        vs.add_chunks(chunks, extra_meta=source.citation_meta())
        source.indexed = True
        bb.save_source(source)
        bb.post("Indexer", "decision", Decision(
            "Indexer", "indexed",
            f"{source.id}: {len(chunks)} chunks into the vector store",
            {"source_id": source.id},
        ).to_dict())
    return {}


def _discover(state: ResearchState) -> dict:
    DiscoveryAgent(state["blackboard"], state["llm"]).run()
    return {}


def _useful_source(source) -> bool:
    """Progress means finding sources worth keeping: 
    1. Reputable 
    2. Related to the topic
    3. Collectable, 
    4. If min_year is set then if is recent enough."""
    year = int(source.publication_date[:4] or 0)
    recent_enough = settings.min_year == 0 or year >= settings.min_year
    return (
        source.ranking in ("high", "medium")
        and source.relevance != "unrelated"
        and not source.captcha
        and recent_enough
    )


def _converge(state: ResearchState) -> dict:
    bb = state["blackboard"]
    sources = bb.sources()
    useful = sum(1 for s in sources if _useful_source(s))
    terms = sum(
        len(s.discovery.get("keywords", [])) + len(s.discovery.get("topics", []))
        for s in sources
    )
    publish = SupervisorAgent(bb, state["llm"]).converge(
        state["loop_count"],
        new_sources=useful > state["useful_count"],
        new_topics=terms > state["term_count"],
    )
    # Bump the loop counter only when we are about to retry, so the researcher
    # knows to load context and broaden.
    return {
        "publish": publish,
        "useful_count": useful,
        "term_count": terms,
        "loop_count": state["loop_count"] + (0 if publish else 1),
    }


def _route(state: ResearchState) -> str:
    return "publish" if state["publish"] else "retry"


def _publish(state: ResearchState) -> dict:
    PublisherAgent(state["blackboard"], state["llm"]).run(
        state["topic"], state["research_question"]
    )
    return {}


def build_research_graph():
    graph = StateGraph(ResearchState)
    graph.add_node("research", _research)
    graph.add_node("parse", _parse)
    graph.add_node("summarise", _summarise)
    graph.add_node("rank", _rank)
    graph.add_node("index", _index)
    graph.add_node("discover", _discover)
    graph.add_node("converge", _converge)
    graph.add_node("publish", _publish)

    graph.add_edge(START, "research")
    graph.add_edge("research", "parse")
    graph.add_edge("parse", "summarise")
    graph.add_edge("summarise", "rank")
    graph.add_edge("rank", "index")
    graph.add_edge("index", "discover")
    graph.add_edge("discover", "converge")
    # Retry re-enters at research: the agent gets the discovery terms and goes
    # looking for more. All enrichment nodes no-op on anything already done.
    graph.add_conditional_edges("converge", _route, {"publish": "publish", "retry": "research"})
    graph.add_edge("publish", END)
    return graph.compile()
