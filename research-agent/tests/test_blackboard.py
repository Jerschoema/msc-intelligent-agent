from src.memory.blackboard import Blackboard
from tests.conftest import make_source


def test_save_then_get_source(bb):
    bb.save_source(make_source())
    source = bb.get_source("2401.1v1")
    assert source.title == "A Paper"
    assert bb.get_source("missing") is None


def test_saving_again_updates_in_place(bb):
    source = make_source()
    bb.save_source(source)
    source.summary = "now summarised"
    bb.save_source(source)
    assert len(bb.sources()) == 1
    assert bb.get_source(source.id).summary == "now summarised"


def test_sources_keep_first_saved_order(bb):
    bb.save_source(make_source(sid="a"))
    bb.save_source(make_source(sid="b"))
    a = bb.get_source("a")
    a.ranking = "high"
    bb.save_source(a)
    assert [s.id for s in bb.sources()] == ["a", "b"]


def test_posts_are_append_only_and_ordered(bb):
    bb.post("AgentA", "decision", {"kind": "retry", "reason": "r1"})
    bb.post("AgentB", "note", {"text": "n"})
    posts = bb.posts()
    assert [p["agent"] for p in posts] == ["AgentA", "AgentB"]
    assert bb.posts("note")[0]["content"]["text"] == "n"


def test_runs_are_isolated(tmp_path):
    db = str(tmp_path / "bb.db")
    run1, run2 = Blackboard("run-1", db), Blackboard("run-2", db)
    run1.save_source(make_source())
    run1.post("A", "note", {"text": "x"})
    assert run2.sources() == []
    assert run2.posts() == []
