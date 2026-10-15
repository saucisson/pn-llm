"""Run the conformance suite (``python -m app.conformance --cases tests/corpus/conformance.json``).

Prints the matrix as JSON, or as a Markdown table with ``--markdown``, and exits with 1 when a
row needs triage (a wrong answer, or two engines contradicting each other).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import TypeAdapter

from app.application.conformance import ConformanceService
from app.domain.conformance import CaseSpec, ConformanceCase, render_markdown
from app.domain.errors import InvalidRequestError
from app.domain.formula_text import formula_from_text
from app.domain.mcc_properties import parse_property_set
from app.domain.models import Limits, Verdict
from app.infrastructure.docker_runner import DockerRunner
from app.infrastructure.engine_registry import DEFAULT_ENGINES, EngineRegistry
from app.infrastructure.json_logging import configure_logging
from app.settings import Settings

CASES = TypeAdapter(tuple[CaseSpec, ...])


def load_cases(*, path: Path) -> tuple[ConformanceCase, ...]:
    """Read a cases file and find each case's net and formula next to it.

    Raises:
        InvalidRequestError: if a case names neither a formula nor a contest property, or a
            contest property that is not in its file.
    """
    resolved = []
    for spec in CASES.validate_json(path.read_bytes()):
        net_path = path.parent / spec.net
        if spec.formula_text is not None:
            formula = formula_from_text(
                text=spec.formula_text,
                formula_id=spec.id,
                logic=spec.logic,
                gloss=spec.source,
                origin="template",
            )
        elif spec.examination is not None and spec.property_id is not None:
            properties = parse_property_set(
                examination=spec.examination,  # type: ignore[arg-type]  # validated by the parser
                xml=(net_path.parent / f"{spec.examination}.xml").read_bytes(),
            )
            found = [p for p in properties.formulas if p.id == spec.property_id]
            if not found:
                raise InvalidRequestError(f"{spec.id}: no property {spec.property_id}")
            formula = found[0].model_copy(update={"id": spec.id})
        else:
            raise InvalidRequestError(
                f"{spec.id}: give formula_text or examination and property_id"
            )
        resolved.append(
            ConformanceCase(
                case_id=spec.id,
                net=spec.net,
                pnml=net_path.read_bytes(),
                formula=formula,
                expected=Verdict(spec.expected),
                source=spec.source,
            )
        )
    return tuple(resolved)


def conformance_main() -> None:
    """Run the cases on the chosen engines and print the matrix."""
    parser = argparse.ArgumentParser(description="Cross-engine conformance suite.")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--engines", nargs="*", help="default: every engine whose image is built")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--memory", type=int, default=4096)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--no-reduce", action="store_true", help="ask engines not to reduce")
    arguments = parser.parse_args()

    config = Settings()
    configure_logging(level=config.log_level, as_json=config.log_json)
    service = ConformanceService(
        engines=EngineRegistry(specs=DEFAULT_ENGINES, docker=DockerRunner())
    )
    matrix = service.run(
        cases=load_cases(path=arguments.cases),
        engines=tuple(arguments.engines) if arguments.engines else service.available_engines(),
        limits=Limits(timeout_s=arguments.timeout, memory_mb=arguments.memory),
        reduce=not arguments.no_reduce,
    )
    sys.stdout.write(
        render_markdown(matrix=matrix)
        if arguments.markdown
        else matrix.model_dump_json(indent=2) + "\n"
    )
    sys.exit(1 if matrix.failures() else 0)


if __name__ == "__main__":
    conformance_main()
