"""Dummy engine: the smallest adapter, and the test of the Docker runner.

Verifies nothing: answers UNKNOWN for every formula.
"""

from pnverif_engine import AdapterAnswer, AdapterInput, normalize_verdict, run_adapter

VERSION = "0.2"


def check(given: AdapterInput) -> tuple[AdapterAnswer, ...]:  # noqa: PLR0917 - callback of run_adapter
    """Answer UNKNOWN for each formula, with a warning that nothing was verified."""
    return tuple(
        AdapterAnswer(
            formula_id=formula.id,
            verdict=normalize_verdict(raw="cannot compute"),
            warnings=("dummy_engine_no_verification",),
        )
        for formula in given.request.formulas
    )


if __name__ == "__main__":
    run_adapter(tool_name="dummy-docker", tool_version=VERSION, check=check)
