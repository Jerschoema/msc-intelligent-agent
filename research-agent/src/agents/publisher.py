"""The agent creates the final report — PDF for humans and markdown for other agents.

The blackboard has the memory of all processed sources. Therefore, the publisher will get all of 
the sources, summary, claims, ranking, and decisions from the blackboard and analyze them to make a report.
The core purpose of the LLM is to write the analysis of all sources.

The report will contain the following sections:


1. introduction
2. summary 
3. conclusion 
4. further research 

Initially, we used a structured output but the model was not able to produce analysis.
The major limitation is the context window of the model. Therefore, we decided to use a
plain chat for each section. We also noticed that model performance is varying. The model
has to analyse a large amount of text and is therefore likely to forget sections or include
relevant sources in the analysis, therefore we use maximum of 8 sources for a summary. We produce
multiple summaries and then integrate them into one summary.

Then there are the deterministic sections. We let deterministic code summarize all claims, 
sources, audit trail and the appendix. This is because these are all facts. 
Therefore, using a model to generate these sections is not reliable. 



"""

from pathlib import Path

import re

from langchain_core.messages import HumanMessage, SystemMessage
from markdown_pdf import MarkdownPdf, Section

from src.config.settings import settings
from src.models import Decision, Report


def _create_report_name(text: str, max_length: int = 50) -> str:
    """Turn a topic into a readable filename part: 'Federated learning!' becomes
    'federated-learning'. Removing some characters to avoid having 
    compability issues with different filesystems."""
    name = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return name[:max_length].rstrip("-")


# One section per call: a small model writes a focused paragraph far more
# reliably than a five-field document in one go — asking for everything at
# once is what produced 'This section provides a brief overview...' filler.
_SECTION_SYSTEM = (
    "You write ONE section of an academic research brief about the given "
    "topic. Here are the rules:"
    "1. Use only the provided source summaries."
    "2. Do not invent any information or make up claims. Only use information that is in the provided sources."
    "3. Never describe what the section is for ('This section provides a summary of the content'). It needs to based on the sources."
    "4. Cite each source with the citation key given for all sources used in the section"
    "5. Use academic style citations: "
    "(Shi & Li, 2022)."
    "6. There is no length limit. Address every source you were given, not "
    "just two or three of them. A section that only touches a handful "
    "when eight were provided is incomplete.\n\n"
    'Example of a good use of citations in a summary: "The graph theories are converging on a common set of'
    "graphs but differ on temporal handling: gated temporal convolutions "
    "(Yu et al., 2018; yan et al., 2025) versus a learned adaptive adjacency matrix "
    "(Wu & Pan, 2019), suggesting a shift toward learned structure."
)

_SECTION_BRIEFS = {
    "introduction": "Write the introduction: one paragraph framing the topic, "
                    "the research question, and what the brief covers.",
    "summary": "Write the summary: the picture ACROSS the sources. Address every "
               "source you were given, not just two or three — major theories, "
               "agreements, tensions, and the state of the evidence, with "
               "in-text citations for each one.",
    "conclusion": "Write the conclusion: what the gathered evidence supports "
                  "for the research question, stated carefully, with in-text "
                  "citations.",
}

# The model reads sources in groups of this size for the summary — see
# _write_summary for why.
_BATCH_SIZE = 8


class _ReportStructure:
    """the sections of the report that are written by the LLM."""

    def __init__(self):
        self.introduction = ""
        self.summary = ""
        self.conclusion = ""
        self.further_research: list[str] = []

    def empty(self) -> bool:
        return not (self.introduction or self.summary or self.conclusion or self.further_research)


def _is_boilerplate(section: str, text: str) -> bool:
    """True when:
     1. the model described the section instead of writing it
        Example: This section summarizes the content of the sources...
     2. A summary/conclusion with no citations also fails.
    """
    lower = text.lower()
    if not text.strip() or "this section" in lower or f"write the {section}" in lower:
        return True
    
    # The model sometimes echoes the source material instead of writing a summary.
    if "cite as" in lower or lower.startswith("topic:"):
        return True
    
    # ( is a citation
    return section in ("summary", "conclusion") and "(" not in text


def _log_entry(kind: str, content: dict) -> str:
    """One post as a readable log line, so the appendix reads as a story."""
    if kind == "tool_call":
        args = ", ".join(f"{k}={v!r}" for k, v in content.get("args", {}).items())
        return f"called `{content.get('tool')}({args})`"
    if kind == "note":
        return content.get("text", "")
    if kind == "decision":
        return f"**{content.get('kind')}** — {content.get('reason')}"
    if kind == "criteria":
        return "contract: " + ", ".join(f"{k}={v}" for k, v in content.items())
    return str(content)


class PublisherAgent:
    name = "PublisherAgent"

    def __init__(self, blackboard, llm) -> None:
        self.bb = blackboard
        self.llm = llm

    def run(self, topic: str, research_question: str = "") -> str:
        sources = self.bb.sources()
        posts = self.bb.posts()
        decisions = [p["content"] for p in posts if p["kind"] == "decision"]

        narrative = self._build_report_sections(topic, research_question, sources)
        markdown = self._render(topic, research_question, sources, decisions, posts, narrative)

        md_path = Path(settings.data_dir) / "reports" / f"{self.bb.run_id}-{_create_report_name(topic)}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown, encoding="utf-8")
        pdf_path = self._write_pdf(markdown, md_path.with_suffix(".pdf"))

        # Pointer only — the content lives on disk, not in the database.
        self.bb.post(self.name, "report", Report(self.bb.run_id, str(md_path), pdf_path).to_dict())
        return str(md_path)

    def _write_pdf(self, markdown: str, path: Path) -> str:
        """Render the markdown to PDF."""
        try:
            pdf = MarkdownPdf(toc_level=2)
            pdf.add_section(Section(markdown))
            pdf.save(str(path))
            return str(path)
        except Exception as exc:  
            self.bb.post(
                self.name, "decision",
                Decision(self.name, "error", f"PDF rendering failed: {exc}").to_dict(),
            )
            return ""

    def _build_report_sections(self, topic, research_question, sources) -> _ReportStructure | None:
        """Have the LLM write the report sections.

        We noticed that if we introduce more than the summaries of 8 sources, the model
        starts to produce poor output. Therefore, we write summaries for 8 sources. Then
        we add all summaries into the context and the model to integrate all summaries which
        produces the final summary. The introduction, conclusion and further research
        sections then read that integrated summary.
        """
        summarised = [s for s in sources if s.summarised and s.relevance != "unrelated"]
        if not summarised:
            return None  # nothing to report if no sources were summarised

        order = {"high": 0, "medium": 1, "": 2, "unknown": 2, "low": 3}
        ranked = sorted(summarised, key=lambda s: (order.get(s.ranking, 2), -s.citations))

        report = _ReportStructure()
        report.summary = self._write_summary(topic, research_question, ranked)

        if report.summary:
            context = (
                f"Topic: {topic}\nResearch question: {research_question or topic}\n\n"
                f"Summary of the sources:\n{report.summary}"
            )
        else:
            # The summary step came back empty — fall back to a raw slice
            # of the strongest sources so these sections still have something.
            context = self._context(topic, research_question, ranked[:8])

        report.introduction = self._write_section("introduction", context)
        report.conclusion = self._write_section("conclusion", context)
        report.further_research = self._write_questions(context)
        return None if report.empty() else report

    def _context(self, topic, research_question, sources) -> str:
        """Format a batch of sources into the material block an LLM call reads."""
        material = []
        for source in sources:
            claims = "; ".join(c.text for c in source.claims[:2])
            material.append(
                f"{source.title} — cite as ({source.cite()})\n"
                f"Summary: {source.summary[:500]}\nKey claims: {claims}"
            )
        return (
            f"Topic: {topic}\nResearch question: {research_question or topic}\n\n"
            + "\n\n".join(material)
        )

    def _write_summary(self, topic, research_question, ranked_sources) -> str:
        """The summary has to speak across every source, not just the top 8 —
        so sources are batched into partial summaries, then merged into
        one. Each call stays small enough for the model to read
        closely instead of losing track past a handful of sources."""
        batches = [
            ranked_sources[i:i + _BATCH_SIZE]
            for i in range(0, len(ranked_sources), _BATCH_SIZE)
        ]
        partials = []
        for batch in batches:
            partial = self._write_section("summary", self._context(topic, research_question, batch))
            if partial:
                partials.append(partial)

        if len(partials) <= 1:
            return partials[0] if partials else ""
        return self._integrate_summaries(topic, research_question, partials)

    def _integrate_summaries(self, topic, research_question, partials: list[str]) -> str:
        """Merge partial summaries (one per batch of sources) into one. Gated
        the same way as any section — the model could just paste the
        partials back to back instead of actually merging them."""
        numbered = "\n\n".join(f"Summary {i + 1}:\n{s}" for i, s in enumerate(partials))
        task = ("Below are separate summaries, each covering a different subset "
                "of sources on the same topic. Write ONE integrated summary that "
                "combines them, keeps every citation, merges repeated points, "
                "and notes any tensions between them. Address the distinct "
                "content of every summary in turn and do not collapse them into "
                "a single short statement just because they share a "
                "conclusion; the integrated summary should read as thoroughly "
                "as the summaries it draws from, not a shorter recap of them.")
        for attempt in (1, 2):
            reply = self.llm.invoke([
                SystemMessage(f"{_SECTION_SYSTEM}\n\nYour task: {task}"),
                HumanMessage(
                    f"Topic: {topic}\nResearch question: {research_question or topic}\n\n"
                    f"{numbered}\n\nNow write the integrated summary."
                ),
            ], reasoning=True)
            text = reply.content.strip() if isinstance(reply.content, str) else ""
            if not _is_boilerplate("summary", text):
                return text
            self.bb.post(
                self.name, "decision",
                Decision(self.name, "error",
                         f"summary integration attempt {attempt} rejected (boilerplate)").to_dict(),
            )
        return "\n\n".join(partials)  # keep the batch work rather than losing it

    def _write_section(self, section: str, context: str) -> str:
        """One focused plain-chat call, gated, one retry. \"\" = leave the
        section out — the report never carries filler."""
        for attempt in (1, 2):
            # Reasoning is set to true because the model has to read a lot of text and then produce a summary.
            reply = self.llm.invoke([
                SystemMessage(f"{_SECTION_SYSTEM}\n\nYour task: {_SECTION_BRIEFS[section]}"),
                HumanMessage(f"{context}\n\nNow, in your own words: {_SECTION_BRIEFS[section]}"),
            ], reasoning=True)
            text = reply.content.strip() if isinstance(reply.content, str) else ""
            if not _is_boilerplate(section, text):
                return text
            self.bb.post(
                self.name, "decision",
                Decision(self.name, "error",
                         f"{section} attempt {attempt} rejected (boilerplate)").to_dict(),
            )
        return ""

    def _write_questions(self, context: str) -> list[str]:
        task = ("List up to four open questions the sources leave unanswered "
                "(further research). One question per line, nothing else.")
        reply = self.llm.invoke([
            SystemMessage(f"{_SECTION_SYSTEM}\n\nYour task: {task}"),
            HumanMessage(f"{context}\n\nNow, in your own words: {task}"),
        ], reasoning=True)
        text = reply.content if isinstance(reply.content, str) else ""
        questions = [line.strip("-* ").strip() for line in text.splitlines() if line.strip()]
        # Keep only lines that read as questions — drops preambles and echoes.
        return [q for q in questions if q.endswith("?")][:4]

    def _render(self, topic, research_question, sources, decisions, posts, narrative) -> str:
        summarised = [s for s in sources if s.summarised and s.relevance != "unrelated"]
        lines = [
            f"# Research Brief: {topic}",
            "",
            f"_Run `{self.bb.run_id}` · {len(summarised)} source(s) summarised._",
            "",
        ]
        if research_question:
            lines += [f"**Research question:** {research_question}", ""]
        # Each narrative section renders only if it passed its quality gate —
        # a weak conclusion doesn't cost the reader a good introduction.
        if narrative is not None and narrative.introduction:
            lines += ["## Introduction", "", narrative.introduction, ""]
        if narrative is not None and narrative.summary:
            lines += ["## Summary", "", narrative.summary, ""]

        # -- findings: one section per summarised source, all from the record --
        lines += ["## Findings", ""]
        if not summarised:
            lines += ["_No sources could be summarised in this run. See Limitations._", ""]
        for i, source in enumerate(summarised, start=1):
            authors = ", ".join(source.authors) or "Unknown authors"
            year = source.publication_date[:4] or "n.d."
            lines += [f"### {i}. {source.title}", f"*{authors} ({year})*", ""]
            if source.ranking:
                lines += [f"_Source reputation: {source.ranking} — {source.ranking_note}_", ""]
            if not source.parsed:
                # Honesty marker: a summary without content was abstract-based.
                lines += ["_Based on the abstract only — the full text was not accessible._", ""]
            lines += [f"{source.summary} ({source.cite()})", ""]
            if source.claims:
                lines.append("**Key claims:**")
                for claim in source.claims:
                    page = f", p. {claim.page}" if claim.page else ""
                    lines.append(f"- {claim.text} ({source.cite()}{page})")
                    if claim.evidence:
                        lines.append(f"  > {claim.evidence}")
                lines.append("")

        # consolidated claims: every claim in one place, each carrying its
        # academic in-text citation so it stands alone.
        lines += ["## Claims and hypotheses", ""]
        any_claim = False
        for source in summarised:
            for claim in source.claims:
                any_claim = True
                page = f", p. {claim.page}" if claim.page else ""
                lines.append(f"- {claim.text} ({source.cite()}{page})")
        if not any_claim:
            lines.append("- No structured claims could be extracted this run.")
        lines.append("")

        if narrative is not None and narrative.conclusion:
            lines += ["## Conclusion", "", narrative.conclusion, ""]
        if narrative is not None and narrative.further_research:
            lines += ["## Further research", ""]
            lines += [f"- {q}" for q in narrative.further_research]
            lines.append("")

        # references: every source, with access labels --------------
        lines += ["## References", ""]
        if sources:
            for source in sources:
                authors = ", ".join(source.authors) or "Unknown"
                year = source.publication_date[:4] or "n.d."
                rep = f" [reputation: {source.ranking}]" if source.ranking else ""
                cited = f" [citations: {source.citations}]" if source.citations else ""
                if source.captcha:
                    access = " [access: blocked by CAPTCHA — content not collected]"
                elif source.restricted:
                    access = " [access: restricted — abstract only]"
                else:
                    access = " [access: open]"
                if source.relevance == "unrelated":
                    access += " [excluded: judged off-topic]"
                if source.source_db == "arxiv":
                    ident = f", arXiv:{source.id}"
                elif source.doi:
                    ident = f", doi:{source.doi}"
                else:
                    ident = ""
                lines.append(
                    f"- {authors} ({year}) '{source.title}'{ident}. "
                    f"Available at: {source.url}{rep}{cited}{access}"
                )
        else:
            lines.append("- No sources retrieved.")
        lines.append("")

        # -- limitationsfrom the decision trail ---------
        lines += ["## Limitations", ""]
        notable = [d for d in decisions if d.get("kind") in {"skip", "error", "retry", "restricted", "captcha"}]
        converges = [d for d in decisions if d.get("kind") == "converge"]
        # Publishing under the user's minimums is the most important caveat.
        under_minimums = bool(converges) and not converges[-1].get("payload", {}).get("met", True)
        if under_minimums:
            lines.append(
                f"- **Published below the requested minimums** — {converges[-1].get('reason')}"
            )
        if notable:
            for d in notable:
                lines.append(f"- _{d.get('made_by')}_: {d.get('reason')}")
        elif not under_minimums:
            lines.append("- No issues recorded during this run.")
        lines += [
            "",
            "_Scope note: this is a deliberately small, local pipeline (free scholarly "
            "APIs + local retrieval + a local LLM). See the README for the design "
            "trade-offs._",
            "",
        ]

        
        lines += ["## Appendix: run log", ""]
        if posts:
            lines.append("| # | agent | entry |")
            lines.append("|---|---|---|")
            for i, post in enumerate(posts, start=1):
                entry = _log_entry(post["kind"], post["content"])
                entry = entry.replace("|", "\\|").replace("\n", " ")
                lines.append(f"| {i} | {post['agent']} | {entry} |")
        else:
            lines.append("_Nothing was posted during this run._")
        lines.append("")
        return "\n".join(lines)
