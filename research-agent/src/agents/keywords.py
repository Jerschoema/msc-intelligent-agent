"""The discovery agent mines each source for keywords and related topics to discover new research directions.

Every source we read gives us more understanding about the research topic. 

the agent looks at each source without discovery terms yet and asks the model for keywords and
related topics worth further investigation. 

The researcher agent may decide to use this to find more relevant sources.

"""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from src.models import Decision


class _DiscoverySchema(BaseModel):
    keywords: list[str] = []  # specific terms/methods/synonyms worth searching
    topics: list[str] = []  # broader or related fields
    justification: str = ""  # why these are worth following up


_SYSTEM = (
    "You extract search directions from an academic source's title and "
    "abstract. Return keywords (specific terms, methods and synonyms worth "
    "searching for related work) and topics (broader or related fields), "
    "three to five of each, lowercase. One sentence of justification.\n\n"
    'Example — title "LLM-Mixer: Multiscale Mixing in LLMs for Time Series '
    'Forecasting" -> keywords: ["multiscale decomposition", "frozen '
    'pretrained llm", "long-term forecasting benchmarks"], topics: ["time '
    'series forecasting", "large language models"]'
)


class DiscoveryAgent:
    name = "DiscoveryAgent"

    def __init__(self, blackboard, llm) -> None:
        self.bb = blackboard
        self.llm = llm

    def run(self) -> None:
        for source in self.bb.sources():
            if source.mined:
                continue  # never mine twice
            try:
                parsed = self.llm.with_structured_output(_DiscoverySchema).invoke([
                    SystemMessage(_SYSTEM),
                    HumanMessage(f"Title: {source.title}\nAbstract: {source.abstract[:800]}"),
                ])
                source.discovery = {"keywords": parsed.keywords, "topics": parsed.topics}
                self.bb.save_source(source)
                self.bb.post(
                    self.name, "decision",
                    Decision(self.name, "discovered",
                             parsed.justification or f"mined {source.id}",
                             {"source_id": source.id}).to_dict(),
                )
            except Exception as exc:  # noqa: BLE001
                # One bad extraction shouldn't stop the run; on the record.
                self.bb.post(
                    self.name, "decision",
                    Decision(self.name, "error",
                             f"discovery failed for {source.id}: {exc}").to_dict(),
                )
