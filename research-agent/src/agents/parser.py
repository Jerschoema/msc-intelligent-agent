"""The parse agent chooses how to parse each downloaded document.

It retrieves the sources from the blackboard and extracts the content from them.
The model inspects each document, decides which parser is the most suitable from the tools 
(Grobic, unstructured, basic, html, etc).

The agent then uses the chosen parser to extract the content and saves it back to the blackboard.


"""

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from src.agents.trace import record_tool_trace
from src.config.settings import settings
from src.models import Decision
from src.tools.parse_tools import make_parse_tools

_SYSTEM_PROMPT = (
    "You prepare downloaded documents for analysis. For EACH document:\n"
    "1. Call inspect_document to see what it is.\n"
    "2. Pick the most suitable parser and call it:\n"
    "   - parse_with_grobid: academic PDFs (papers with sections/references);\n"
    "   - parse_with_unstructured: messy or non-academic PDF layouts;\n"
    "   - parse_basic: web pages, and the fallback whenever another parser is "
    "unavailable or fails.\n"
    "3. End with one sentence per document naming your parser choice and why.\n"
    "\n"
    "Example:\n"
    "  inspect_document('X1') -> 'PDF, 21 pages. First page sample: Abstract...'\n"
    "  parse_with_grobid('X1') -> 'GROBID is not available here. Use parse_basic instead.'\n"
    "  parse_basic('X1') -> 'Parsed X1 with parse_basic: 21 page(s). Move on to the next document.'\n"
    "  Final reply: 'X1: academic PDF, used parse_basic because GROBID is offline.'"
)


class ParseAgent:
    name = "ParseAgent"

    def __init__(self, blackboard, llm) -> None:
        self.bb = blackboard
        self.llm = llm

    def run(self) -> None:
        pending = sorted(s.id for s in self.bb.sources() if s.file_path and not s.parsed)
        if not pending:
            return 

        tools = make_parse_tools(self.bb)
        agent = create_agent(self.llm, tools, system_prompt=_SYSTEM_PROMPT)
        try:
            result = agent.invoke(
                {"messages": [HumanMessage("Documents to prepare: " + ", ".join(pending))]},
                config={"recursion_limit": settings.agent_max_steps},
            )
            record_tool_trace(self.bb, self.name, result["messages"])
        except Exception as exc:  
         
            self.bb.post(
                self.name, "decision",
                Decision(self.name, "error", f"parse agent failed: {exc}").to_dict(),
            )
