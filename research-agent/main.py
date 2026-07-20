"""CLI tool to prompt the agent.

A request states the topic, the research question, and the minimums for the
report. Whatever is left out gets asked for interactively
(or defaults, when not running in a terminal).

Usage:
    python main.py "federated learning for medical imaging — what are the privacy risks? minimum 5 reputable sources and 800 words"
    python main.py "transformer models for time series forecasting"   # asked for the rest
    python main.py --deep "..."    # raised budgets: chase every relevant source
"""

import sys
from datetime import datetime

from dotenv import load_dotenv

from src.agents.supervisor import SupervisorAgent
from src.config.settings import enable_deep_mode, settings
from src.llm.factory import get_llm
from src.memory.blackboard import Blackboard
from src.memory.vector_store import VectorStore
from src.workflows.research_graph import build_research_graph


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    argv = sys.argv[1:] if argv is None else argv
    if "--deep" in argv:
        argv = [a for a in argv if a != "--deep"]
        enable_deep_mode()
    # The user must state the topic. Reject both a missing arg and an
    # empty/whitespace one (e.g. main.py "") — there is nothing to research.
    request = " ".join(argv).strip()
    if not request:
        print('Usage: python main.py "<topic> — <research question>? <minimum sources and words>"')
        print('  e.g. python main.py "federated learning for medical imaging — what are the '
              'privacy risks? minimum 5 reputable sources and 800 words"')
        print("  Anything you leave out will be asked for (topic is required).")
        return 1
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    blackboard = Blackboard(run_id)
    vector_store = VectorStore()
    llm = get_llm()

    # Grounding: split topic, research question and minimums out of the request

    topic, question, criteria = SupervisorAgent(blackboard, llm).intake(request)
    print(f"[run {run_id}] researching: {topic!r}")
    print(f"[question] {question}")
    print(f"[criteria] ≥{criteria['min_words']} words, ≥{criteria['min_sources']} reputable sources")

    graph = build_research_graph()
    graph.invoke(
        {
            "run_id": run_id,
            "topic": topic,
            "research_question": question,
            "loop_count": 0,
            "useful_count": 0,
            "term_count": 0,
            "blackboard": blackboard,
            "vector_store": vector_store,
            "llm": llm,
            "publish": False,
        },
        # Each research loop walks ~8 graph nodes. So this is a safe limit.
        config={"recursion_limit": (settings.max_loops + 2) * 10},
    )

    reports = blackboard.posts("report")
    if reports:
        report = reports[-1]["content"]
        print(f"\nReport written to: {report['path']}")
        if report.get("pdf_path"):
            print(f"PDF written to:    {report['pdf_path']}")
        return 0
    print("\nNo report was produced (see blackboard decisions).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
