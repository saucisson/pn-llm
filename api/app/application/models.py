"""Use cases about the contest models: seeding the platform with them, and listing them."""

from __future__ import annotations

from app.domain.contract import PageRequest
from app.domain.errors import DomainError
from app.domain.mcc import (
    MccFamily,
    MccNetType,
    ModelEntry,
    SeedFailure,
    SeedReport,
)
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
    ) -> SeedReport:
        """Store the nets of the chosen families (all if none is named).

        A net that cannot be stored is reported in the result and does not stop the run;
        running again after a crash stores the same nets again, which changes nothing.
        """
        chosen: tuple[MccFamily, ...] = tuple(
            family
            for family in source.catalog()
            if not only_families or family.name in only_families
        )
        stored = 0
        known = 0
        failures: list[SeedFailure] = []
        for family in chosen:
            self._catalog.save_family(family=family)
            taken = 0
            for found in source.nets(family=family):
                if max_nets_per_family is not None and taken >= max_nets_per_family:
                    break
                taken += 1
                try:
                    saved = self._nets.register(payload=found.payload, format=NetFormat.PNML)
                except DomainError as exc:
                    failures.append(
                        SeedFailure(
                            family=family.name, member=found.instance.member, reason=str(exc)
                        )
                    )
                    continue
                net_id = saved.stored.summary.net_id
                self._catalog.save_entry(
                    entry=ModelEntry(
                        net_id=net_id,
                        family=family.name,
                        instance=found.instance.instance,
                        net_type=found.instance.net_type,
                        member=found.instance.member,
                    )
                )
                self._descriptions.save_description(
                    net_id=net_id, text=family.description, origin="mcc"
                )
                if saved.created:
                    stored += 1
                else:
                    known += 1
        return SeedReport(
            families=len(chosen),
            nets_stored=stored,
            nets_already_known=known,
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
