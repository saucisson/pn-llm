"""Run the model conditions: a session in non-interactive mode, then the common measurement.

The model works as it would for a person, except that every question it asks is answered with the
same fixed "no answer is available" and counted. The properties it proposed are taken from the
events of the session, renamed back when the net was obfuscated, and measured like any other
condition's (``ExperimentRunner.measure``). The session stays stored, so the run can be replayed.
"""

from __future__ import annotations

from app.domain.conditions import GOAL, NO_ANSWER, gives_description
from app.domain.errors import InvalidRequestError
from app.domain.experiment import Condition, RunRecord, RunSpec
from app.domain.formula import Formula
from app.domain.formula_text import render_text
from app.domain.models import DomainModel
from app.domain.nets import NetFormat
from app.domain.obfuscation import Renaming, obfuscate_names, restore_formula
from app.domain.sessions import PropertyProposed, SessionState

from .agent import AgentService
from .experiment import ExperimentRunner
from .nets import NetService
from .ports import DescriptionRepository

MAX_QUESTIONS = 20


class ConditionAgent(DomainModel, arbitrary_types_allowed=True):
    """The agent of one condition (its tools differ), and the hash of what it tells the model."""

    condition: Condition
    agent: AgentService
    prompt_hash: str


class ModelConditionRunner:
    """Run L1, L2, L3 and N."""

    def __init__(
        self,
        *,
        runner: ExperimentRunner,
        agents: tuple[ConditionAgent, ...],
        nets: NetService,
        descriptions: DescriptionRepository,
        model_id: str,
    ) -> None:
        """Create the runner over the judge, one agent per condition and the model's identity."""
        self._runner = runner
        self._agents = agents
        self._nets = nets
        self._descriptions = descriptions
        self._model_id = model_id

    def run(self, *, spec: RunSpec, net_id: str) -> RunRecord:
        """Let the model work on the net, then measure what it proposed on the original net.

        Raises:
            InvalidRequestError: if the condition has no agent, or L3 has no description to show.
        """
        chosen = next((a for a in self._agents if a.condition == spec.condition), None)
        if chosen is None:
            raise InvalidRequestError(f"No agent is configured for condition {spec.condition}")
        shown_net = net_id
        renamings: tuple[Renaming, ...] = ()
        if spec.condition == "N":
            obfuscated = obfuscate_names(document=self._nets.get(net_id=net_id).document)
            renamings = obfuscated.renamings
            shown_net = self._nets.register(
                payload=obfuscated.document.model_dump_json().encode(), format=NetFormat.JSON
            ).stored.summary.net_id
        description_id = None
        if gives_description(condition=spec.condition):
            described = self._descriptions.descriptions_of(net_id=net_id)
            if not described:
                raise InvalidRequestError("No description is stored for this net (condition L3)")
            description_id = described[0].description_id

        agent = chosen.agent
        session_id = agent.start(
            net_id=shown_net, description_id=description_id, goal=GOAL
        ).session.session_id
        questions = 0
        while True:
            while agent.run_next():
                pass
            if agent.get(session_id=session_id).state is not SessionState.WAITING_FOR_USER:
                break
            question = agent.open_question(session_id=session_id)
            if question is None or questions >= MAX_QUESTIONS:
                agent.cancel(session_id=session_id)
                break
            agent.answer(session_id=session_id, question_id=question.question_id, text=NO_ANSWER)
            questions += 1

        formulas: list[Formula] = []
        seen: set[tuple[str, str]] = set()
        for stored in agent.all_events(session_id=session_id):
            if not isinstance(stored.event, PropertyProposed):
                continue
            formula = (
                restore_formula(formula=stored.event.formula, renamings=renamings)
                if renamings
                else stored.event.formula
            )
            key = (formula.logic, render_text(expression=formula.ast))
            if key in seen:
                continue
            seen.add(key)
            formulas.append(
                formula.model_copy(update={"id": f"{spec.condition}-{len(formulas) + 1}"})
            )
        record = self._runner.measure(
            spec=spec.model_copy(
                update={"model_id": self._model_id, "prompt_hash": chosen.prompt_hash}
            ),
            net_id=net_id,
            formulas=tuple(formulas),
        )
        return record.model_copy(
            update={"session_id": session_id, "proposed": len(formulas), "questions": questions}
        )
