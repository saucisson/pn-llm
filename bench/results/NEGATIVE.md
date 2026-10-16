# Negative and null results

## Learned selection from net size alone (feature set "1")

- **Question**: does a decision tree per (engine, examination) on log sizes of the net pick a
  better engine than always using the best one?
- **Setup**: split `v1`, development folds only, grouped by family; 20,514 questions; depths,
  leaf sizes and margins varied (`python -m app.train_predictor`).
- **Result**: selector 19,722 solved (PAR-2 1137 s), single best 19,713 (1138 s), virtual best
  20,008 (759 s). The selector is not meaningfully better than the single best engine.
- **Not done**: the test families were not used. Cost-based picking (leaf mean time) was tried
  and was worse than the probability pick.
- **Details**: `docs/predictor.md`.
