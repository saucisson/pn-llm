# Formula text syntax

The text form of formulas, for users and for imports (the MCC). The platform parses it into the
formula tree of `docs/json-contract.md`; the LLM and the adapters work with the tree.
`app/domain/formula_text.py` is the reference; printing a tree and parsing it back gives the same
tree.

```
expr    := or ('->' expr)?                       implication, right associative
or      := and (('||' | '|') and)*
and     := until (('&&' | '&') until)*
until   := unary ('U' unary)?                    LTL until
unary   := '!' unary | TEMPORAL unary | atom
TEMPORAL:= G F X AG AF AX EG EF EX
atom    := '(' expr ')' | ('A' | 'E') '[' expr 'U' expr ']'
         | 'true' | 'false' | 'deadlock'
         | ('fireable' | 'enabled' | 'is-fireable') '(' id (',' id)* ')'
         | term CMP term
term    := INT | id ('+' id)*
CMP     := '<' '<=' '=' '==' '!=' '>=' '>'
```

- An `id` is the id of a place or transition, as in the net. It is bare when made of letters,
  digits and `_ . : # $ / -`, and neither a keyword nor only digits; otherwise it is in double
  quotes with `\\` and `\"` as escapes. Names are not accepted: only ids.
- `p >= 1` is a **cardinality** atom (`tokens`); `p1 + p2 <= p3` and `3 < p` are `compare`
  atoms. `fireable(t)` is a **fireability** atom (`enabled`); several transitions mean any of them
  (the MCC `is-fireable(t1, t2)`).
- The logic follows from the operators: `G F X U` give LTL, the `A` and `E` operators give CTL,
  none gives a state formula (reachability: some reachable marking satisfies it). Mixing LTL and
  CTL operators is an error. A logic can also be given, and the operators are checked against it.
- Errors carry the offset of the fault in the text.

## Patterns
`POST /v1/formulas/from-pattern` (`GET /v1/formulas/patterns` lists them) builds the formula of a
specification pattern and checks it on the net, so that common questions do not depend on the
operators being written right. Conditions `p`, `q` are state formulas in the syntax above; `logic` is
`ctl` (default) or `ltl`.

| Pattern | CTL | LTL |
|---|---|---|
| `absence` (p never holds) | `AG !p` | `G !p` |
| `universality` (p always holds) | `AG p` | `G p` |
| `existence` | `EF p` (some run) | `F p` (every run) |
| `bound` (p is a comparison on one place, `k`) | `AG (place <= k)` | `G (place <= k)` |
| `response` (p, then q) | `AG (p -> AF q)` | `G (p -> F q)` |
| `precedence` (p only after q) | `!E[!q U (p && !q)]` | `(!p U q) || G !p` |
| `exclusion` | `AG !(p && q)` | `G !(p && q)` |
| `recurrence` | `AG AF p` | `G F p` |

Formulas built this way have origin `template`. After Dwyer, Avrunin and Corbett (1999), global scope.

## Trivial properties
A property that the structure of the net already decides says nothing about its behaviour: `AG (p <= 1)`
when a P-invariant bounds `p` by 1, a condition on a place that can never hold that many tokens, an
implication whose premise is impossible, a fireability atom on a dead transition. The agent's
`check_formulas` still checks such a property but lists it under `trivial`, with the reason and where
in the formula (`holds_in_every_state`, `holds_in_no_state`, `vacuous_antecedent`), so it is not mistaken
for a finding. The reasons are proofs from bounds, P-invariants and dead transitions, never guesses.
