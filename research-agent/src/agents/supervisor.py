"""The Supervisor owns the run's contract: what to research, and when it's done.

Two jobs:

1. ``intake`` the user states the topic, the research question, and the
   minimum sources and words. The agent will ground the prompt. Users can press
   enter to accept defaults.

2. ``converge``  The run keeps
   researching while it is still learning: it stops when a pass produced no
   new sources that are meet the useful_source func criteria in the langgraph pipeline
   and there are no undiscovered topics, or if the loop limit is reached.
   
Note that the the user's minimums are a floor. The loop limit guarantees
the run will stop and be able to produce a quality report. 
 

   
"""

import sys

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from src.config.settings import settings
from src.models import Decision

DEFAULT_MIN_WORDS = 300
DEFAULT_MIN_SOURCES = 2


class _IntakeSchema(BaseModel):
    topic: str
    research_question: str = ""  # "" = the user did not state one
    min_words: int = 0  # 0 = not stated
    min_sources: int = 0


_INTAKE_SYSTEM = (
    "You read a research request and separate its parts: the topic, the "
    "research question (if the user phrased one), min_words (required length "
    "of the final report) and min_sources (required number of reputable "
    "sources). Use 0 or an empty string for anything not stated.\n\n"
    'Example: "LLM safety benchmarks — can they be gamed? At least 4 solid '
    'sources and 800 words" -> topic: "LLM safety benchmarks", '
    'research_question: "Can LLM safety benchmarks be gamed?", '
    "min_words: 800, min_sources: 4."
)


class SupervisorAgent:
    name = "SupervisorAgent"

    def __init__(self, blackboard, llm=None) -> None:
        self.bb = blackboard
        self.llm = llm

    # grounding of the prompt

    def intake(self, request: str) -> tuple[str, str, dict]:
        """Turn the user's request into (topic, research_question, criteria)
        and post the contract to the blackboard."""
        topic, question, min_words, min_sources = request, "", 0, 0
        try:
            parsed = self.llm.with_structured_output(_IntakeSchema).invoke(
                [SystemMessage(_INTAKE_SYSTEM), HumanMessage(request)]
            )
            if parsed.topic.strip():
                topic = parsed.topic.strip()
                question = parsed.research_question.strip()
                min_words, min_sources = parsed.min_words, parsed.min_sources
        except Exception:  # noqa: BLE001
            pass  # keep the raw request as the topic; ask for the rest below

        # Whatever the user didn't state, make them specify
        if not question:
            question = self._ask_text("Research question", default=topic)
        if min_words <= 0:
            min_words = self._ask_int("Minimum report length in words", DEFAULT_MIN_WORDS)
        if min_sources <= 0:
            min_sources = self._ask_int("Minimum number of reputable sources", DEFAULT_MIN_SOURCES)

        criteria = {
            "topic": topic,
            "research_question": question,
            "min_words": min_words,
            "min_sources": min_sources,
        }
        self.bb.post(self.name, "criteria", criteria)
        return topic, question, criteria

    @staticmethod
    def _ask_text(prompt: str, default: str) -> str:
        """Interactive prompt with a default; non-interactive runs 
        silently take the default."""
        if not sys.stdin.isatty():
            return default
        answer = input(f"{prompt} [{default}]: ").strip()
        return answer or default

    @staticmethod
    def _ask_int(prompt: str, default: int) -> int:
        if not sys.stdin.isatty():
            return default
        answer = input(f"{prompt} [{default}]: ").strip()
        try:
            return int(answer) if answer else default
        except ValueError:
            return default

    # -- convergence ----------------------------------------------------------

    def converge(self, loop_count: int, new_sources: bool = True, new_topics: bool = True) -> bool:
        """True = publish, False = research again. Records why either way."""
        posts = self.bb.posts("criteria")
        criteria = posts[-1]["content"] if posts else {}
        min_words = criteria.get("min_words", DEFAULT_MIN_WORDS)
        min_sources = criteria.get("min_sources", DEFAULT_MIN_SOURCES)

        sources = self.bb.sources()
        on_topic = [s for s in sources if s.relevance != "unrelated"]
        words = sum(len(s.summary.split()) for s in on_topic)
        # "Reputable" = ranked high or medium, and actually on topic.
        reputable = sum(1 for s in on_topic if s.ranking in ("high", "medium"))
        met = words >= min_words and reputable >= min_sources

        # Stop when the run stops learning (refer to langgraph useful_source func)
        # or at the loop limit. The minimums do NOT stop the run.

        exhausted = loop_count > 0 and not new_sources and not new_topics
        at_cap = loop_count >= settings.max_loops
        publish = exhausted or at_cap

        reason = (
            f"{words}/{min_words} words, {reputable}/{min_sources} reputable sources; "
            + ("minimums met" if met else "minimums NOT met")
            + ("; search exhausted (no new sources, no new topics)" if exhausted else "")
            + (f"; loop limit reached ({loop_count}/{settings.max_loops})" if at_cap else "")
            + (" -> publishing" if publish else " -> researching further")
        )
        self.bb.post(
            self.name, "decision",
            Decision(
                self.name,
                "converge" if publish else "retry",
                reason,
                {"words": words, "reputable": reputable, "loop": loop_count, "met": met},
            ).to_dict(),
        )
        return publish
