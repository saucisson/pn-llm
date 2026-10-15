"""Test data and builders shared by the test modules."""

from app.domain.models import CheckRequest

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
