# Conformance report

Cross-engine conformance on `api/tests/corpus/conformance.json` (suite: `docs/engines.md`,
`app/conformance.py`). Run on 2026-10-16 with `--timeout 120 --memory 2048`, engines itstools
1.0.0.202609112134, tapaal 4.4.2 and smpt 5.0-82206dd. A cell is the engine's verdict; `!` after it
would mark a wrong answer, and the last column would say `yes` for a row to triage (a wrong answer,
or two engines contradicting each other).

Result: 54 cases, 0 wrong answers, 0 contradictions. itstools has four TIMEOUT and tapaal one, on the
colored instance, within the 120 s of this run; none is a disagreement. smpt checks reachability
only, so its UNKNOWN cells are the CTL and LTL rows (a different question, with the warning
`smpt_checks_reachability_not_<logic>`) and the eight reachability rows of the colored instance
(`colored_nets_not_supported`); all its 13 answers (the reachability rows of the by-hand net and
of `TwoPhaseLocking-PT-nC00004vN`, and the invariants `AG φ`) equal the reference. The cases are the
by-hand ones and the contest's reference answers (see `api/tests/corpus/mcc/README.md`); a
timeout or an UNKNOWN is not an answer and is not counted against an engine here.

| case | expected | itstools | tapaal | smpt | triage |
|---|---|---|---|---|---|
| mutex-reach-true | TRUE | TRUE | TRUE | TRUE |  |
| mutex-reach-false | FALSE | FALSE | FALSE | FALSE |  |
| mutex-ctl-true | TRUE | TRUE | TRUE | TRUE |  |
| mutex-ctl-false | FALSE | FALSE | FALSE | FALSE |  |
| mutex-ltl-true | TRUE | TRUE | TRUE | UNKNOWN |  |
| mutex-ltl-false | FALSE | FALSE | FALSE | UNKNOWN |  |
| mutex-no-deadlock | FALSE | FALSE | FALSE | FALSE |  |
| mutex-ltl-next-true | TRUE | TRUE | TRUE | UNKNOWN |  |
| mutex-ltl-next-false | FALSE | FALSE | FALSE | UNKNOWN |  |
| mutex-ltl-next-twice | TRUE | TRUE | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-ReachabilityCardinality-00 | TRUE | TRUE | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-ReachabilityCardinality-01 | FALSE | FALSE | FALSE | UNKNOWN |  |
| PGCD-COL-D04N050-ReachabilityCardinality-02 | TRUE | TRUE | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-ReachabilityCardinality-03 | TRUE | TRUE | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-ReachabilityFireability-00 | FALSE | FALSE | FALSE | UNKNOWN |  |
| PGCD-COL-D04N050-ReachabilityFireability-01 | FALSE | FALSE | FALSE | UNKNOWN |  |
| PGCD-COL-D04N050-ReachabilityFireability-02 | TRUE | TRUE | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-ReachabilityFireability-03 | TRUE | TRUE | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-CTLCardinality-00 | TRUE | TRUE | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-CTLCardinality-01 | FALSE | TIMEOUT | TIMEOUT | UNKNOWN |  |
| PGCD-COL-D04N050-CTLFireability-00 | TRUE | TRUE | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-CTLFireability-01 | TRUE | TIMEOUT | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-CTLFireability-02 | TRUE | TRUE | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-CTLFireability-03 | TRUE | TIMEOUT | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-LTLCardinality-00 | TRUE | TRUE | TRUE | UNKNOWN |  |
| PGCD-COL-D04N050-LTLCardinality-01 | FALSE | TIMEOUT | FALSE | UNKNOWN |  |
| PGCD-COL-D04N050-LTLCardinality-02 | FALSE | FALSE | FALSE | UNKNOWN |  |
| PGCD-COL-D04N050-LTLCardinality-03 | FALSE | FALSE | FALSE | UNKNOWN |  |
| PGCD-COL-D04N050-LTLFireability-00 | FALSE | FALSE | FALSE | UNKNOWN |  |
| PGCD-COL-D04N050-LTLFireability-01 | FALSE | FALSE | FALSE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityCardinality-00 | TRUE | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityCardinality-01 | TRUE | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityCardinality-02 | TRUE | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityCardinality-03 | FALSE | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityFireability-00 | FALSE | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityFireability-01 | TRUE | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityFireability-02 | TRUE | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityFireability-03 | TRUE | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-CTLCardinality-00 | FALSE | FALSE | FALSE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-CTLCardinality-01 | TRUE | TRUE | TRUE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-CTLCardinality-02 | FALSE | FALSE | FALSE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-CTLCardinality-03 | FALSE | FALSE | FALSE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-CTLFireability-00 | FALSE | FALSE | FALSE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-CTLFireability-01 | TRUE | TRUE | TRUE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-CTLFireability-02 | TRUE | TRUE | TRUE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-CTLFireability-03 | FALSE | FALSE | FALSE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-LTLCardinality-00 | FALSE | FALSE | FALSE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-LTLCardinality-01 | FALSE | FALSE | FALSE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-LTLCardinality-02 | FALSE | FALSE | FALSE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-LTLCardinality-03 | FALSE | FALSE | FALSE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-LTLFireability-00 | TRUE | TRUE | TRUE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-LTLFireability-01 | FALSE | FALSE | FALSE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-LTLFireability-02 | TRUE | TRUE | TRUE | UNKNOWN |  |
| TwoPhaseLocking-PT-nC00004vN-LTLFireability-03 | TRUE | TRUE | TRUE | UNKNOWN |  |
