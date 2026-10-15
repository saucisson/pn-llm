"""Test data and builders shared by the test modules."""

from app.domain.models import CheckRequest
from app.domain.net_validation import DocumentLimits
from app.domain.pnml_import import import_pnml

# Lease long enough that no test job expires by accident.
LEASE = 60.0

# Minimal mutual exclusion: one process and a lock.
MUTEX_PNML = b"""<?xml version="1.0"?>
<pnml><net id="mutex" type="http://www.pnml.org/version-2009/grammar/ptnet"><page id="p">
  <place id="idle1"><name><text>idle1</text></name>
    <initialMarking><text>1</text></initialMarking></place>
  <place id="crit1"><name><text>crit1</text></name></place>
  <place id="lock"><name><text>lock</text></name>
    <initialMarking><text>1</text></initialMarking></place>
  <transition id="enter1"><name><text>enter1</text></name></transition>
  <transition id="leave1"><name><text>leave1</text></name></transition>
  <arc id="a1" source="idle1" target="enter1"/>
  <arc id="a2" source="lock" target="enter1"/>
  <arc id="a3" source="enter1" target="crit1"/>
  <arc id="a4" source="crit1" target="leave1"/>
  <arc id="a5" source="leave1" target="idle1"/>
  <arc id="a6" source="leave1" target="lock"/>
</page></net></pnml>"""

CHECK_BODY = {
    "formulas": [{"id": "f1", "syntax": "ltl", "text": "G(!(crit1 && crit2))", "origin": "llm"}],
    "engine": "dummy",
}


def make_request(**overrides) -> CheckRequest:
    """Build a CheckRequest from the default body, with fields overridden by keyword."""
    return CheckRequest.model_validate({**CHECK_BODY, **overrides})


# The same net as a document (children in file order, as imported).
MUTEX_DOCUMENT = import_pnml(payload=MUTEX_PNML, limits=DocumentLimits())


def make_ring(*, size: int) -> bytes:
    """Return a ring of ``size`` philosophers-like cells as PNML: fork_i, think_i, eat_i, take_i."""
    parts = [
        '<pnml><net id="ring" type="http://www.pnml.org/version-2009/grammar/ptnet"><page id="p">'
    ]
    for i in range(1, size + 1):
        marking = "<initialMarking><text>1</text></initialMarking>"
        parts.append(f'<place id="fork{i}"><name><text>fork_{i}</text></name>{marking}</place>')
        parts.append(f'<place id="think{i}"><name><text>think_{i}</text></name>{marking}</place>')
        parts.append(f'<place id="eat{i}"><name><text>eat_{i}</text></name></place>')
        parts.append(f'<transition id="take{i}"><name><text>take_{i}</text></name></transition>')
        nxt = i % size + 1
        parts.append(f'<arc id="af{i}" source="fork{i}" target="take{i}"/>')
        parts.append(f'<arc id="ag{i}" source="fork{nxt}" target="take{i}"/>')
        parts.append(f'<arc id="at{i}" source="think{i}" target="take{i}"/>')
        parts.append(
            f'<arc id="ae{i}" source="take{i}" target="eat{i}">'
            "<inscription><text>2</text></inscription></arc>"
        )
    parts.append("</page></net></pnml>")
    return "".join(parts).encode()
