"""Engine registry: the tools that can verify a net, and how to run them.

Implements the ``EngineGateway`` port. Contract with each engine (docs/engine-contract.md): a
Docker image whose entrypoint reads /work/input/{net.pnml,request.json} and writes
/work/output/result.json.

The default registry lists the tools of the MCC 2026 (docs/mcc-tools.md). Their images are not
built yet: each one has its own integration issue in the backlog.
"""

from __future__ import annotations

import contextlib
import tempfile
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Literal

from app.domain.capabilities import classes_checked_by
from app.domain.catalog import OPERATIONS
from app.domain.contract import Envelope
from app.domain.engine_contract import (
    EngineCheckData,
    EngineFormulaResult,
    EngineOperationData,
    EngineOperationReport,
    EngineReport,
    EngineRequest,
    EngineTrace,
    ReportedResult,
)
from app.domain.errors import InvalidRequestError
from app.domain.models import DomainModel, EngineInfo, Verdict

from .docker_runner import DockerRunner, DockerTimeoutError, DockerUnavailableError

ALL_LOGICS = ("ltl", "ctl", "state")
BOOLEAN_EXAMINATIONS = (
    "ReachabilityCardinality",
    "ReachabilityFireability",
    "CTLCardinality",
    "CTLFireability",
    "LTLCardinality",
    "LTLFireability",
)
REACHABILITY_EXAMINATIONS = BOOLEAN_EXAMINATIONS[:2]
OTHER_EXAMINATIONS = ("UpperBounds", "GlobalProperties", "StateSpace")
# Mode of the output directory: the container user is not the API user.
OUTPUT_DIR_MODE = 0o777
# An engine cannot make the API read an arbitrarily large file.
MAX_OUTPUT_FILE_BYTES = 64 * 1024 * 1024


class EngineSpec(DomainModel):
    """Static description of an engine. ``image`` is None for the in-process dummy engine."""

    image: str | None
    version: str
    logics: tuple[str, ...]
    colored: bool = False
    # The operations (analyses, reductions) this engine performs, by name (ADR 0014).
    operations: tuple[str, ...] = ()
    # The contest examinations it takes part in (docs/mcc-tools.md) and what is known about it.
    examinations: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class ContainerRun(DomainModel):
    """How a container run went; ``failure`` is set when its output must not be read."""

    failure: Literal["timeout", "docker_unavailable", "out_of_memory"] | None
    exit_code: int | None = None
    elapsed_s: float
    output_dir: Path


# Adding an engine = one image + one entry here. Versions stay "tbd" until an image pins a release.
DEFAULT_ENGINES: Mapping[str, EngineSpec] = {
    "dummy": EngineSpec(image=None, version="0.1", logics=ALL_LOGICS),
    # The platform's own analyses, run in a container (engines/native); bump the version, here
    # and in its Dockerfile, with every change of an algorithm: results are cached by version.
    "native": EngineSpec(
        image="pn-llm-verif/native:1.8",
        version="1.8",
        logics=(),
        operations=tuple(op.name for op in OPERATIONS),
    ),
    "itstools": EngineSpec(
        image="pn-llm-verif/itstools:1.0.0.202609112134",
        version="1.0.0.202609112134",
        logics=ALL_LOGICS,
        colored=True,
        examinations=(*BOOLEAN_EXAMINATIONS, *OTHER_EXAMINATIONS),
        limitations=(
            "gives no counterexample",
            "cannot switch its reductions off",
            "the deadlock atom is rewritten as no transition fireable",
            "starts a JVM for each examination (a few seconds)",
        ),
    ),
    "tapaal": EngineSpec(
        image="pn-llm-verif/tapaal:4.4.2",
        version="4.4.2",
        logics=ALL_LOGICS,
        colored=True,
        examinations=(*BOOLEAN_EXAMINATIONS, "UpperBounds", "GlobalProperties"),
        limitations=(
            "gives no counterexample on colored nets (it unfolds them)",
            "one process per formula",
        ),
    ),
    "smpt": EngineSpec(
        image="pn-llm-verif/smpt:latest",
        version="tbd",
        logics=("state",),
        colored=True,
        examinations=REACHABILITY_EXAMINATIONS,
    ),
    # tedd covers the StateSpace category; extend its logics once it is integrated.
    "tedd": EngineSpec(
        image="pn-llm-verif/tedd:latest",
        version="tbd",
        logics=("state",),
        colored=True,
        examinations=("StateSpace",),
    ),
    "petrivet": EngineSpec(
        image="pn-llm-verif/petrivet:latest",
        version="tbd",
        logics=("state",),
        examinations=("StateSpace", "GlobalProperties"),
    ),
    "ty": EngineSpec(
        image="pn-llm-verif/ty:latest",
        version="tbd",
        logics=ALL_LOGICS,
        colored=True,
        examinations=(*BOOLEAN_EXAMINATIONS, *OTHER_EXAMINATIONS),
    ),
}


def non_answers(
    *,
    spec: EngineSpec,
    engine: str,
    request: EngineRequest,
    verdict: Verdict,
    warning: str,
    elapsed: float = 0.0,
) -> EngineReport:
    """Report one non-answer per formula: a failure is never reported as TRUE or FALSE."""
    return EngineReport(
        tool_name=engine,
        tool_version=spec.version,
        status="ok",
        results=tuple(
            ReportedResult(
                result=EngineFormulaResult(
                    id=formula.id, verdict=verdict, time_s=elapsed, warnings=(warning,)
                )
            )
            for formula in request.formulas
        ),
    )


def read_report(*, output_dir: Path) -> EngineReport:
    """Read ``result.json`` and the traces it cites from an engine's output directory.

    A missing, oversized or unreadable file gives a ``failed`` report, never a guess.
    """
    result_file = output_dir / "result.json"
    if not result_file.is_file() or result_file.stat().st_size > MAX_OUTPUT_FILE_BYTES:
        return EngineReport(status="failed", error_code="no_usable_result_file")
    try:
        envelope = Envelope[EngineCheckData].model_validate_json(result_file.read_text())
    except ValueError:  # includes pydantic's ValidationError and invalid JSON
        return EngineReport(status="failed", error_code="unreadable_result_json")
    if envelope.data is None:
        return EngineReport(
            tool_name=envelope.tool.name,
            tool_version=envelope.tool.version,
            status="failed",
            error_code=envelope.error.code if envelope.error else "no_data",
        )
    reported: list[ReportedResult] = []
    for result in envelope.data.results:
        trace = None
        if result.trace is not None:
            trace_file = output_dir / result.trace
            try:
                if trace_file.stat().st_size > MAX_OUTPUT_FILE_BYTES:
                    raise ValueError(trace_file.name)
                trace = EngineTrace.model_validate_json(trace_file.read_text())
            except OSError, ValueError:
                result = result.model_copy(  # noqa: PLW2901 - the loop variable is replaced by its annotated copy
                    update={"warnings": (*result.warnings, "unreadable_trace")}
                )
        reported.append(ReportedResult(result=result, trace=trace))
    return EngineReport(
        tool_name=envelope.tool.name,
        tool_version=envelope.tool.version,
        status=envelope.status,
        error_code=envelope.error.code if envelope.error else None,
        results=tuple(reported),
    )


def read_operation_report(*, output_dir: Path, elapsed_s: float) -> EngineOperationReport:
    """Read the ``result.json`` of an analysis or a reduction.

    A missing, oversized or unreadable file gives a ``failed`` report, never a guess.
    """
    result_file = output_dir / "result.json"
    if not result_file.is_file() or result_file.stat().st_size > MAX_OUTPUT_FILE_BYTES:
        return EngineOperationReport(
            status="failed", error_code="no_usable_result_file", elapsed_s=elapsed_s
        )
    try:
        envelope = Envelope[EngineOperationData].model_validate_json(result_file.read_text())
    except ValueError:
        return EngineOperationReport(
            status="failed", error_code="unreadable_result_json", elapsed_s=elapsed_s
        )
    reduced_file = output_dir / "reduced.pnml"
    reduced = (
        reduced_file.read_bytes()
        if reduced_file.is_file() and reduced_file.stat().st_size <= MAX_OUTPUT_FILE_BYTES
        else None
    )
    return EngineOperationReport(
        tool_name=envelope.tool.name,
        tool_version=envelope.tool.version,
        status=envelope.status,
        error_code=envelope.error.code
        if envelope.error
        else ("no_data" if envelope.data is None else None),
        result=None if envelope.data is None else envelope.data.result,
        reduced_pnml=reduced,
        warnings=envelope.warnings,
        elapsed_s=elapsed_s,
    )


class EngineRegistry:
    """Registered engines, run in ephemeral containers (or in-process for the dummy engine)."""

    def __init__(self, *, specs: Mapping[str, EngineSpec], docker: DockerRunner) -> None:
        """Create the registry from engine specs and the runner used to start containers."""
        self._specs = specs
        self._docker = docker

    def list_engines(self) -> tuple[EngineInfo, ...]:
        """Return every registered engine with its availability on this machine."""
        return tuple(
            EngineInfo(
                name=name,
                version=spec.version,
                logics=spec.logics,
                supports_colored=spec.colored,
                operations=spec.operations,
                examinations=spec.examinations,
                classes=classes_checked_by(examinations=spec.examinations),
                limitations=spec.limitations,
                available=spec.image is None or self._docker.image_present(image=spec.image),
            )
            for name, spec in self._specs.items()
        )

    def is_known(self, *, name: str) -> bool:
        """Return True if ``name`` is a registered engine that verifies formulas."""
        spec = self._specs.get(name)
        return spec is not None and bool(spec.logics)

    def choose(self, *, requested: str) -> str:
        """Return the engine to use: the requested one, or for "auto" the first available.

        Placeholder policy until the tool-selection milestone: first available real engine that
        verifies formulas, else the dummy engine.
        """
        if requested != "auto":
            return requested
        for info in self.list_engines():
            if info.name != "dummy" and info.logics and info.available:
                return info.name
        return "dummy"

    def choose_for(self, *, operation: str, requested: str) -> str:
        """Return the engine that will perform an operation.

        The requested one, or for "auto" the first available one that declares it.

        Raises:
            InvalidRequestError: if the requested engine does not declare the operation, or no
                available engine does.
        """
        declaring = [info for info in self.list_engines() if operation in info.operations]
        if requested != "auto":
            if requested not in {info.name for info in declaring}:
                raise InvalidRequestError(f"Engine {requested!r} does not perform {operation!r}")
            return requested
        for info in declaring:
            if info.available:
                return info.name
        raise InvalidRequestError(f"No available engine performs {operation!r}")

    def version_of(self, *, engine: str) -> str:
        """Return the pinned version of a registered engine.

        Raises:
            InvalidRequestError: if ``engine`` is not registered.
        """
        spec = self._specs.get(engine)
        if spec is None:
            raise InvalidRequestError(f"Unknown engine: {engine}")
        return spec.version

    def stop(self, *, job_id: str) -> None:
        """Kill and remove the engine container of a job, if one is running."""
        self._docker.stop(job_id=job_id)

    @contextlib.contextmanager
    def _container(
        self, *, spec: EngineSpec, pnml: bytes, request: EngineRequest, job_id: str
    ) -> Iterator[ContainerRun]:
        """Run the engine's container on a net and give the output directory while it exists."""
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="pnjob-") as tmp:
            work_dir = Path(tmp)
            (work_dir / "input").mkdir()
            (work_dir / "output").mkdir()
            (work_dir / "output").chmod(OUTPUT_DIR_MODE)
            (work_dir / "input" / "net.pnml").write_bytes(pnml)
            (work_dir / "input" / "request.json").write_text(request.model_dump_json())
            output_dir = work_dir / "output"
            try:
                outcome = self._docker.run(
                    image=spec.image or "", job_id=job_id, work_dir=work_dir, limits=request.limits
                )
            except DockerTimeoutError:
                yield ContainerRun(
                    failure="timeout", elapsed_s=time.monotonic() - started, output_dir=output_dir
                )
                return
            except DockerUnavailableError:
                yield ContainerRun(
                    failure="docker_unavailable",
                    elapsed_s=time.monotonic() - started,
                    output_dir=output_dir,
                )
                return
            yield ContainerRun(
                # whatever the engine managed to write is not trusted after an out-of-memory kill
                failure="out_of_memory" if outcome.oom_killed else None,
                exit_code=outcome.exit_code,
                elapsed_s=time.monotonic() - started,
                output_dir=output_dir,
            )

    def run(self, *, engine: str, pnml: bytes, request: EngineRequest, job_id: str) -> EngineReport:
        """Run an engine on a net and report what it produced, one result per formula.

        Failures never become verdicts: a timeout, an out-of-memory kill or an unreachable Docker
        give TIMEOUT, OOM or ERROR for every formula, never TRUE or FALSE. Whatever the engine
        wrote is only read here; the platform checks it (``app.domain.engine_check``).

        Raises:
            InvalidRequestError: if ``engine`` is not registered.
        """
        spec = self._specs.get(engine)
        if spec is None:
            raise InvalidRequestError(f"Unknown engine: {engine}")

        if spec.image is None:  # the dummy engine verifies nothing and says so
            return non_answers(
                spec=spec,
                engine=engine,
                request=request,
                verdict=Verdict.UNKNOWN,
                warning="dummy_engine_no_verification",
            )

        with self._container(spec=spec, pnml=pnml, request=request, job_id=job_id) as ran:
            failures = {
                "timeout": (Verdict.TIMEOUT, "engine_timeout"),
                "docker_unavailable": (Verdict.ERROR, "docker_unavailable"),
                "out_of_memory": (Verdict.OOM, "engine_out_of_memory"),
            }
            if ran.failure is not None:
                verdict, warning = failures[ran.failure]
                return non_answers(
                    spec=spec,
                    engine=engine,
                    request=request,
                    verdict=verdict,
                    warning=warning,
                    elapsed=ran.elapsed_s,
                )
            report = read_report(output_dir=ran.output_dir)
            if report.status == "failed" and report.error_code == "no_usable_result_file":
                return non_answers(
                    spec=spec,
                    engine=engine,
                    request=request,
                    verdict=Verdict.ERROR,
                    warning=f"no_result_file_exit_{ran.exit_code}",
                    elapsed=ran.elapsed_s,
                )
            return report

    def run_operation(
        self, *, engine: str, pnml: bytes, request: EngineRequest, job_id: str
    ) -> EngineOperationReport:
        """Run an analysis or a reduction in an engine's container and read its result.

        Every failure is reported as a ``failed`` report with a code, never as a result.

        Raises:
            InvalidRequestError: if ``engine`` is not registered or has no image.
        """
        spec = self._specs.get(engine)
        if spec is None or spec.image is None:
            raise InvalidRequestError(f"Engine {engine!r} cannot run operations")
        with self._container(spec=spec, pnml=pnml, request=request, job_id=job_id) as ran:
            if ran.failure is not None:
                return EngineOperationReport(
                    status="failed", error_code=ran.failure, elapsed_s=ran.elapsed_s
                )
            return read_operation_report(output_dir=ran.output_dir, elapsed_s=ran.elapsed_s)
