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
