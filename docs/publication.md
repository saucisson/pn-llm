# Publication targets: Petri Nets conference

## Petri Nets 2027 (Rennes)
International Conference on Application and Theory of Petri Nets and Concurrency, Rennes,
Faculty of Economics, **21 to 25 June 2027** (tutorials 21 and 22 June). Sources:
`https://petrinets2027.inria.fr/` (call for papers and important dates pages, read on
2026-10-15). Springer LNCS format with line numbers, EasyChair submission.

| Date | Event |
|---|---|
| 15 January 2027 | Abstract submission |
| 22 January 2027 | Paper submission |
| March 2027 | Registration opens |
| 21 to 25 June 2027 | Conference |
| to be announced | Workshops, **Model Checking Contest** |

The notification and camera-ready dates and the time-zone convention (the 2026 edition used
Anywhere on Earth) are not published yet. As of 2026-10-15 the abstract deadline is about 13 weeks
away and the paper deadline about 14 weeks.

### Categories
| Category | Limit | Scope |
|---|---|---|
| Regular paper | 20 pages excluding references | Original results advancing Petri net theory or concurrent systems, results extending the applicability of Petri nets, or case studies and experience reports on practical use. |
| Tool paper | 10 pages excluding references | Description of a Petri-net-based computer tool, not mainly an application of it or its underlying theory. The tool must be usable by other groups (not necessarily free); the submission must say how reviewers get it, and that access **must be free**. Accepted tools are demonstrated at the Tool Exhibition. |

No other submission type is listed (no short papers). **Not stated** in the 2027 call (*to check*,
possibly in the EasyChair page): review mode (single or double blind), policy on LLM use,
artifact or reproducibility rules, simultaneous submission.

### Topics that match this project
Verification and model checking with nets; computer tools for nets; analysis of nets;
higher-level nets (later, colored nets); experience reports on applying nets; model checking and
verification of distributed systems. The Model Checking Contest is announced for the same event
(dates to be announced): a venue for the engines we wrap, not for this work itself.

## ACSD (to check)
ACSD, the International Conference on Application of Concurrency to System Design, has been
held together with Petri Nets in several years (for example 2014 and 2019, according to those
editions' web sites). **No page for a 2026 or 2027 edition was found**, so nothing is assumed here:
whether ACSD takes place in 2027, where, when, its deadline, its paper types and page limits, its
publisher and whether it accepts tool or short papers are all *to check*. Its scope (applying
concurrency theory to system design, hence verification and design aids) fits papers A, D and E
better than a pure theory venue; the choice between Petri Nets and ACSD for each paper is made once
both calls are known. The same work must not be submitted to both (overlap rules *to check*).

## Candidate papers
Claims C1 to C6 are defined in `docs/objective.md`; measures and thresholds in
`docs/evaluation.md`.

| Id | Paper | Category | Objective | Evidence required | Claims |
|---|---|---|---|---|---|
| A | The platform: REST API, MCC engines in containers, verified chat | Tool | Describe a tool others can use; demonstrate it | Working, documented, free reviewer access; soundness guarantees; short demonstration scenario | C1, part of C5 |
| B | LLM-proposed properties versus a rule-based generator | Regular | Show whether an LLM adds value, and from which context (analysis, description, names) | Frozen protocol, baseline B0, ablations, mutation and fault finding, family-level statistics | C3, C4 |
| C | Faithful formalization of properties by an LLM | Regular | Measure whether formulas mean what is claimed; give an error taxonomy and a dataset | Translation benchmark, blind raters with agreement, engines as judge | C2 |
| D | Experience report on real models | Regular (case study / experience) | Report what happened on real nets: faults found, useful and useless properties, lessons | Real cases, including the authors' own unpublished models; honest qualitative analysis | C5, part of C3 |
| E | Integrating the MCC tools behind one API | Regular (experience) | Report on heterogeneity: syntaxes, verdict semantics, disagreements between tools | Real disagreement cases, with root causes | C1 |
| F | Tool selection from static features | Regular | Show a selector beats a fixed choice | Regret against single best and virtual best tool, cross-validation by family | C6 |

Objectives differ and so does the bar. A is judged on availability and clarity, B on statistical
credibility, C on rigorous measurement of a narrow question, D on honesty and insight, E on
concrete findings, F on benchmark quality.

## What each paper needs from the code base
- **A (tool)**: free access for reviewers, with no paid LLM key required. The design allows it:
  *replay mode* (serving recorded sessions from event logs, ADR 0008) and the scripted fake LLM
  (ADR 0009). Also a one-command installation (`docker compose`), versioned documentation, an
  open-source licence, a stable demonstration scenario, and the soundness audit (M1).
- **B and C**: the experiment runner, B0, mutation pipeline, dataset freeze (milestone M6).
- **D**: sessions kept as event logs; consent and retention for data that is not ours (ADR 0011).
- **E**: logging of every disagreement between equivalent tools (already a domain rule).
- **F**: the tool-selection milestone (M5).

## Suggested order
1. **A** first: smallest scope, needs M1 and the text chat (M8), plus replay mode and the
   reviewer-access plan.
2. **C** next: narrow, reuses part of the evaluation infrastructure.
3. **B** as the main result: needs the full frozen protocol; do not rush it.
4. **D**, **E**, **F** as the corresponding material matures; D and E can feed A and B.

Splitting results across papers must be honest: no salami-slicing of one study, and each paper
states what it reuses from the others. Check the venue's rules on overlap with prior submissions.

## Writing rules
- Claims in a paper must be among those defined in `docs/objective.md`, with the thresholds of
  the frozen protocol; deviations are stated.
- Negative results from `bench/results/NEGATIVE.md` are reported where relevant.
- Use of LLMs in the work is described precisely: model identifier, prompts, budgets. Check the
  venue's policy on LLM use in writing (*to check*).
