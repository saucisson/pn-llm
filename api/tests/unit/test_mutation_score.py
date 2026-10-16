import pytest

from app.domain.models import Verdict as Value
from app.domain.mutation_score import (
    PropertyOutcome,
    judge_mutant,
    score_condition,
    score_family,
)


def outcome(original, mutant, *, pid="p", replays=None):
    return PropertyOutcome(
        property_id=pid, original=original, mutant=mutant, replays_on_mutant=replays
    )


def judge(*outcomes):
    return judge_mutant(mutant_id="m", outcomes=tuple(outcomes))


def test_a_property_whose_definitive_verdict_changes_kills_the_mutant():
    judgement = judge(
        outcome(Value.TRUE, Value.FALSE, pid="a"), outcome(Value.TRUE, Value.TRUE, pid="b")
    )
    assert (judgement.status, judgement.killers) == ("killed", ("a",))


@pytest.mark.parametrize("word", [Value.UNKNOWN, Value.TIMEOUT, Value.OOM, Value.ERROR])
def test_a_non_answer_never_kills_and_leaves_the_mutant_undecided(word):
    assert judge(outcome(Value.TRUE, word)).status == "undecided"
    assert judge(outcome(word, Value.FALSE)).status == "undecided"
    assert judge(outcome(Value.TRUE, word), outcome(Value.TRUE, Value.TRUE)).status == "undecided"


def test_a_kill_stands_even_when_another_property_could_not_decide():
    assert (
        judge(outcome(Value.TRUE, Value.FALSE), outcome(Value.TRUE, Value.TIMEOUT)).status
        == "killed"
    )


def test_a_mutant_every_property_decided_without_a_change_survived_and_is_not_called_equivalent():
    judgement = judge(outcome(Value.TRUE, Value.TRUE), outcome(Value.FALSE, Value.FALSE))
    assert judgement.status == "survived"
    assert judge().status == "undecided"  # no property: nothing was tried


def test_a_fault_is_found_only_by_a_counterexample_that_replays_on_the_mutant():
    assert judge(outcome(Value.TRUE, Value.FALSE, replays=True)).fault_found
    assert not judge(outcome(Value.TRUE, Value.FALSE, replays=False)).fault_found
    assert not judge(outcome(Value.TRUE, Value.FALSE, replays=None)).fault_found
    assert not judge(
        outcome(Value.FALSE, Value.FALSE, replays=True)
    ).fault_found  # failed before too
    assert not judge(outcome(Value.FALSE, Value.TRUE, replays=True)).fault_found


def test_family_scores_leave_undecided_mutants_out_of_the_ratio_and_count_them():
    j = [
        judge(outcome(Value.TRUE, Value.FALSE, replays=True)),
        judge(outcome(Value.TRUE, Value.TRUE)),
        judge(outcome(Value.TRUE, Value.TIMEOUT)),
        judge(outcome(Value.TRUE, Value.FALSE, replays=False)),
    ]
    score = score_family(family="F", judgements=tuple(j))
    assert (score.mutants, score.killed, score.survived, score.undecided) == (4, 2, 1, 1)
    assert score.score == pytest.approx(2 / 3)
    assert score.fault_finding == 0.25


def test_a_family_with_nothing_decided_has_no_score_and_does_not_enter_the_mean():
    nothing = score_family(family="E", judgements=(judge(outcome(Value.TRUE, Value.TIMEOUT)),))
    half = score_family(
        family="F",
        judgements=(
            judge(outcome(Value.TRUE, Value.FALSE)),
            judge(outcome(Value.TRUE, Value.TRUE)),
        ),
    )
    empty = score_family(family="Z", judgements=())
    assert nothing.score is None
    assert empty.fault_finding is None
    condition = score_condition(families=(half, nothing, empty))
    assert condition.mean_score == 0.5
    assert [f.family for f in condition.families] == ["E", "F", "Z"]
    assert score_condition(families=()).mean_score is None
