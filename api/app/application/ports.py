"""Ports: what the use cases require from the outside world.

Defined here, implemented in ``app.infrastructure``. All parameters are keyword-only.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol

from app.domain.descriptions import Description, DescriptionOrigin, SavedDescription
from app.domain.engine_contract import EngineOperationReport, EngineReport, EngineRequest, Trace
from app.domain.llm import LlmMessage, LlmStep, ToolSpec
from app.domain.mcc import MccFamily, MccInputNet, MccNetFile, MccNetType, ModelEntry
from app.domain.mcc_properties import Examination, MccProperties
from app.domain.mcc_results import MccRun, ResultFileInfo, ResultSetInfo, RunSample, ToolRate
from app.domain.models import (
    EngineInfo,
    FormulaResult,
    Job,
    JobSubmission,
)
from app.domain.net_document import NetDocument
from app.domain.nets import NetReferences, NetSummary, SavedNet, StoredNet
from app.domain.operations import Lineage, OperationOutcome, OperationRun, RunSubmission
from app.domain.predictor import InstanceSize
from app.domain.selection_evaluation import InstanceRun
from app.domain.sessions import (
    Session,
    SessionEvent,
    SessionState,
    StartedSession,
    StoredEvent,
)
from app.domain.splits import Split


class NetRepository(Protocol):
    """Persistent storage of nets."""

    def save_net(self, *, summary: NetSummary, document: NetDocument) -> SavedNet:
        """Store a net if it is new; return what is stored (the existing net if already known)."""
        ...

    def load_net(self, *, net_id: str) -> StoredNet:
        """Return a stored net, or raise NotFoundError."""
        ...


class DescriptionRepository(Protocol):
    """Persistent storage of net descriptions."""

    def save_description(
        self, *, net_id: str, text: str, origin: DescriptionOrigin
    ) -> SavedDescription:
        """Store a description and link it to a net; adding the same text twice is a no-op."""
        ...

    def descriptions_of(self, *, net_id: str) -> tuple[Description, ...]:
        """Return the descriptions linked to a net, oldest first."""
        ...

    def load_description(self, *, description_id: str) -> tuple[Description, ...]:
        """Return a description with each of its links (one per net and origin).

        Raises:
            NotFoundError: if the description is unknown.
        """
        ...


class SessionRepository(Protocol):
    """Persistent storage of sessions and their events. Every operation is atomic."""

    def create_session(self, *, session: Session, started: SessionEvent) -> StartedSession:
        """Store a new session and its first event together."""
        ...

    def session_ids(self) -> tuple[str, ...]:
        """Return the id of every session, oldest first."""
        ...

    def load_session(self, *, session_id: str) -> Session:
        """Return a session, or raise NotFoundError."""
        ...

    def append_event(self, *, session_id: str, event: SessionEvent) -> StoredEvent:
        """Add an event with the next number of the session (strictly increasing, no gap)."""
        ...

    def events_after(self, *, session_id: str, after: int, limit: int) -> tuple[StoredEvent, ...]:
        """Return up to ``limit`` events whose number is above ``after``, in order."""
        ...

    def move_session(
        self, *, session_id: str, allowed_from: tuple[SessionState, ...], to: SessionState
    ) -> bool:
        """Change the state if it is one of ``allowed_from``; False if it was not."""
        ...

    def claim_next_run(self, *, lease_seconds: float) -> Session | None:
        """Atomically claim the oldest queued session for this process; None if none waits."""
        ...

    def renew_run_lease(self, *, session_id: str, lease_seconds: float) -> bool:
        """Extend the lease of a running session; False if it is no longer running."""
        ...

    def finish_run(self, *, session_id: str, to: SessionState) -> bool:
        """Leave the running state, only if the session is still running."""
        ...

    def requeue_lost_runs(self) -> int:
        """Queue again the running sessions whose lease expired: a run resumes from its events."""
        ...

    def expire_waiting_sessions(self, *, older_than_s: float) -> tuple[str, ...]:
        """Cancel the sessions waiting for the user for longer than this; return their ids."""
        ...


class RetentionRepository(Protocol):
    """Deletion of user data (docs/architecture.md, "Retention and deletion")."""

    def delete_session(self, *, session_id: str) -> bool:
        """Delete a session and its events; False if it did not exist."""
        ...

    def purge_sessions(self, *, older_than_s: float) -> int:
        """Delete the sessions not touched for this long, unless a run is queued or running."""
        ...

    def references_of(self, *, net_id: str) -> NetReferences:
        """Return how many jobs and sessions refer to a net, and how many of them are live."""
        ...

    def delete_net(self, *, net_id: str) -> bool:
        """Delete a net with its jobs, traces, sessions, events and description links."""
        ...

    def delete_description_link(self, *, description_id: str, net_id: str) -> bool:
        """Unlink a description from a net; the text goes when no net uses it any more."""
        ...

    def purge_unreferenced(self, *, older_than_s: float) -> int:
        """Delete nets older than this that no job or session uses, and unlinked descriptions."""
        ...


class JobRepository(Protocol):
    """Persistent storage of jobs."""

    def create_or_get_job(self, *, job: Job) -> JobSubmission:
        """Insert ``job`` unless an equivalent live job exists (idempotency); say which was used.

        A queued job waits for a worker and has no lease; a running job has one (see below).
        """
        ...

    def claim_next_job(self, *, lease_seconds: float) -> Job | None:
        """Atomically claim the oldest queued job; None if the queue is empty."""
        ...

    def requeue(self, *, job_id: str) -> bool:
        """Queue an interrupted job again; False if it was not interrupted.

        Raises:
            ConflictError: if an equivalent live job exists.
        """
        ...

    def load_job(self, *, job_id: str) -> Job:
        """Return a job, or raise NotFoundError."""
        ...

    def renew_lease(self, *, job_id: str, lease_seconds: float) -> bool:
        """Extend a running job's lease; return False if it is no longer running."""
        ...

    def cancel(self, *, job_id: str) -> None:
        """Cancel a queued or running job; finished jobs are left untouched."""
        ...

    def finish(
        self, *, job_id: str, results: tuple[FormulaResult, ...], traces: tuple[Trace, ...]
    ) -> None:
        """Store results and counterexamples and mark the job done, only if it is still running."""
        ...

    def load_trace(self, *, job_id: str, formula_id: str) -> Trace:
        """Return the counterexample stored for a formula of a job, or raise NotFoundError."""
        ...

    def purge_finished_jobs(self, *, older_than_s: float) -> int:
        """Delete finished jobs and their traces older than ``older_than_s``; return the count."""
        ...

    def recover_interrupted(self) -> int:
        """Mark running jobs whose lease expired as interrupted; safe to call from any process."""
        ...


class EngineGateway(Protocol):
    """The verification engines."""

    def list_engines(self) -> tuple[EngineInfo, ...]:
        """Return every registered engine with its availability on this machine."""
        ...

    def is_known(self, *, name: str) -> bool:
        """Return True if ``name`` is a registered engine."""
        ...

    def choose(self, *, requested: str) -> str:
        """Return the engine to use for a request ("auto" lets the gateway decide)."""
        ...

    def run(self, *, engine: str, pnml: bytes, request: EngineRequest, job_id: str) -> EngineReport:
        """Run an engine on a net for a job; report what it produced (to be checked)."""
        ...

    def choose_for(self, *, operation: str, requested: str) -> str:
        """Return the engine that will perform an operation ("auto" lets the gateway decide).

        Raises:
            InvalidRequestError: if no suitable engine is available.
        """
        ...

    def version_of(self, *, engine: str) -> str:
        """Return the pinned version of an engine."""
        ...

    def run_operation(
        self, *, engine: str, pnml: bytes, request: EngineRequest, job_id: str
    ) -> EngineOperationReport:
        """Run an analysis or a reduction in an engine; report what it produced (to be checked)."""
        ...

    def stop(self, *, job_id: str) -> None:
        """Kill the engine run of a job, if one is in progress (cancellation)."""
        ...


class LlmGateway(Protocol):
    """The language model, behind a port: the provider SDK is imported in one adapter only."""

    def next_step(
        self, *, system: str, messages: tuple[LlmMessage, ...], tools: tuple[ToolSpec, ...]
    ) -> LlmStep:
        """Return what the model does next, given the conversation so far and the tools."""
        ...


class MccSource(Protocol):
    """Where the contest's catalog and archives come from."""

    def catalog(self) -> tuple[MccFamily, ...]:
        """Return the families of the contest."""
        ...

    def nets(self, *, family: MccFamily) -> Iterator[MccNetFile]:
        """Yield the nets of a family, one at a time."""
        ...

    def result_file(self) -> ResultFileInfo:
        """Make the published results file available and say where it is from."""
        ...

    def result_lines(self) -> Iterator[str]:
        """Yield the lines of the published results file."""
        ...

    def inputs(self, *, only_families: tuple[str, ...]) -> Iterator[MccInputNet]:
        """Yield the instances of the contest inputs with their property files, one at a time."""
        ...

    def instance_sizes(self) -> Iterator[InstanceSize]:
        """Yield the size of every instance of the contest inputs, counted on its PNML."""
        ...


class ModelCatalogRepository(Protocol):
    """Persistent storage of the contest families and of which stored net is which instance."""

    def save_family(self, *, family: MccFamily) -> None:
        """Store a family, replacing the previous record of the same name."""
        ...

    def save_entry(self, *, entry: ModelEntry) -> None:
        """Link a stored net to its family and instance; saving the same link twice is a no-op."""
        ...

    def families(self) -> tuple[MccFamily, ...]:
        """Return the stored families, by name."""
        ...

    def save_sizes(self, *, sizes: Iterable[InstanceSize]) -> int:
        """Store the sizes of contest instances (replacing earlier ones); return how many."""
        ...

    def sizes(self) -> tuple[InstanceSize, ...]:
        """Return the stored instance sizes, by instance."""
        ...

    def entries(self, *, family: str | None, net_type: MccNetType | None) -> tuple[ModelEntry, ...]:
        """Return the entries matching the filters, by family then instance."""
        ...

    def save_properties(self, *, net_id: str, properties: MccProperties) -> None:
        """Store the properties of an examination for a net, replacing the previous ones."""
        ...

    def properties_of(self, *, net_id: str, examination: Examination) -> MccProperties:
        """Return the properties of an examination for a net.

        Raises:
            NotFoundError: if there are none.
        """
        ...


class ResultsRepository(Protocol):
    """Persistent storage of the contest's published runs."""

    def replace_result_set(
        self, *, year: int, file: ResultFileInfo, runs: Iterable[MccRun]
    ) -> ResultSetInfo:
        """Store the runs of a year in place of the ones stored for it, all or nothing."""
        ...

    def samples(
        self, *, tool: str | None, examination: str | None, family: str | None
    ) -> Iterator[RunSample]:
        """Yield the runs matching the filters, in no particular order."""
        ...

    def result_sets(self) -> tuple[ResultSetInfo, ...]:
        """Return the stored result sets, by year."""
        ...

    def instance_runs(self) -> Iterator[InstanceRun]:
        """Yield the run of each engine on each instance and examination (references left out)."""
        ...

    def tool_rates(self, *, examinations: tuple[str, ...]) -> tuple[ToolRate, ...]:
        """Return, per engine and examination, how many runs there are and how many computed."""
        ...


class SplitRepository(Protocol):
    """Persistent storage of frozen splits of the families."""

    def save_split(self, *, split: Split) -> None:
        """Store a split under its name.

        Raises:
            ConflictError: if a split of that name exists; splits are frozen.
        """
        ...

    def load_split(self, *, name: str) -> Split:
        """Return a split, or raise NotFoundError."""
        ...

    def split_names(self) -> tuple[str, ...]:
        """Return the names of the stored splits."""
        ...


class OperationRepository(Protocol):
    """Persistent storage of the runs of operations; a finished run is the cache of its key."""

    def create_or_get_run(self, *, run: OperationRun, key: str) -> RunSubmission:
        """Insert ``run`` unless a queued, running or finished run has the same key."""
        ...

    def claim_next_run(self, *, lease_seconds: float) -> OperationRun | None:
        """Atomically claim the oldest queued run; None if the queue is empty."""
        ...

    def load_run(self, *, run_id: str) -> OperationRun:
        """Return a run, or raise NotFoundError."""
        ...

    def renew_lease(self, *, run_id: str, lease_seconds: float) -> bool:
        """Extend a running run's lease; False if it is no longer running."""
        ...

    def finish_run(self, *, run_id: str, outcome: OperationOutcome) -> None:
        """Store the outcome and end the run (done if ok, failed otherwise), if still running."""
        ...

    def cancel_run(self, *, run_id: str) -> None:
        """Cancel a queued or running run; finished runs are left untouched."""
        ...

    def recover_interrupted_runs(self) -> int:
        """Mark running runs whose lease expired as interrupted."""
        ...

    def purge_finished_runs(self, *, older_than_s: float) -> int:
        """Delete finished runs not touched for that long; return the count."""
        ...

    def save_lineage(self, *, lineage: Lineage) -> None:
        """Record that a net was derived from another by a rule; saving it again is a no-op."""
        ...

    def lineage_of(self, *, net_id: str) -> tuple[Lineage, ...]:
        """Return the ways a net was derived from other nets (none for an uploaded net)."""
        ...
