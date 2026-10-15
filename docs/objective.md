# Objective

## Problem
Users of Petri net tools often do not know **what to prove** about their model. Verification
tools answer precisely but only questions that someone has formulated. The MCC shows that tools
are strong; formulating relevant properties remains a human bottleneck.

## Objective
Show whether an LLM, given a Petri net, optionally a description in the user's words, and
static-analysis facts, can **propose properties worth checking**, formalize them correctly, and
get them **verified by existing tools**, in a conversation where the user sees the work and can be
questioned. The LLM generates hypotheses; the tools arbitrate (`CLAUDE.md`).

"Worth checking" is made operational in `docs/evaluation.md`: a property is worth checking when it
is meaningful (not vacuous, not trivially implied), faithful (the formula means what it is said to
mean), and useful (it helps find a fault or build confidence that an expert would want).

## Claims to test
Each claim is a hypothesis that the evaluation may refute. They are listed by priority.

| # | Claim | Status |
|---|---|---|
| C1 | **Soundness**: the system never reports a verdict that no engine produced, and never turns UNKNOWN, TIMEOUT, OOM or ERROR into a verdict. | Must hold; any violation is a defect, not a result. |
| C2 | **Fidelity**: the formulas sent to the engines mean what the assistant says they mean. | Primary risk of the approach. |
| C3 | **Usefulness**: LLM-proposed properties find more injected faults and cover more of the model than a rule-based generator with the same budget. | Primary research claim. |
| C4 | **Context helps**: static-analysis facts and the user's description improve C3, beyond what place and transition names alone provide. | Ablation. |
| C5 | **Workflow**: in the chat, users reach a first useful verified property faster, and read verdicts correctly (UNKNOWN is not FALSE). | Small user study. |
| C6 | **Tool selection** (separate track): a selector based on static features beats a fixed tool choice. | Secondary, `M5`. |

## Success of the prototype
The prototype is considered successful when, on the frozen test set and with the thresholds of
`docs/evaluation.md`:

- C1 holds without exception (zero unsupported verdicts);
- C2 reaches the fidelity threshold on the audited sample;
- C3 shows a clear gain over the rule-based baseline, with uncertainty computed over model families;
- C4 and C5 are reported honestly, whatever their outcome.

A **negative result is a valid outcome** and is recorded (for example "the LLM adds nothing over
rules once structural facts are given"). The evaluation is designed so that such a result is
visible and not hidden by choices made after seeing the data.

## Not goals
- Proving anything by LLM reasoning, or replacing model checkers.
- Beating tools on speed or scalability (that is the MCC's question).
- General natural-language to temporal-logic translation outside Petri nets.
- Colored nets and graph display in the first study (M3 and M9 come later).
