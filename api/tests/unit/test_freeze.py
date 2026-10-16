import pytest

from app.domain.analysis_stats import FamilyProvenance, analyze_runs
from app.domain.freeze import ExtraFamily, FrozenVersion, build_manifest
from app.domain.splits import make_split


def split():
    return make_split(
        name="v1", seed="seed", folds=2, test_fraction=0.25, families=("A", "B", "C", "D")
    )


def manifest(*extras):
    return build_manifest(
        name="eval-freeze-1",
        split=split(),
        extras=extras,
        git_commit="abc",
        protocol_text="protocol",
        engines=(FrozenVersion(name="tapaal", version="4.4.2"),),
    )


def test_the_manifest_lists_every_family_with_its_role_and_provenance():
    own = ExtraFamily(family="Mine", provenance="unpublished", role="test", net_ids=("n1",))
    synthetic = ExtraFamily(family="Gen", provenance="synthetic", role="dev", net_ids=("n2",))
    frozen = manifest(own, synthetic)
    by_family = {f.family: f for f in frozen.families}
    assert {f.provenance for f in frozen.families} == {"public", "unpublished", "synthetic"}
    assert (by_family["Mine"].role, by_family["Gen"].role) == ("test", "dev")
    assert sum(f.role == "test" for f in frozen.families if f.provenance == "public") == 1
    assert frozen.git_commit == "abc"
    assert frozen.engines[0].version == "4.4.2"
    assert "C3" in " ".join(frozen.thresholds)
    assert "'seed'" in frozen.selection_rule


def test_the_manifest_is_the_same_for_the_same_inputs_and_changes_with_the_protocol():
    assert manifest() == manifest()
    other = build_manifest(
        name="eval-freeze-1",
        split=split(),
        extras=(),
        git_commit="abc",
        protocol_text="protocol edited",
        engines=(),
    )
    assert other.protocol_sha256 != manifest().protocol_sha256


def test_an_extra_family_cannot_take_a_contest_family_name():
    clash = ExtraFamily(family="A", provenance="synthetic", role="dev", net_ids=())
    with pytest.raises(ValueError, match="share a name"):
        manifest(clash)


def test_the_analysis_is_also_run_on_each_provenance_apart():
    provenance = (
        FamilyProvenance(family="A", provenance="public"),
        FamilyProvenance(family="Mine", provenance="unpublished"),
    )
    analysis = analyze_runs(records=(), seed="s", provenance=provenance)
    assert [label for label, _ in analysis.by_provenance] == ["public", "unpublished"]
    assert all(part.primary.families == 0 for _, part in analysis.by_provenance)
    assert analyze_runs(records=(), seed="s").by_provenance == ()
