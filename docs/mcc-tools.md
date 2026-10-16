# MCC tools

Tools that took part in the **Model Checking Contest 2026**, as listed on the contest results page
(<https://mcc.lip6.fr/2026/results.php>). Each one has an integration issue in the backlog.

| Tool | Author / institution (as listed) | Examination categories entered | Colored nets |
|---|---|---|---|
| ITS-Tools | Y. Thierry-Mieg, LIP6 | all | yes |
| Tapaal | J. Srba, Aalborg University | GlobalProperties, UpperBounds, ReachabilityFormulas, CTL, LTL | yes |
| TY | A. Yates, Ferrite Technology | StateSpace, GlobalProperties, UpperBounds, ReachabilityFormulas, CTL, LTL | yes |
| smpt | N. Amat, ONERA | ReachabilityCardinality, ReachabilityFireability | yes (not in our image) |
| tedd | B. Berthomieu, LAAS-CNRS | StateSpace | yes |
| petrivet | M. Dyer, TU Munich | StateSpace, GlobalProperties | P/T only |

The results page also evaluates two non-submitted entries (a composite of the 2025 gold medals and
a virtual reference tool); they are not integration targets.

Historical participants (LoLA, LTSmin, Marcie, GreatSPN, Smart, Sift, ...) are tracked in separate,
lower-priority issues: confirm that each is still maintained and redistributable before integrating.

## Examination categories used in this project

StateSpace, GlobalProperties (e.g. deadlock, liveness, safety), UpperBounds, Reachability
(cardinality and fireability variants), CTL (cardinality / fireability), LTL (cardinality /
fireability). "Equivalent tools" for a property means tools entered in the same category, with the
same semantics for the formula class (see the tool-selection issues).

*Information above comes from the contest web site at the time of writing; re-check it each year.*
