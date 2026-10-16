"""Use cases about the contest models: seeding the platform with them, and listing them."""

from __future__ import annotations

from app.domain.contract import PageRequest
from app.domain.errors import DomainError
from app.domain.mcc import (
    MccFamily,
    MccNetType,
    ModelEntry,
    SeedCandidate,
    SeedFailure,
    SeedReport,
)
from app.domain.mcc_properties import Examination, MccProperties, parse_property_set
from app.domain.nets import NetFormat
from app.domain.pagination import Paged, paginate

from .nets import NetService
from .ports import DescriptionRepository, MccSource, ModelCatalogRepository


class ModelCatalogService:
    """Store the contest models as nets, with their family, instance and description."""

    def __init__(
        self,
        *,
        catalog: ModelCatalogRepository,
        nets: NetService,
        descriptions: DescriptionRepository,
    ) -> None:
        """Create the service over its repositories and the net service that registers nets."""
        self._catalog = catalog
        self._nets = nets
        self._descriptions = descriptions

    def seed(
        self,
        *,
        source: MccSource,
        only_families: tuple[str, ...],
        max_nets_per_family: int | None,
        with_properties: bool,
    ) -> SeedReport:
        """Store the nets of the chosen families (all if none is named).

        With ``with_properties`` the nets come from the contest inputs, which also hold the
        formulas of each examination; otherwise from the family archives. A net or property file
        that cannot be stored is reported in the result and does not stop the run; running again
        after a crash stores the same things again, which changes nothing.
        """
        families = {
            family.name: family
            for family in source.catalog()
            if not only_families or family.name in only_families
        }
        for family in families.values():
            self._catalog.save_family(family=family)
        if max_nets_per_family == 0:  # only the catalog was asked for: read no archive
            return SeedReport(
                families=len(families), nets_stored=0, nets_already_known=0, failures=()
            )
        if with_properties:
            candidates = (
                SeedCandidate(
                    family=found.family,
                    instance=found.instance,
                    net_type=found.net_type,
                    member=found.name,
                    payload=found.model,
                    properties=found.properties,
                )
                for found in source.inputs(only_families=tuple(families))
            )
        else:
            candidates = (
                SeedCandidate(
                    family=family.name,
                    instance=found.instance.instance,
                    net_type=found.instance.net_type,
                    member=found.instance.member,
                    payload=found.payload,
                )
                for family in families.values()
                for found in source.nets(family=family)
            )
        stored = 0
        known = 0
        property_sets = 0
        failures: list[SeedFailure] = []
        taken: dict[str, int] = {}
        for candidate in candidates:
            chosen = families.get(candidate.family)
            seen = taken.get(candidate.family, 0)
            if chosen is None or (max_nets_per_family is not None and seen >= max_nets_per_family):
                continue
            taken[candidate.family] = seen + 1
            try:
                saved = self._nets.register(payload=candidate.payload, format=NetFormat.PNML)
            except DomainError as exc:
                failures.append(
                    SeedFailure(family=chosen.name, member=candidate.member, reason=str(exc))
                )
                continue
            net_id = saved.stored.summary.net_id
            self._catalog.save_entry(
                entry=ModelEntry(
                    net_id=net_id,
                    family=chosen.name,
                    instance=candidate.instance,
                    net_type=candidate.net_type,
                    member=candidate.member,
                )
            )
            self._descriptions.save_description(
                net_id=net_id, text=chosen.description, origin="mcc"
            )
            stored += saved.created
            known += not saved.created
            for file in candidate.properties:
                try:
                    parsed = parse_property_set(examination=file.examination, xml=file.xml)
                except DomainError as exc:
                    failures.append(
                        SeedFailure(
                            family=chosen.name,
                            member=f"{candidate.member}/{file.examination}.xml",
                            reason=str(exc),
                        )
                    )
                    continue
                self._catalog.save_properties(net_id=net_id, properties=parsed)
                property_sets += 1
        return SeedReport(
            families=len(families),
            nets_stored=stored,
            nets_already_known=known,
            property_sets_stored=property_sets,
            failures=tuple(failures),
        )

    def families(self) -> tuple[MccFamily, ...]:
        """Return the stored families, by name."""
        return self._catalog.families()

    def entries(
        self, *, family: str | None, net_type: MccNetType | None, page: PageRequest
    ) -> Paged[ModelEntry]:
        """Return a page of the stored contest nets, filtered by family and type."""
        return paginate(items=self._catalog.entries(family=family, net_type=net_type), request=page)

    def properties(self, *, net_id: str, examination: Examination) -> MccProperties:
        """Return the contest's properties of a net for one examination."""
        return self._catalog.properties_of(net_id=net_id, examination=examination)
