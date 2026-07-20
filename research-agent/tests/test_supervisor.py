from tests.conftest import FakeStructuredLLM, make_source

from src.agents.supervisor import DEFAULT_MIN_SOURCES, DEFAULT_MIN_WORDS, SupervisorAgent


def _criteria(bb, words=1, sources=0):
    bb.post("SupervisorAgent", "criteria", {"min_words": words, "min_sources": sources})


def _enriched(bb, sid="p1", summary="thirty words " * 15, ranking="high"):
    bb.save_source(make_source(sid=sid, summary=summary, ranking=ranking))


def test_keeps_researching_while_minimums_met_but_still_learning(bb):
    _criteria(bb, words=5, sources=1)
    _enriched(bb)
    assert SupervisorAgent(bb).converge(loop_count=0, new_sources=True, new_topics=True) is False


def test_publishes_when_a_retry_learned_nothing_new(bb):
    _criteria(bb)
    _enriched(bb)
    assert SupervisorAgent(bb).converge(loop_count=1, new_sources=False, new_topics=False) is True


def test_new_topics_alone_keep_the_loop_alive(bb, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("src.agents.supervisor.settings", SimpleNamespace(max_loops=2))
    _criteria(bb)
    assert SupervisorAgent(bb).converge(loop_count=1, new_sources=False, new_topics=True) is False


def test_first_pass_never_counts_as_exhausted(bb):
    _criteria(bb)
    assert SupervisorAgent(bb).converge(loop_count=0, new_sources=False, new_topics=False) is False


def test_loop_limit_publishes_even_while_still_learning(bb):
    _criteria(bb, words=5000, sources=9)
    assert SupervisorAgent(bb).converge(loop_count=5, new_sources=True, new_topics=True) is True


def test_decision_records_the_floor_check(bb):
    _criteria(bb, words=50, sources=1)
    bb.save_source(make_source(summary="short", ranking="low"))
    SupervisorAgent(bb).converge(loop_count=0)
    decision = bb.posts("decision")[-1]["content"]
    assert decision["kind"] == "retry"
    assert "1/50 words" in decision["reason"]
    assert "0/1 reputable sources" in decision["reason"]
    assert decision["payload"]["met"] is False


def test_low_and_unknown_rankings_do_not_count_as_reputable(bb):
    _criteria(bb, words=1, sources=1)
    bb.save_source(make_source(sid="p1", summary="words here", ranking="low"))
    bb.save_source(make_source(sid="p2", summary="words here", ranking="unknown"))
    SupervisorAgent(bb).converge(loop_count=0)
    assert "0/1 reputable sources" in bb.posts("decision")[-1]["content"]["reason"]


def test_off_topic_sources_do_not_count_toward_words_or_reputable(bb):
    _criteria(bb, words=1, sources=1)
    bb.save_source(make_source(sid="p1", summary="plenty of words here", ranking="high", relevance="unrelated"))
    SupervisorAgent(bb).converge(loop_count=0)
    reason = bb.posts("decision")[-1]["content"]["reason"]
    assert "0/1 words" in reason
    assert "0/1 reputable sources" in reason


def test_intake_splits_the_request_into_the_contract(bb):
    llm = FakeStructuredLLM(parsed={
        "topic": "LLM safety benchmarks",
        "research_question": "Can they be gamed?",
        "min_words": 800, "min_sources": 4,
    })
    topic, question, criteria = SupervisorAgent(bb, llm).intake(
        "LLM safety benchmarks — can they be gamed? 4 solid sources, 800 words"
    )
    assert topic == "LLM safety benchmarks"
    assert question == "Can they be gamed?"
    assert criteria["min_words"] == 800 and criteria["min_sources"] == 4
    assert bb.posts("criteria")[-1]["content"] == criteria


def test_intake_falls_back_to_defaults_when_nothing_stated(bb):
    llm = FakeStructuredLLM(parsed={"topic": "quantum error correction",
                                    "research_question": "", "min_words": 0, "min_sources": 0})
    topic, question, criteria = SupervisorAgent(bb, llm).intake("quantum error correction")
    assert question == "quantum error correction"
    assert criteria["min_words"] == DEFAULT_MIN_WORDS
    assert criteria["min_sources"] == DEFAULT_MIN_SOURCES


def test_intake_asks_the_user_when_interactive(bb, monkeypatch):
    llm = FakeStructuredLLM(parsed={"topic": "t", "research_question": "", "min_words": 0, "min_sources": 0})
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["why does t matter?", "500", "3"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    _, question, criteria = SupervisorAgent(bb, llm).intake("t")
    assert question == "why does t matter?"
    assert criteria == {"topic": "t", "research_question": "why does t matter?",
                        "min_words": 500, "min_sources": 3}


def test_intake_survives_llm_failure(bb):
    topic, question, criteria = SupervisorAgent(bb, FakeStructuredLLM(raw_text="??")).intake("plain topic")
    assert topic == "plain topic"
    assert question == "plain topic"
    assert criteria["min_words"] == DEFAULT_MIN_WORDS
