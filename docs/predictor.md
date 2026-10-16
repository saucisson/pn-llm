# Learned engine selection

The selector (`POST /v1/select-tools`, `basis: "predictor"`) can rank the engines by a small model
trained on the contest's published results. This page says what the model is, how it is trained
and judged, and what it achieved.

## The model

- **Features** (`domain/predictor.py`, `FEATURE_SET = "1"`): log10 of the places, transitions and
  arcs of the net, and whether it is colored. Sizes of contest instances come from the
  `model.pnml` files (`python -m app.seed --sizes`).
- **One decision tree per (engine, examination)**, grown by CART with the Gini criterion. A leaf
  keeps the share of runs that answered, the number of runs and the mean log time of the answered
  ones. The tree predicts the *chance of an answer*; a timeout, a memory failure or an error counts
  as "no answer", never as a verdict.
- **Only engines that answered at least once** in an examination get a tree there: the results
  hold rows for tools that did not enter an examination.
- **Choice rule** (`pick`): the engine with the highest chance, but the default engine (the best on
  average) is kept unless another one is better by more than `margin`.
- The model is a JSON file (`PNVERIF_PREDICTOR_PATH`); without it the selector ranks by contest
  history. It records its feature set and what it was trained on.

## Training and judging

```bash
python -m app.seed --sizes            # instance sizes
python -m app.train_predictor --split v1 --out predictor.json
```

Training reads the **development families of a frozen split only**; the margin is picked by
family-grouped cross-validation on those folds, and the test families are never read
(`docs/evaluation.md`). The report compares the selector with the single best engine and with the
virtual best (an oracle choosing per question), by solved questions and PAR-2 (a miss costs twice
the 3,600 s timeout).

## Result (negative)

On the development folds of split `v1` (20,514 questions with at least two engines):

| | solved | PAR-2 (s) |
|---|---|---|
| single best engine | 19,713 | 1138 |
| selector | 19,722 | 1137 |
| virtual best | 20,008 | 759 |

No depth, leaf size or margin tried beats the single best engine meaningfully (+10 questions at
best). Network size alone does not tell which engine will answer: the gap to the oracle is real
but these features do not close it. The finding is logged in `bench/results/NEGATIVE.md`. The test
families have not been used; a richer feature set (structure: bounds, invariants, formula size)
is the next thing to try, and must bump `FEATURE_SET`.
