"""The research agent finds and downloads sources for a topic.

The research agent has to find the minimum number of reputable sources the user requested. 
It does by deciding which search engine to use and crafting queries to find relevant papers. 
However, there is limit to the agent loop because retrieving relevant sources is potentially a bottomless pit.
So the agent might not be able to retrieve all sources. 

There are two mechanisms:

1. The langraph workflow will manage how often the researcher will be called until the minimum number of sources is found or the loop limit is reached.
However, that is managed outside of this agent. This agent will only be called once per loop. 
Therefore, we ensure that all relevant sources will be considered in another loop.

2. We rely on the search engines ability to return relevant results. 
Therefore, the agent will not have to exhaustively scan all results from a query. 
Only the top results (managed via settings). This makes the limitation less relevant.

On subsequent loops it will build a context from the blackboard that will preven it from
repeating the same queries and will give it new keywords, topics and titles to try finding
new information.


All papers are posted to the blackboard.
"""

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from src.agents.trace import record_tool_trace
from src.config.settings import settings
from src.models import Decision
from src.tools.research_tools import make_research_tools

_SYSTEM_PROMPT = (
    "You are a research assistant gathering academic sources on a topic.\n"
     "1. Pick the right search engine and call it with a concise keyword query:\n"
    "   - search_openalex indexes ~250M works across EVERY academic field "
    "(sciences, medicine, social science, humanities, economics...) — a "
    "solid default whenever you are unsure, and worth trying even for "
    "CS/ML topics, not only as a fallback;\n"
    "   - search_papers (arXiv) is worth trying alongside it for physics, "
    "math, CS, quantitative biology/finance, statistics and economics and variety of other scientific disciplines "
    "it's a preprint server, so it only covers those disciplines;\n"
    "   - search_semanticscholar also covers every field and is a good "
    "second opinion (if it returns nothing, use another engine instead of "
    "retrying).\n"
    "2. Craft queries deliberately: try synonyms and related concepts "
    "('automated driving' vs 'autonomous vehicles'), and use the titles and "
    "abstracts of results for terminology worth a follow-up search. Every "
    "query needs at least two specific terms anchored to the topic itself "
    "(the task/domain, not just a method or architecture name) — a bare "
    "generic word like 'transformer' alone matches unrelated fields (vision, "
    "medical imaging, robotics...) and is rejected.\n"
    "3. Judge which results are most relevant to the topic — not merely "
    "related because they share a technique or keyword. A paper that reuses "
    "the same method in a different field (e.g. a vision or forecasting "
    "paper turning up under a code-generation topic) is NOT relevant. Prefer "
    "papers without content restrictions (the entire text is available))"
   
    "4. Call fetch_paper for EVERY paper that is clearly relevant to the "
    "topic — skip only the irrelevant and the restricted ones. "
    "5. ALWAYS fetch before you finish: a report based on full access is better than one based on abstracts. "
  
    "6. End with ONE sentence naming what you retrieved and why.\n"
    "\n"
    "Example:\n"
    "  search_papers('graph neural network traffic forecasting')\n"
    "  -> '- id=2101.1v1 | Traffic GNN (2021)...\\n- id=2102.2v1 | ...'\n"
    "  fetch_paper('2101.1v1') -> 'Downloaded 2101.1v1 (PDF). It will be parsed next.'\n"
    "  Final reply: 'Retrieved Traffic GNN as the most directly relevant paper.'"
)


class ResearchAgent:
    name = "ResearchAgent"

    def __init__(self, blackboard, llm) -> None:
        self.bb = blackboard
        self.llm = llm

    def run(self, topic: str, research_question: str = "", loop_count: int = 0) -> None:
        tools = make_research_tools(self.bb, topic)
        agent = create_agent(self.llm, tools, system_prompt=_SYSTEM_PROMPT)
        task = f"Research topic: {topic}"
        if research_question:
            task += f"\nResearch question: {research_question}"
        

        #We build a task here and make sure the agent is aware of the user's minimum requirements.
        criteria = self.bb.posts("criteria")
        min_sources = criteria[-1]["content"].get("min_sources", 0) if criteria else 0
        if min_sources:
            task += (
                f"\nThe user requires at least {min_sources} reputable sources: "
                "fetch every clearly relevant open paper until you comfortably "
                "exceed that."
            )
        if loop_count > 0:
            task += self._load_context()
        try:
            result = agent.invoke(
                {"messages": [HumanMessage(task)]},
                config={"recursion_limit": settings.agent_max_steps},
            )
            record_tool_trace(self.bb, self.name, result["messages"])
        except Exception as exc:  # noqa: BLE001
            # Post-and-continue: converge will retry once or publish a partial report.
            self.bb.post(
                self.name, "decision",
                Decision(self.name, "error", f"research agent failed: {exc}").to_dict(),
            )

    def _load_context(self) -> str:
        """Brief a retry with everything the blackboard already knows.

        The context is populated with following items:
          1.  which queries were already tried (tool_call posts, including ones that found nothing),
          2.  which search directions the DiscoveryAgent found from the sources, 
          3.  and what was already found. 
          
        This is what allows the agent to discovery.
        
        """
        tried = {
            p["content"]["args"]["query"]
            for p in self.bb.posts("tool_call")
            if p["content"]["tool"].startswith("search") and p["content"]["args"].get("query")
        }
        keywords: list[str] = []
        topics: list[str] = []
        titles: list[str] = []
        for source in self.bb.sources():
            keywords += source.discovery.get("keywords", [])
            topics += source.discovery.get("topics", [])
            titles.append(source.title)

        lines = [
            "\nThe first pass retrieved too little. Craft DIFFERENT queries this time:"
            " use synonyms, related concepts, a broader umbrella term, or another engine "
            "— but every query must still carry at least two specific terms anchored to "
            "the topic itself; do not fall back to a single generic word."
        ]
        if tried:
            lines.append("Already tried (do not repeat): " + "; ".join(sorted(tried)))
        if keywords or topics:
            lines.append(
                "Search directions mined from the sources found so far — "
                f"keywords: {', '.join(dict.fromkeys(keywords))}; "
                f"topics: {', '.join(dict.fromkeys(topics))}."
            )
        if titles:
            lines.append("Already found (do not fetch again): " + "; ".join(titles[:5]))
        return "\n".join(lines)
