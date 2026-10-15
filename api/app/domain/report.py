"""The report of a session: what was asked, what was checked, what the engines said.

Built from the events alone. Verdicts come only from ``verdict`` events (engine results); what the
assistant wrote is quoted and labelled as written by the language model; text from the net or from
people is data and is shown in code spans and fenced blocks, never as markup.
"""

from __future__ import annotations

from .descriptions import Description
from .formula_text import render_text
from .models import DomainModel
from .nets import NetSummary
from .sessions import (
    Answer,
    AssistantMessage,
    BudgetExhausted,
    DescriptionAccepted,
    Question,
    Session,
    SessionError,
    SessionStarted,
    StoredEvent,
    UserMessage,
    Verdict,
)
from .sessions import PropertyProposed as ProposedEvent


class ReportedVerdict(DomainModel):
    """A property and the verdict an engine gave it."""

    formula_id: str
    formula: str | None = None
    gloss: str = ""
    verdict: str
    engine: str
    engine_version: str
    job_id: str
    result_index: int
    has_counterexample: bool


class ReportedExchange(DomainModel):
    """A line of the conversation: who said it, and what."""

    who: str
    text: str


class SessionReport(DomainModel):
    """Everything worth keeping of a session, structured."""

    session: Session
    net: NetSummary
    goal: str
    description: Description | None = None
    verdicts: tuple[ReportedVerdict, ...] = ()
    conversation: tuple[ReportedExchange, ...] = ()
    problems: tuple[str, ...] = ()
    event_count: int


def build_report(
    *,
    session: Session,
    net: NetSummary,
    description: Description | None,
    events: tuple[StoredEvent, ...],
) -> SessionReport:
    """Build the report of a session from its events."""
    proposed: dict[str, ProposedEvent] = {}
    verdicts: list[ReportedVerdict] = []
    conversation: list[ReportedExchange] = []
    problems: list[str] = []
    goal = ""
    for stored in events:
        event = stored.event
        if isinstance(event, ProposedEvent):
            proposed[event.formula.id] = event
        elif isinstance(event, Verdict):
            property_event = proposed.get(event.formula_id)
            verdicts.append(
                ReportedVerdict(
                    formula_id=event.formula_id,
                    formula=None
                    if property_event is None
                    else render_text(expression=property_event.formula.ast),
                    gloss="" if property_event is None else property_event.formula.gloss,
                    verdict=event.verdict.value,
                    engine=event.engine,
                    engine_version=event.engine_version,
                    job_id=event.job_id,
                    result_index=event.result_index,
                    has_counterexample=event.has_trace,
                )
            )
        elif isinstance(event, UserMessage | Answer):
            conversation.append(ReportedExchange(who="user", text=event.text))
        elif isinstance(event, AssistantMessage):
            conversation.append(
                ReportedExchange(who="assistant (written by the language model)", text=event.text)
            )
        elif isinstance(event, Question):
            conversation.append(ReportedExchange(who="assistant asks", text=event.text))
        elif isinstance(event, BudgetExhausted):
            problems.append(f"The assistant stopped: budget reached ({event.budget}).")
        elif isinstance(event, SessionError):
            problems.append(f"Error {event.code}: {event.message}")
        elif isinstance(event, DescriptionAccepted):
            problems.append("A description proposed by the assistant was accepted.")
        elif isinstance(event, SessionStarted):
            goal = event.goal
    return SessionReport(
        session=session,
        net=net,
        goal=goal,
        description=description,
        verdicts=tuple(verdicts),
        conversation=tuple(conversation),
        problems=tuple(problems),
        event_count=len(events),
    )


def longest_backtick_run(*, text: str) -> int:
    """Return the length of the longest run of backticks in ``text``."""
    longest = run = 0
    for character in text:
        run = run + 1 if character == "`" else 0
        longest = max(longest, run)
    return longest


def code(*, text: str) -> str:
    """Write ``text`` as an inline code span that cannot be closed from inside."""
    flat = text.replace("\n", " ")
    marks = "`" * (longest_backtick_run(text=flat) + 1)
    pad = " " if flat.startswith("`") or flat.endswith("`") else ""
    return f"{marks}{pad}{flat}{pad}{marks}"


def block(*, text: str) -> str:
    """Write ``text`` as a fenced block."""
    marks = "`" * max(3, longest_backtick_run(text=text) + 1)
    return f"{marks}text\n{text}\n{marks}"


def render_markdown(*, report: SessionReport) -> str:
    """Write the report as Markdown, ready to read, share or keep."""
    summary = report.net
    lines = [
        f"# Session report {code(text=report.session.session_id)}",
        "",
        f"- Net: {code(text=summary.source_id)} ({summary.kind}): {summary.places} places, "
        f"{summary.transitions} transitions, {summary.arcs} arcs; id {code(text=summary.net_id)}",
        f"- State: {report.session.state.value}; {report.event_count} events",
        "",
        "## Goal",
        "",
        block(text=report.goal),
    ]
    if report.description is not None:
        lines += [
            "",
            f"## Description of the system (origin: {report.description.origin})",
            "",
            "_Text written by a person, quoted as data._",
            "",
            block(text=report.description.text),
        ]
    lines += ["", "## Verdicts", ""]
    if not report.verdicts:
        lines.append("No property was checked by an engine.")
    else:
        lines += [
            "Verdicts are the ones engines reported; nothing else in this report is a verdict.",
            "",
            "| Property | Verdict | Engine | Counterexample |",
            "|---|---|---|---|",
        ]
        for item in report.verdicts:
            property_text = code(text=item.formula) if item.formula else code(text=item.formula_id)
            counterexample = (
                f"yes (job {code(text=item.job_id)}, result {item.result_index})"
                if item.has_counterexample
                else "no"
            )
            lines.append(
                f"| {code(text=item.formula_id)}: {property_text} | **{item.verdict}** | "
                f"{code(text=item.engine)} {code(text=item.engine_version)} | {counterexample} |"
            )
        glossed = [item for item in report.verdicts if item.gloss]
        if glossed:
            lines += ["", "In plain words (as written by the proposer):", ""]
            lines += [
                f"- {code(text=item.formula_id)}: {item.gloss.replace(chr(10), ' ')}"
                for item in glossed
            ]
    lines += ["", "## Conversation", ""]
    for exchange in report.conversation:
        lines += [f"**{exchange.who}**", "", block(text=exchange.text), ""]
    if report.problems:
        lines += ["## Notes", ""] + [f"- {problem}" for problem in report.problems]
    return "\n".join(lines).rstrip() + "\n"
