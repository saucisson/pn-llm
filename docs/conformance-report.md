# Conformance report

Cross-engine conformance on `api/tests/corpus/conformance.json` (suite: `docs/engines.md`,
`app/conformance.py`). Run on 2026-10-15 with `--timeout 120 --memory 2048`, engines tapaal 4.4.2
and itstools 1.0.0.202609112134. A cell is the engine's verdict; `!` after it would mark a wrong
answer, and the last column would say `yes` for a row to triage (a wrong answer, or two engines
contradicting each other).

Result: 51 cases, 0 wrong answers, 0 contradictions. Four rows hold a TIMEOUT: three for itstools
and one for tapaal, on the colored instance, within the 120 s of this run; none is a disagreement.
The cases are the seven by hand and the contest's reference answers (see
`api/tests/corpus/mcc/README.md`); a timeout is not an answer and is not counted against an
engine here.

| case | expected | itstools | tapaal | triage |
|---|---|---|---|---|
| mutex-reach-true | TRUE | TRUE | TRUE |  |
| mutex-reach-false | FALSE | FALSE | FALSE |  |
| mutex-ctl-true | TRUE | TRUE | TRUE |  |
| mutex-ctl-false | FALSE | FALSE | FALSE |  |
| mutex-ltl-true | TRUE | TRUE | TRUE |  |
| mutex-ltl-false | FALSE | FALSE | FALSE |  |
| mutex-no-deadlock | FALSE | FALSE | FALSE |  |
| PGCD-COL-D04N050-ReachabilityCardinality-00 | TRUE | TRUE | TRUE |  |
| PGCD-COL-D04N050-ReachabilityCardinality-01 | FALSE | FALSE | FALSE |  |
| PGCD-COL-D04N050-ReachabilityCardinality-02 | TRUE | TRUE | TRUE |  |
| PGCD-COL-D04N050-ReachabilityCardinality-03 | TRUE | TRUE | TRUE |  |
| PGCD-COL-D04N050-ReachabilityFireability-00 | FALSE | FALSE | FALSE |  |
| PGCD-COL-D04N050-ReachabilityFireability-01 | FALSE | FALSE | FALSE |  |
| PGCD-COL-D04N050-ReachabilityFireability-02 | TRUE | TRUE | TRUE |  |
| PGCD-COL-D04N050-ReachabilityFireability-03 | TRUE | TRUE | TRUE |  |
| PGCD-COL-D04N050-CTLCardinality-00 | TRUE | TRUE | TRUE |  |
| PGCD-COL-D04N050-CTLCardinality-01 | FALSE | TIMEOUT | TIMEOUT |  |
| PGCD-COL-D04N050-CTLFireability-00 | TRUE | TRUE | TRUE |  |
| PGCD-COL-D04N050-CTLFireability-01 | TRUE | TIMEOUT | TRUE |  |
| PGCD-COL-D04N050-CTLFireability-02 | TRUE | TRUE | TRUE |  |
| PGCD-COL-D04N050-CTLFireability-03 | TRUE | TIMEOUT | TRUE |  |
| PGCD-COL-D04N050-LTLCardinality-00 | TRUE | TRUE | TRUE |  |
| PGCD-COL-D04N050-LTLCardinality-01 | FALSE | TIMEOUT | FALSE |  |
| PGCD-COL-D04N050-LTLCardinality-02 | FALSE | FALSE | FALSE |  |
| PGCD-COL-D04N050-LTLCardinality-03 | FALSE | FALSE | FALSE |  |
| PGCD-COL-D04N050-LTLFireability-00 | FALSE | FALSE | FALSE |  |
| PGCD-COL-D04N050-LTLFireability-01 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityCardinality-00 | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityCardinality-01 | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityCardinality-02 | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityCardinality-03 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityFireability-00 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityFireability-01 | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityFireability-02 | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-ReachabilityFireability-03 | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-CTLCardinality-00 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-CTLCardinality-01 | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-CTLCardinality-02 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-CTLCardinality-03 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-CTLFireability-00 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-CTLFireability-01 | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-CTLFireability-02 | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-CTLFireability-03 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-LTLCardinality-00 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-LTLCardinality-01 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-LTLCardinality-02 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-LTLCardinality-03 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-LTLFireability-00 | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-LTLFireability-01 | FALSE | FALSE | FALSE |  |
| TwoPhaseLocking-PT-nC00004vN-LTLFireability-02 | TRUE | TRUE | TRUE |  |
| TwoPhaseLocking-PT-nC00004vN-LTLFireability-03 | TRUE | TRUE | TRUE |  |
