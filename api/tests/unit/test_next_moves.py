import pytest

from app.domain.models import FormulaResult, Verdict
from app.domain.next_moves import next_moves_for


def result(verdict, **extra):
    return FormulaResult(id="f", verdict=verdict, engine="a", **extra)


def kinds(*, verdict, untried=(), reduced=True, timeout_s=60, **extra):
    moves = next_moves_for(
        result=result(verdict, **extra),
        untried_engines=untried,
        reduced=reduced,
        timeout_s=timeout_s,
    )
    return None if moves is None else [m.kind for m in moves.moves]


@pytest.mark.parametrize("verdict", [Verdict.TRUE, Verdict.FALSE])
def test_an_answer_needs_no_move(verdict):
    assert kinds(verdict=verdict) is None


def test_a_contradiction_is_reported_not_worked_around():
    assert kinds(verdict=Verdict.UNKNOWN, agreement="contradiction") is None


def test_an_error_is_about_the_engine_not_the_difficulty():
    assert kinds(verdict=Verdict.ERROR, untried=("b",)) == ["other_engine"]
    assert kinds(verdict=Verdict.ERROR) == []


def test_out_of_memory_does_not_suggest_a_longer_timeout():
    assert kinds(verdict=Verdict.OOM, reduced=False) == [
        "reduce_first",
        "simpler_property",
        "weaker_property",
    ]


def test_a_timeout_at_the_maximum_cannot_be_extended():
    assert "longer_timeout" in kinds(verdict=Verdict.TIMEOUT, timeout_s=60)
    assert "longer_timeout" not in kinds(verdict=Verdict.TIMEOUT, timeout_s=600)
