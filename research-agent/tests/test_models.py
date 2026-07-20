from src.models import Claim, Decision, Report, Source
from tests.conftest import make_source


def test_source_round_trips_through_json_with_claims():
    source = make_source(
        restricted=True, captcha=True, content="[page 1]\ntext", pages=1,
        summary="a summary", claims=[Claim(text="c", evidence="e", page=3)],
        ranking="high", ranking_note="peer reviewed", indexed=True,
        discovery={"keywords": ["k"], "topics": ["t"]},
        doi="10.1/x", citations=12, document_type="article", language="en",
    )
    restored = Source.from_dict(source.to_dict())
    assert restored == source
    assert restored.claims[0].page == 3


def test_source_from_dict_tolerates_old_and_foreign_keys():
    old = {"id": "p1", "title": "T", "authors": [], "abstract": "a",
           "pdf_url": "http://x", "some_future_field": True}
    source = Source.from_dict(old)
    assert source.id == "p1"
    assert source.restricted is False


def test_empty_fields_are_the_todo_markers():
    source = make_source()
    assert not source.parsed and not source.summarised
    assert not source.ranked and not source.mined
    source.content = "[page 1]\ntext"
    source.summary = "done"
    source.ranking = "high"
    source.discovery = {"keywords": ["k"]}
    assert source.parsed and source.summarised and source.ranked and source.mined


def test_describe_warns_the_model_about_restricted_sources():
    line = make_source(restricted=True, citations=524).describe()
    assert "id=2401.1v1" in line
    assert "[restricted — abstract only]" in line
    assert "cited 524×" in line


def test_citation_meta_is_flat_scalars_for_the_vector_store():
    meta = make_source(
        authors=["A. One", "B. Two"], journal="Nature", doi="10.1/x",
        citations=7, ranking="high",
    ).citation_meta()
    assert meta["authors"] == "A. One; B. Two"
    assert meta["year"] == 2024
    assert meta["journal"] == "Nature"
    assert meta["reputation"] == "high"
    assert all(isinstance(v, (str, int)) for v in meta.values())
    assert Source(id="x").citation_meta()["year"] == 0


def test_cite_builds_academic_in_text_citations():
    assert make_source(authors=["Zhuangwei Shi"]).cite() == "Shi, 2024"
    assert make_source(authors=["Z. Shi", "Bo Li"]).cite() == "Shi & Li, 2024"
    assert make_source(authors=["A. One", "B. Two", "C. Three"]).cite() == "One et al., 2024"
    assert make_source(authors=[], journal="Nature", publication_date="").cite() == "Nature, n.d."


def test_decision_and_report_round_trip():
    d = Decision(made_by="SupervisorAgent", kind="retry", reason="not enough", payload={"loop": 1})
    assert Decision.from_dict(d.to_dict()) == d
    r = Report(run_id="r1", path="data/reports/r1.md", pdf_path="data/reports/r1.pdf")
    assert Report.from_dict(r.to_dict()) == r
