import json

import pytest

from app import analyze_runs, audit_sessions, rate
from app.domain.nets import NetFormat
from tests.support import MUTEX_PNML
from tests.unit.test_experiment import ArcCounting, runner_over, spec


@pytest.fixture
def records_file(store, tmp_path):
    nets, runner = runner_over(store=store, engines=ArcCounting(trace_steps=("enter1",)))
    net_id = nets.register(payload=MUTEX_PNML, format=NetFormat.PNML).stored.summary.net_id
    record = runner.run_baseline(spec=spec(properties=5), net_id=net_id)
    path = tmp_path / "b0.jsonl"
    path.write_text(record.model_dump_json() + "\n\n")
    return path


def run(monkeypatch, main, *argv):
    monkeypatch.setattr("sys.argv", ["prog", *map(str, argv)])
    main()


def test_the_analysis_command_prints_the_protocol_analysis(monkeypatch, capsys, records_file):
    run(monkeypatch, analyze_runs.analyze_main, records_file, "--seed", "x")
    out = json.loads(capsys.readouterr().out)
    assert out["primary"]["condition"] == "L3"
    assert out["primary"]["families"] == 0
    assert {v["condition"] for v in out["families"]} == {"B0"}


def test_the_rating_commands_write_a_blind_sheet_and_analyze_filled_ratings(
    monkeypatch, capsys, records_file, tmp_path
):
    items, key = tmp_path / "sheet.json", tmp_path / "key.json"
    run(
        monkeypatch,
        rate.rate_main,
        "sheet",
        records_file,
        "--per-family",
        "3",
        "--items-out",
        items,
        "--key-out",
        key,
    )
    shown = json.loads(items.read_text())
    assert len(shown) == 3
    assert "B0" not in items.read_text()
    assert "B0" in key.read_text()
    ratings = tmp_path / "ratings.json"
    ratings.write_text(
        json.dumps(
            [
                {"item_id": i["item_id"], "rater": r, "score": 4, "keep": True}
                for i in shown
                for r in ("ann", "bob")
            ]
        )
    )
    run(monkeypatch, rate.rate_main, "analyze", "--key", key, ratings)
    out = json.loads(capsys.readouterr().out)
    assert out["agreement"][0]["items"] == 3
    assert {v["measure"] for v in out["values"]} == {"M8_rating", "M8_keep"}


def test_the_audit_command_exits_zero_on_a_sound_database_and_prints_its_report(
    monkeypatch, capsys, settings, store
):
    monkeypatch.setenv("PNVERIF_DATABASE_PATH", str(settings.database_path))
    with pytest.raises(SystemExit) as stopped:
        run(monkeypatch, audit_sessions.audit_main)
    assert stopped.value.code == 0
    assert json.loads(capsys.readouterr().out)["sound"] is True


def test_the_study_command_measures_the_sessions_of_the_database(
    monkeypatch, capsys, settings, store
):
    from app import study
    from app.domain.canonical import net_id_of
    from app.domain.nets import summarize_document
    from app.domain.sessions import Session, SessionStarted, SessionState
    from tests.support import MUTEX_DOCUMENT

    net_id = net_id_of(document=MUTEX_DOCUMENT)
    store.save_net(
        summary=summarize_document(document=MUTEX_DOCUMENT, net_id=net_id), document=MUTEX_DOCUMENT
    )
    session = Session(
        session_id="s1", net_id=net_id, state=SessionState.IDLE, created_at=1.0, updated_at=1.0
    )
    store.create_session(session=session, started=SessionStarted(net_id=net_id, goal="g"))
    monkeypatch.setenv("PNVERIF_DATABASE_PATH", str(settings.database_path))
    run(monkeypatch, study.study_main)
    out = json.loads(capsys.readouterr().out)
    assert [m["session_id"] for m in out] == ["s1"]
    run(monkeypatch, study.study_main, "--session", "s1")
    assert json.loads(capsys.readouterr().out)[0]["questions"] == 0


def test_the_analysis_command_takes_a_manifest_and_splits_by_provenance(
    monkeypatch, capsys, records_file, tmp_path
):
    from app.domain.freeze import FreezeManifest, FrozenFamily

    manifest = FreezeManifest(
        name="f",
        split="v1",
        split_seed="s",
        selection_rule="r",
        thresholds=(),
        git_commit="c",
        protocol_sha256="p",
        engines=(),
        families=(FrozenFamily(family="Mutex", role="dev", provenance="synthetic"),),
    )
    path = tmp_path / "freeze.json"
    path.write_text(manifest.model_dump_json())
    run(monkeypatch, analyze_runs.analyze_main, records_file, "--manifest", path)
    out = json.loads(capsys.readouterr().out)
    assert [label for label, _ in out["by_provenance"]] == ["synthetic"]
