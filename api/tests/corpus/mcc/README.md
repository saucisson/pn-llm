# Contest corpus used as test fixtures

Two instances of the Model Checking Contest 2026 inputs (<https://mcc.lip6.fr/2026/>), kept
unchanged except that each formula file holds only its first four properties:

| Directory | Model | Type |
|---|---|---|
| `TwoPhaseLocking-PT-nC00004vN` | TwoPhaseLocking | P/T |
| `PGCD-COL-D04N050` | PGCD | colored |

The models belong to their authors, named in the model forms published by the contest
(`https://mcc.lip6.fr/2026/pdf/<Family>-form.pdf`) with their licence; they are redistributed here
only as fixtures for round-trip tests. Larger corpora are downloaded by `python -m app.seed` and
never committed.
