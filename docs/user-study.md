# User study protocol (M10)

A small study of the chat workflow: do people reach a first useful verified property faster, and
read verdicts correctly? **Descriptive only**: with a handful of participants nothing is
generalized (`docs/evaluation.md`, threats to validity). Claim C5 of `docs/objective.md`.

## Participants and tasks
- 6 to 12 people who know Petri nets or model checking at least at a basic level; their level is
  asked and reported, not used to select.
- Each takes two tasks on two nets they have not seen, in randomized order and counterbalanced:
  - **with the assistant** (the chat, text only): given the net and a one-paragraph description,
    produce verified properties worth keeping;
  - **without** (an engine's own interface or the REST API with a command-line client, same
    engines, same time): the same kind of task.
- Nets: two per participant from a pool of small and medium P/T nets of the dev families,
  unpublished ones included. 30 minutes per task; the clock stops at the participant's call.
- The session starts with the same goal text as the tasks; the participant may answer the
  assistant's questions: that is the interaction being studied.

## Measures
| Measure | Source |
|---|---|
| Time to the first *useful* verified property | the log gives the time of each definitive verdict (`python -m app.study`); the participant marks which properties they find useful, at the end, without seeing the condition's name |
| Properties proposed, questions asked by the assistant, verdicts by kind | session log (`python -m app.study`) |
| Share of the verified properties judged useful | participant |
| **Correct reading of UNKNOWN and TIMEOUT** | a short questionnaire after the task: for 4 verdict screenshots (TRUE, FALSE, UNKNOWN, TIMEOUT) the participant says what they tell about the property; answers are scored by two people from a written key (UNKNOWN and TIMEOUT: the engine did not decide, nothing is known) |
| Experience | 5-point scale on trust, effort, and what was missing; free text |

The log is the platform's own event log (ADR 0008): nothing is added to the product for the study.

## Consent and data handling
- Written consent before the task, saying what is recorded (the session events, the questionnaire,
  free text), why, who reads it, and that the participant may stop and have their data deleted at
  any time. Participation is not tied to any evaluation of the person.
- Participants are identified by a code (P01...); the table linking codes to names is kept apart
  from the data and destroyed at the end of the study.
- Nets and descriptions from participants stay confidential: stored only on the study database,
  never sent to a model other than the one configured for the study, and deleted with their
  sessions (`DELETE /v1/sessions/{id}`, retention rules of ADR 0011 and `docs/architecture.md`)
  once the analysis is done. Published results contain aggregates and short anonymized quotes only.
- The assistant sends the net's inspection answers and the description to the configured model
  provider: participants are told which provider and that it receives them.

## Analysis and reporting
- Per participant, then summarized: medians and ranges for times, counts and shares; the
  questionnaire as the proportion of correct readings per verdict kind.
- Paired comparison with/without per participant, reported as individual differences, with no
  significance test and no claim beyond the sample.
- Anything unexpected (a participant misled by a verdict, a failure of the platform, a session
  restarted) is listed in the report with its session id. Negative results go to
  `bench/results/NEGATIVE.md`.
