# NLU calibration (T-21)

Rule parser on the 133 hand-labeled queries: intent accuracy 1.000, entity F1 1.000.

A parse counts as correct only if intent and every entity match. A calibrated score has
observed accuracy close to its confidence.

| confidence bin | queries | observed accuracy |
|---|---|---|
| 0.0-0.2 | 18 | 1.000 |
| 0.6-0.8 | 1 | 1.000 |
| 0.8-1.0 | 114 | 1.000 |

The 0.0-0.2 bin holds the out-of-scope queries, which get confidence 0 by design.
Caveat: the labeled set and the parser share one author and vocabulary, so these
numbers are optimistic for unseen phrasing. Held-out checks against the hosted model are in
docs/nlu-groq-prototype.md.
