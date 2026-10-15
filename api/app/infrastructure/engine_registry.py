"""Engine registry: the tools that can verify a net, and how to run them.

Implements the ``EngineGateway`` port. Contract with each engine (docs/engine-contract.md): a
Docker image whose entrypoint reads /work/input/{net.pnml,request.json} and writes
/work/output/result.json.

The default registry lists the tools of the MCC 2026 (docs/mcc-tools.md). Their images are not
built yet: each one has its own integration issue in the backlog.
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

from app.domain.errors import InvalidRequestError
from app.domain.models import (
    CheckRequest,
    DomainModel,
    EngineInfo,
    EngineOutput,
    FormulaResult,
    Verdict,
)

from .docker_runner import DockerRunner, DockerTimeoutError, DockerUnavailableError

ALL_LOGICS = ("ltl", "ctl", "state")
# Mode of the output directory: the container user is not the API user.
OUTPUT_DIR_MODE = 0o777


class EngineSpec(DomainModel):
    """Static description of an engine. ``image`` is None for the in-process dummy engine."""

    image: str | None
    version: str
    logics: tuple[str, ...]
    colored: bool = False


# Adding an engine = one image + one entry here. Versions stay "tbd" until an image pins a release.
DEFAULT_ENGINES: Mapping[str, EngineSpec] = {
    "dummy": EngineSpec(image=None, version="0.1", logics=ALL_LOGICS),
    "itstools": EngineSpec(
        image="pn-llm-verif/itstools:latest", version="tbd", logics=ALL_LOGICS, colored=True
    ),
    "tapaal": EngineSpec(
        image="pn-llm-verif/tapaal:latest", version="tbd", logics=ALL_LOGICS, colored=True
    ),
    "smpt": EngineSpec(
        image="pn-llm-verif/smpt:latest", version="tbd", logics=("state",), colored=True
    ),
    # tedd covers the StateSpace category; extend its logics once it is integrated.
    "tedd": EngineSpec(
        image="pn-llm-verif/tedd:latest", version="tbd", logics=("state",), colored=True
    ),
    "petrivet": EngineSpec(image="pn-llm-verif/petrivet:latest", version="tbd", logics=("state",)),
    "ty": EngineSpec(
        image="pn-llm-verif/ty:latest", version="tbd", logics=ALL_LOGICS, colored=True
    ),
}


def non_answers(
    *, engine: str, request: CheckRequest, verdict: Verdict, warning: str, elapsed: float = 0.0
) -> tuple[FormulaResult, ...]:
    """Return one non-answer per formula: a failure is never reported as TRUE or FALSE."""
    return tuple(
        FormulaResult(
            id=formula.id, verdict=verdict, engine=engine, time_s=elapsed, warnings=(warning,)
        )
        for formula in request.formulas
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
                available=spec.image is None or self._docker.image_present(image=spec.image),
            )
            for name, spec in self._specs.items()
        )

    def is_known(self, *, name: str) -> bool:
        """Return True if ``name`` is a registered engine."""
        return name in self._specs

    def choose(self, *, requested: str) -> str:
        """Return the engine to use: the requested one, or for "auto" the first available.

        Placeholder policy until the tool-selection milestone: first available real engine, else
        the dummy engine.
        """
        if requested != "auto":
            return requested
        for info in self.list_engines():
            if info.name != "dummy" and info.available:
                return info.name
        return "dummy"

    def stop(self, *, job_id: str) -> None:
        """Kill and remove the engine container of a job, if one is running."""
        self._docker.stop(job_id=job_id)

    def run(
        self, *, engine: str, pnml: bytes, request: CheckRequest, job_id: str
    ) -> tuple[FormulaResult, ...]:
        """Run an engine on a net and return one result per formula.

        Failures never become verdicts: a timeout, an out-of-memory kill, a missing Docker or a
        missing result file give TIMEOUT, OOM or ERROR for every formula, never TRUE or FALSE.

        Raises:
            InvalidRequestError: if ``engine`` is not registered.
        """
        spec = self._specs.get(engine)
        if spec is None:
            raise InvalidRequestError(f"Unknown engine: {engine}")

        if spec.image is None:  # the dummy engine verifies nothing and says so
            return tuple(
                FormulaResult(
                    id=formula.id,
                    verdict=Verdict.UNKNOWN,
                    engine=engine,
                    engine_version=spec.version,
                    warnings=("dummy_engine_no_verification",),
                )
                for formula in request.formulas
            )

        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="pnjob-") as tmp:
            work_dir = Path(tmp)
            (work_dir / "input").mkdir()
            (work_dir / "output").mkdir()
            (work_dir / "output").chmod(OUTPUT_DIR_MODE)
            (work_dir / "input" / "net.pnml").write_bytes(pnml)
            (work_dir / "input" / "request.json").write_text(request.model_dump_json())

            try:
                outcome = self._docker.run(
                    image=spec.image, job_id=job_id, work_dir=work_dir, limits=request.limits
                )
            except DockerTimeoutError:
                return non_answers(
                    engine=engine,
                    request=request,
                    verdict=Verdict.TIMEOUT,
                    warning="engine_timeout",
                    elapsed=time.monotonic() - started,
                )
            except DockerUnavailableError:
                return non_answers(
                    engine=engine,
                    request=request,
                    verdict=Verdict.ERROR,
                    warning="docker_unavailable",
                )

            elapsed = time.monotonic() - started
            if outcome.oom_killed:  # whatever the engine managed to write is not trusted
                return non_answers(
                    engine=engine,
                    request=request,
                    verdict=Verdict.OOM,
                    warning="engine_out_of_memory",
                    elapsed=elapsed,
                )
            result_file = work_dir / "output" / "result.json"
            if not result_file.exists():
                return non_answers(
                    engine=engine,
                    request=request,
                    verdict=Verdict.ERROR,
                    warning=f"no_result_file_exit_{outcome.exit_code}",
                    elapsed=elapsed,
                )
            return EngineOutput.model_validate_json(result_file.read_text()).results
