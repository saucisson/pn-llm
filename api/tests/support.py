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


def make_formula(*, formula_id: str) -> dict:
    """Return a minimal valid formula (as a request body) on the mutex net."""
    return {
        "id": formula_id,
        "logic": "state",
        "ast": {"op": "tokens", "place": "crit1", "cmp": ">=", "value": 1},
    }


CHECK_BODY = {
    "formulas": [
        {
            "id": "f1",
            "logic": "ltl",
            "gloss": "The critical section never holds two tokens.",
            "origin": "llm",
            "ast": {
                "op": "G",
                "arg": {"op": "tokens", "place": "crit1", "cmp": "<=", "value": 1},
            },
        }
    ],
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


def engine_envelope(*, results, version="9", status="ok", error=None, name="itstools"):
    """Build the ``result.json`` an engine writes (docs/engine-contract.md), as a dict."""
    return {
        "schema_version": "1.0",
        "tool": {"name": name, "version": version},
        "net_id": "n",
        "status": status,
        "data": None if status == "failed" else {"results": results},
        "warnings": [],
        "truncated": None,
        "error": error,
        "elapsed_s": 0.5,
    }


class ScriptedEngines:
    """An engine gateway whose answer is decided by the test: the process boundary double.

    It reports the verdicts and traces it was given for the formulas of the request, as an engine
    would, and lets the platform check them.
    """

    def __init__(self, *, verdict="FALSE", trace_steps=("enter1",), version="1.2.3", tamper=None):
        self.verdict = verdict
        self.trace_steps = trace_steps
        self.version = version
        self.tamper = tamper  # a function from the report to a modified report
        self.stopped = []

    def list_engines(self):
        return ()

    def is_known(self, *, name):
        return True

    def choose(self, *, requested):
        return "scripted" if requested == "auto" else requested

    def stop(self, *, job_id):
        self.stopped.append(job_id)

    def run(self, *, engine, pnml, request, job_id):
        from app.domain.engine_contract import (
            EngineFormulaResult,
            EngineReport,
            EngineTrace,
            EngineTraceStep,
            ReportedResult,
        )
        from app.domain.models import Verdict

        report = EngineReport(
            tool_name=engine,
            tool_version=self.version,
            status="ok",
            results=tuple(
                ReportedResult(
                    result=EngineFormulaResult(
                        id=formula.id, verdict=Verdict(self.verdict), rendered="native syntax"
                    ),
                    trace=EngineTrace(
                        steps=tuple(EngineTraceStep(transition=t) for t in self.trace_steps)
                    )
                    if self.trace_steps
                    else None,
                )
                for formula in request.formulas
            ),
        )
        return self.tamper(report) if self.tamper else report


class InProcessNative:
    """The native engine without its container: the same operations, called as functions.

    The process boundary double for operations. ``gate`` (an Event) holds a run until the test
    lets it go, to test the slow path; ``tamper`` modifies the report, to test the checks.
    """

    def __init__(self, *, gate=None, tamper=None, available=True):
        self.gate = gate
        self.tamper = tamper
        self.available = available
        self.calls = []
        self.stopped = []

    def list_engines(self):
        from app.domain.analyses import ANALYSES
        from app.domain.models import EngineInfo

        return (
            EngineInfo(
                name="native",
                version="1.0",
                logics=(),
                operations=tuple(op.name for op in ANALYSES),
                available=self.available,
            ),
        )

    def is_known(self, *, name):
        return False

    def choose(self, *, requested):
        return requested

    def choose_for(self, *, operation, requested):
        from app.domain.errors import InvalidRequestError

        if requested not in {"auto", "native"} or not self.available:
            raise InvalidRequestError(f"No engine for {operation} ({requested})")
        return "native"

    def version_of(self, *, engine):
        return "1.0"

    def stop(self, *, job_id):
        self.stopped.append(job_id)

    def run_operation(self, *, engine, pnml, request, job_id):
        from app.domain.analyses import find_operation
        from app.domain.engine_contract import EngineOperationReport
        from app.domain.net_structure import build_structure
        from app.domain.net_validation import DocumentLimits
        from app.domain.operations import compute_on
        from app.domain.pnml_import import import_pnml

        self.calls.append(request.operation)
        if self.gate is not None:
            self.gate.wait(timeout=10)
        document = import_pnml(payload=pnml, limits=DocumentLimits())
        structure = build_structure(document=document, net_id=request.net_id)
        result = compute_on(
            definition=find_operation(name=request.operation),
            structure=structure,
            parameters=request.parameters,
        )
        report = EngineOperationReport(
            tool_name=engine,
            tool_version="1.0",
            status="ok",
            result=result.model_dump(mode="json"),
            elapsed_s=0.01,
        )
        return self.tamper(report) if self.tamper else report


def query(*, path, sql, params=()):
    """Run one read-only SQL statement on a database file and close the connection."""
    import contextlib
    import sqlite3

    with contextlib.closing(sqlite3.connect(path)) as conn:
        return conn.execute(sql, params).fetchall()
