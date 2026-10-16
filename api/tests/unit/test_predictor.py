import pytest

from app.application.predictor_training import PredictorTrainer
from app.application.results import ResultsService
from app.application.selection import SelectionRequest, SelectionService
from app.domain.errors import InvalidRequestError, NotFoundError
from app.domain.formula_text import formula_from_text
from app.domain.mcc import MccNetType
from app.domain.mcc_results import HEADER
from app.domain.models import EngineInfo
from app.domain.predictor import (
    InstanceSize,
    LabelledRun,
    Leaf,
    expected_time_s,
    features_of,
    grow,
    probability_of,
)
from app.domain.selection_evaluation import (
    Hyperparameters,
    InstanceRun,
    cross_validate,
    key_runs,
    pick,
    score_selection,
    train_predictor,
)
from app.domain.splits import make_split
from app.infrastructure.sqlite_catalog import SqliteCatalog
from app.infrastructure.sqlite_results import SqliteResults
from app.infrastructure.sqlite_splits import SqliteSplits
from tests.unit.test_results_service import FakeContest

EXAM = "ReachabilityCardinality"


def sized(name, family, places):
    return InstanceSize(
        instance=name,
        family=family,
        net_type=MccNetType.PT,
        places=places,
        transitions=places,
        arcs=places * 2,
    )


def run(name, family, tool, answered, time_ms=1000.0):
    return InstanceRun(
        instance=name,
        family=family,
        tool=tool,
        examination=EXAM,
        answered=answered,
        time_ms=time_ms,
    )


def world(*, families=8):
    """Engine small answers small nets, engine big answers large ones."""
    sizes, runs = [], []
    for index in range(families):
        for step, places in enumerate((10, 20, 5_000, 8_000)):
            name = f"F{index}-PT-{step}"
            sizes.append(sized(name, f"F{index}", places))
            runs.append(run(name, f"F{index}", "small", places < 1000))
            runs.append(run(name, f"F{index}", "big", places >= 1000))
    return tuple(sizes), tuple(runs)


def test_a_tree_splits_where_the_answers_change_and_keeps_its_counts():
    data = tuple(
        LabelledRun(features=(float(x),), answered=x < 5, log_time=3.0 if x < 5 else 0.0)
        for x in range(10)
        for _ in range(3)
    )
    tree = grow(runs=data, depth=0, max_depth=3, min_leaf=2)
    assert probability_of(tree=tree, features=(2.0,)) == 1.0
    assert probability_of(tree=tree, features=(7.0,)) == 0.0
    assert expected_time_s(tree=tree, features=(2.0,)) == pytest.approx(1.0)  # 10**3 ms
    assert expected_time_s(tree=tree, features=(7.0,)) is None  # nothing answered there


def test_a_pure_or_tiny_set_stays_a_leaf():
    same = tuple(LabelledRun(features=(float(x),), answered=True) for x in range(10))
    assert isinstance(grow(runs=same, depth=0, max_depth=4, min_leaf=2), Leaf)
    assert isinstance(grow(runs=same[:2], depth=0, max_depth=4, min_leaf=5), Leaf)
    assert grow(runs=(), depth=0, max_depth=4, min_leaf=1).probability == 0.0


def test_features_are_log_sizes_and_the_colored_flag():
    assert features_of(places=100, transitions=10, arcs=1000, colored=True) == (2.0, 1.0, 3.0, 1.0)
    assert features_of(places=0, transitions=0, arcs=0, colored=False) == (0.0, 0.0, 0.0, 0.0)


def test_the_model_picks_the_engine_that_suits_the_size_of_the_net():
    sizes, runs = world()
    predictor = train_predictor(
        runs=runs,
        sizes=sizes,
        families=frozenset(f"F{i}" for i in range(8)),
        hyper=Hyperparameters(max_depth=3, min_leaf=2, margin=0.0),
        trained_on="test",
    )
    small = features_of(places=10, transitions=10, arcs=20, colored=False)
    large = features_of(places=6_000, transitions=6_000, arcs=12_000, colored=False)
    assert (
        pick(predictor=predictor, features=small, examination=EXAM, tools=["small", "big"])
        == "small"
    )
    assert (
        pick(predictor=predictor, features=large, examination=EXAM, tools=["small", "big"]) == "big"
    )
    assert pick(predictor=predictor, features=small, examination="Other", tools=["small"]) is None


def test_a_margin_keeps_the_default_engine_unless_another_is_clearly_better():
    sizes, runs = world()
    families = frozenset(f"F{i}" for i in range(8))
    cautious = train_predictor(
        runs=runs,
        sizes=sizes,
        families=families,
        hyper=Hyperparameters(max_depth=3, min_leaf=2, margin=1.0),
        trained_on="test",
    )
    large = features_of(places=6_000, transitions=6_000, arcs=12_000, colored=False)
    default = cautious.defaults[0].tool
    assert (
        pick(predictor=cautious, features=large, examination=EXAM, tools=["small", "big"])
        == default
    )


def test_engines_that_never_answered_an_examination_have_no_tree_for_it():
    sizes, runs = world(families=2)
    runs = (*runs, run("F0-PT-0", "F0", "absent", False))
    predictor = train_predictor(
        runs=runs,
        sizes=sizes,
        families=frozenset({"F0", "F1"}),
        hyper=Hyperparameters(max_depth=2, min_leaf=1, margin=0.0),
        trained_on="test",
    )
    assert {t.tool for t in predictor.trees} == {"small", "big"}


def test_cross_validation_by_family_shows_the_selector_reaching_the_oracle_where_size_decides():
    sizes, runs = world(families=10)
    split = make_split(
        name="s", seed="x", folds=3, test_fraction=0.2, families=tuple(f"F{i}" for i in range(10))
    )
    result = cross_validate(
        runs=runs,
        sizes=sizes,
        split=split,
        hyper=Hyperparameters(max_depth=3, min_leaf=2, margin=0.0),
    )
    score = result.score
    dev = [a.family for a in split.assignments if a.role == "dev"]
    assert score.questions == 4 * len(dev)
    assert score.selector_solved == score.virtual_best_solved == score.questions
    assert score.single_best_solved < score.virtual_best_solved
    assert {f.family for f in score.by_family} == set(dev)  # the test families are never read
    assert score.selector_par2_s < score.single_best_par2_s


def test_score_selection_needs_two_engines_on_a_question_and_counts_misses_at_twice_the_timeout():
    sizes, runs = world(families=2)
    predictor = train_predictor(
        runs=runs,
        sizes=sizes,
        families=frozenset({"F0"}),
        hyper=Hyperparameters(max_depth=3, min_leaf=1, margin=0.0),
        trained_on="test",
    )
    alone = {
        k: {t: r for t, r in v.items() if t == "small"}
        for k, v in key_runs(runs=runs, families=frozenset({"F1"})).items()
    }
    empty = score_selection(
        predictor=predictor,
        train_runs=runs,
        test_runs=alone,
        sizes=sizes,
        train_families=frozenset({"F0"}),
    )
    assert empty.questions == 0
    both = key_runs(runs=runs, families=frozenset({"F1"}))
    full = score_selection(
        predictor=predictor,
        train_runs=runs,
        test_runs=both,
        sizes=sizes,
        train_families=frozenset({"F0"}),
    )
    assert full.questions == 4
    assert full.virtual_best_par2_s == pytest.approx(1.0)  # one second, answered every time


# ---- persistence and use ---------------------------------------------------------------------


def test_sizes_are_stored_and_replaced(settings):
    catalog = SqliteCatalog(path=settings.database_path)
    assert catalog.save_sizes(sizes=[sized("A-PT-1", "A", 10), sized("B-PT-1", "B", 20)]) == 2
    catalog.save_sizes(sizes=[sized("A-PT-1", "A", 11)])
    assert [(s.instance, s.places) for s in catalog.sizes()] == [("A-PT-1", 11), ("B-PT-1", 20)]


ROWS = (
    "itstools,Big-PT-1,ReachabilityCardinality,4,OK,OK,16 BOOL:TRUE,-,1,1,2000,0,normal,r1",
    "itstools,Big-PT-1,ReachabilityCardinality,4,DNF,OK,DNF,-,1,1,9,0,timeout,r1b",
    "tapaal,Big-PT-1,ReachabilityCardinality,4,DNF,OK,DNF,-,1,1,3600000,0,timeout,r2",
    "tapaal,Big-PT-1,ReachabilityCardinality,4,OK,OK,16 BOOL:TRUE,-,1,1,500,0,normal,r2b",
    "tapaal,Odd-PT-2,CTLCardinality,4,OK,OK,16 BOOL:TRUE,-,1,1,500,0,normal,r3",
    "gold2025,Big-PT-1,ReachabilityCardinality,1,OK,OK,16 BOOL:TRUE,-,1,1,1,0,normal,r4",
)


def test_runs_are_read_one_per_engine_and_question_references_left_out_a_rerun_that_answers_wins(
    settings,
):
    results = SqliteResults(path=settings.database_path)
    ResultsService(results=results).import_results(
        source=FakeContest(lines=(f"### {HEADER}", *ROWS)), year=2026
    )
    got = {(r.instance, r.tool, r.examination): r for r in results.instance_runs()}
    assert set(got) == {
        ("Big-PT-1", "itstools", EXAM),
        ("Big-PT-1", "tapaal", EXAM),
        ("Odd-PT-2", "tapaal", "CTLCardinality"),
    }
    assert got[("Big-PT-1", "itstools", EXAM)].answered is True  # the later re-run did not answer
    assert got[("Big-PT-1", "tapaal", EXAM)].answered is True  # the later re-run answered
    assert got[("Big-PT-1", "tapaal", EXAM)].time_ms == 500


def test_the_trainer_reads_only_development_families_and_refuses_when_there_is_nothing(
    settings, monkeypatch, capsys, tmp_path
):
    catalog = SqliteCatalog(path=settings.database_path)
    results = SqliteResults(path=settings.database_path)
    splits = SqliteSplits(path=settings.database_path)
    trainer = PredictorTrainer(catalog=catalog, results=results, splits=splits)
    with pytest.raises(NotFoundError):
        trainer.train(split_name="none", max_depth=2, min_leaf=1, margins=(0.0,))
    sizes, runs = world(families=10)
    families = tuple(f"F{i}" for i in range(10))
    splits.save_split(
        split=make_split(name="v1", seed="s", folds=2, test_fraction=0.2, families=families)
    )
    with pytest.raises(InvalidRequestError, match="Nothing to learn"):
        trainer.train(split_name="v1", max_depth=2, min_leaf=1, margins=(0.0,))
    catalog.save_sizes(sizes=sizes)

    def row(i, r):
        outcome = "16 BOOL:TRUE" if r.answered else "DNC"
        return (
            f"{r.tool},{r.instance},{r.examination},4,OK,OK,{outcome},-,1,1,"
            f"{int(r.time_ms)},0,normal,r{i}"
        )

    rows = tuple(row(i, r) for i, r in enumerate(runs))
    ResultsService(results=results).import_results(
        source=FakeContest(lines=(f"### {HEADER}", *rows)), year=2026
    )
    report = trainer.train(split_name="v1", max_depth=3, min_leaf=2, margins=(0.0, 1.0))
    assert len(report.tried) == 2
    assert report.validation.margin == 0.0  # the margin that scored best on the development folds
    assert report.predictor.trained_on.startswith("split v1")
    held_out = {a.family for a in splits.load_split(name="v1").assignments if a.role == "test"}
    assert held_out
    assert {f.family for f in report.validation.score.by_family}.isdisjoint(held_out)

    # The command does the same from the database and writes the model for the settings to load.
    from app import train_predictor
    from app.domain.predictor import Predictor

    out = tmp_path / "model.json"
    monkeypatch.setenv("PNVERIF_DATABASE_PATH", str(settings.database_path))
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "--split",
            "v1",
            "--out",
            str(out),
            "--max-depth",
            "3",
            "--min-leaf",
            "2",
            "--margins",
            "0.0",
            "1.0",
        ],
    )
    train_predictor.train_main()
    assert Predictor.model_validate_json(out.read_text()).trained_on.startswith("split v1")
    assert "margin" in capsys.readouterr().out


# ---- the selector with a model -----------------------------------------------------------------


class Listed:
    def __init__(self, *engines):
        self._engines = engines

    def list_engines(self):
        return self._engines


def engine(name):
    return EngineInfo(
        name=name,
        version="1",
        logics=("state",),
        classes=("state-cardinality",),
        examinations=(EXAM,),
        available=True,
    )


def test_a_model_ranks_the_engines_for_the_size_of_the_net(store, settings, mutex_pnml):
    from app.application.nets import NetService
    from app.domain.net_validation import DocumentLimits
    from app.domain.nets import NetFormat

    sizes, runs = world()
    predictor = train_predictor(
        runs=runs,
        sizes=sizes,
        families=frozenset(f"F{i}" for i in range(8)),
        hyper=Hyperparameters(max_depth=3, min_leaf=2, margin=0.0),
        trained_on="test",
    )
    net_id = (
        NetService(nets=store, max_upload_bytes=10**6, limits=DocumentLimits())
        .register(payload=mutex_pnml, format=NetFormat.PNML)
        .stored.summary.net_id
    )  # 3 places: small
    selection = SelectionService(
        nets=store,
        engines=Listed(engine("big"), engine("small")),
        results=SqliteResults(path=settings.database_path),
        predictor=predictor,
    ).select(
        request=SelectionRequest(
            net_id=net_id,
            formulas=(
                formula_from_text(
                    text='"crit1" >= 1', formula_id="f", logic="state", gloss="", origin="user"
                ),
            ),
        )
    )
    assert selection.basis == "predictor"
    assert [r.engine for r in selection.ranked] == ["small", "big"]
    assert selection.ranked[0].success_probability == 1.0
    assert selection.ranked[1].success_probability == 0.0
    assert selection.ranked[0].expected_time_s == pytest.approx(1.0)
    assert "model" in selection.ranked[0].rationale
