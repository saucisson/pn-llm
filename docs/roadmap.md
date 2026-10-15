# Roadmap: order of the backlog

GitHub issue numbers follow creation order and cannot change. This page gives the order in which
to work. Milestone names keep their historical numbers (they are quoted in other documents);
their *sequence* is the order below, also written in each milestone description.
`scripts/create_issues.sh` holds the milestone of each issue and matches this page.

## Sequence of milestones

| # | Milestone | Why here |
|---|---|---|
| 1 | M1 Core API and first engine | Everything else builds on the net document, inspection and the engine path. |
| 2 | M2 MCC data and tool integrations | Corpus, formulas and at least two engines (conformance needs two). |
| 3 | M4 Static analysis and reductions | The chat facade (#129) needs analyses; reductions come last. |
| 4 | M8 Text chat workflow | Next workflow (CLAUDE.md). P/T nets first; colored nets are not yet supported by the agent. |
| 5 | M3 Colored nets | Extends nets, formulas, analyses and the LLM summary once the chat works on P/T. |
| 6 | M5 LLM agent and tool selection | Extends the agent of M8 (#95 builds on #130, #94 on #129); historical tools last. |
| 7 | M6 Evaluation | Needs the agent (M5/M8), the corpus (M2) and the analyses (M4). |
| 8 | M7 Exploration | Deferred: only on request. |
| 9 | M9 Graph display | Deferred. |
| 10 | M10 Publication | Paper A needs M1 and M8 and can start earlier; the others follow the frozen protocol (`docs/publication.md`). |

## Order inside each milestone

Issues in one group can be done in any order; groups are sequential.

**M1**
1. Contract: #16, #17
2. Net document: #9, #10, #11, #14, #13
3. Inspection: #18, #19, #20
4. Engine path: #7, #112, #8, #21, #23, #22
5. Jobs and storage: #6, #5, #28
6. Tooling: #25, #24, #26, #27, #29, #30, #31

**M2**
1. Corpus: #32, #33, #12, #15
2. Formulas, descriptions, results: #35, #34, #36, #37
3. First engines: #111, #39, #40
4. Conformance: #38
5. Other engines: #42, #41, #43, #44

**M4**
1. Runner and native engine: #61, #71
2. Analyses: #68, #62, #63, #64, #67, #65, #66, #69, #70, #72
3. Reductions: #73, then #74, #75, #76, #77, #78, #79 (needs #62), #80 (needs #67), #81, #82
4. Back to the original net: #83, #84

**M8**
1. Decisions and models: #124, #125, #126, #132
2. Storage and ports: #127, #128, #129
3. Agent: #130, #131, #133, #138, #140, #137
4. API: #134, #135, #136, #139
5. UI: #141, #142, #143, #144, #145
6. Report and docs: #146, #147

**M3**: #52, #53, #54, #55, #56, #57, #58, #59, #60

**M5**
1. Tool selection: #85, #86, #87, #88, #89, #90, #91, #92, #93
2. Agent: #94, #95, #96, #97
3. Historical tools: #45, #46, #47, #48, #49, #50, #51

**M6**: #98, #100, #99, #103, #102, #101, #105, #106, #104, #107, #108, #109, #110

**M7**: #113 first; the rest on demand.

**M9**: #148, #149.

**M10**: #150, then papers A (#151, #152), C (#153), B (#154), then D, E, F (#155, #156, #157).
