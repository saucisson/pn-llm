r"""Text syntax of formulas: a parser producing the tree and a printer that reads back the same.

Grammar, from the loosest to the tightest binding::

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

An ``id`` is the id of a place or transition in the net: bare when it uses letters, digits and
``_ . : # $ / -``, otherwise (or when it is a keyword or all digits) in double quotes with ``\\``
and ``\\"`` escapes. ``is-fireable(t1, t2)`` is the MCC form of ``enabled(t1) || enabled(t2)``.
"""

from __future__ import annotations

import re

from .errors import FormulaSyntaxError
from .formula import (
    And,
    Compare,
    Comparison,
    Constant,
    CtlUnary,
    CtlUntil,
    Deadlock,
    Enabled,
    Expression,
    Formula,
    Implies,
    Logic,
    LtlUnary,
    LtlUntil,
    Not,
    Or,
    Origin,
    Term,
    TokenCount,
    Tokens,
    Truth,
    subexpressions,
)
from .models import DomainModel

KEYWORDS = frozenset(
    {"G", "F", "X", "U", "AG", "AF", "AX", "EG", "EF", "EX", "A", "E", "true", "false"}
    | {"deadlock", "fireable", "enabled", "is-fireable"}
)
LTL_PREFIX = frozenset({"G", "F", "X"})
CTL_PREFIX = frozenset({"AG", "AF", "AX", "EG", "EF", "EX"})
FIREABLE_NAMES = frozenset({"fireable", "enabled", "is-fireable"})
COMPARISONS = frozenset({"<", "<=", "=", "==", "!=", ">=", ">"})

TOKEN = re.compile(
    r"""\s*(?:
    (?P<STRING>"(?:[^"\\]|\\.)*")
  | (?P<OP>->|<=|>=|==|!=|&&|\|\||[<>=!&|()\[\],+])
  | (?P<WORD>[A-Za-z0-9_.:#$/]+(?:-(?!>)[A-Za-z0-9_.:#$/]+)*)
    )""",
    re.VERBOSE,
)


class Token(DomainModel):
    """A lexical token: its kind, its value (unquoted for strings) and its offset."""

    kind: str  # STRING, OP, WORD or END
    value: str
    position: int


def tokenize(*, text: str) -> tuple[Token, ...]:
    """Split ``text`` into tokens, ending with an END token.

    Raises:
        FormulaSyntaxError: on a character that starts no token.
    """
    tokens: list[Token] = []
    position = 0
    while position < len(text):
        if text[position:].strip() == "":
            break
        match = TOKEN.match(text, position)
        if match is None:
            raise FormulaSyntaxError(
                f"unexpected character {text[position:].lstrip()[0]!r}",
                position=len(text) - len(text[position:].lstrip()),
            )
        kind = match.lastgroup or "OP"
        value = match.group(kind)
        start = match.start(kind)
        if kind == "STRING":
            value = re.sub(r"\\(.)", r"\1", value[1:-1])
        tokens.append(Token(kind=kind, value=value, position=start))
        position = match.end()
    tokens.append(Token(kind="END", value="", position=len(text)))
    return tuple(tokens)


class Parser:
    """Recursive-descent parser over a token list."""

    def __init__(self, *, text: str) -> None:
        """Tokenize ``text`` and start at its first token."""
        self._tokens = tokenize(text=text)
        self._index = 0

    def peek(self) -> Token:
        """Return the current token without consuming it."""
        return self._tokens[self._index]

    def take(self) -> Token:
        """Consume and return the current token."""
        token = self._tokens[self._index]
        self._index += 1
        return token

    def is_op(self, *, values: tuple[str, ...]) -> bool:
        """Tell whether the current token is one of these operators."""
        token = self.peek()
        return token.kind == "OP" and token.value in values

    def is_word(self, *, values: frozenset[str]) -> bool:
        """Tell whether the current token is one of these bare keywords."""
        token = self.peek()
        return token.kind == "WORD" and token.value in values

    def expect_op(self, *, value: str) -> None:
        """Consume the operator ``value`` or fail."""
        token = self.peek()
        if token.kind != "OP" or token.value != value:
            raise FormulaSyntaxError(f"expected {value!r}", position=token.position)
        self.take()

    def parse_all(self) -> Expression:
        """Parse the whole text as one expression."""
        expression = self.expression(allow_until=True)
        token = self.peek()
        if token.kind != "END":
            raise FormulaSyntaxError(f"unexpected {token.value!r}", position=token.position)
        return expression

    def expression(self, *, allow_until: bool) -> Expression:
        """Parse an implication."""
        left = self.disjunction(allow_until=allow_until)
        if self.is_op(values=("->",)):
            self.take()
            return Implies(left=left, right=self.expression(allow_until=allow_until))
        return left

    def disjunction(self, *, allow_until: bool) -> Expression:
        """Parse operands separated by ``||``."""
        operands = [self.conjunction(allow_until=allow_until)]
        while self.is_op(values=("||", "|")):
            self.take()
            operands.append(self.conjunction(allow_until=allow_until))
        return operands[0] if len(operands) == 1 else Or(args=tuple(operands))

    def conjunction(self, *, allow_until: bool) -> Expression:
        """Parse operands separated by ``&&``."""
        operands = [self.until(allow_until=allow_until)]
        while self.is_op(values=("&&", "&")):
            self.take()
            operands.append(self.until(allow_until=allow_until))
        return operands[0] if len(operands) == 1 else And(args=tuple(operands))

    def until(self, *, allow_until: bool) -> Expression:
        """Parse an LTL until, unless the context reserves ``U`` for a CTL bracket."""
        left = self.unary()
        if allow_until and self.is_word(values=frozenset({"U"})):
            self.take()
            return LtlUntil(left=left, right=self.unary())
        return left

    def unary(self) -> Expression:
        """Parse a negation, a temporal operator applied to an operand, or an atom."""
        token = self.peek()
        if token.kind == "OP" and token.value == "!":
            self.take()
            return Not(arg=self.unary())
        if token.kind == "WORD" and token.value in LTL_PREFIX:
            self.take()
            return LtlUnary(op=token.value, arg=self.unary())
        if token.kind == "WORD" and token.value in CTL_PREFIX:
            self.take()
            return CtlUnary(op=token.value, arg=self.unary())
        return self.atom()

    def atom(self) -> Expression:
        """Parse a parenthesized expression, a CTL until, a keyword atom or a comparison."""
        token = self.peek()
        if token.kind == "OP" and token.value == "(":
            self.take()
            inner = self.expression(allow_until=True)
            self.expect_op(value=")")
            return inner
        if token.kind == "WORD" and token.value in {"A", "E"}:
            self.take()
            self.expect_op(value="[")
            first = self.expression(allow_until=False)
            until = self.peek()
            if until.kind != "WORD" or until.value != "U":
                raise FormulaSyntaxError("expected 'U'", position=until.position)
            self.take()
            second = self.expression(allow_until=False)
            self.expect_op(value="]")
            return CtlUntil(op="AU" if token.value == "A" else "EU", left=first, right=second)
        return self.simple_atom()

    def simple_atom(self) -> Expression:
        """Parse a constant, ``deadlock``, a fireability atom or a comparison."""
        token = self.peek()
        if token.kind == "WORD" and token.value in {"true", "false"}:
            self.take()
            return Truth(value=token.value == "true")
        if token.kind == "WORD" and token.value == "deadlock":
            self.take()
            return Deadlock()
        if token.kind == "WORD" and token.value in FIREABLE_NAMES:
            self.take()
            return self.fireable()
        left = self.term()
        comparison = self.peek()
        if comparison.kind != "OP" or comparison.value not in COMPARISONS:
            raise FormulaSyntaxError("expected a comparison", position=comparison.position)
        self.take()
        right = self.term()
        cmp: Comparison = "==" if comparison.value == "=" else comparison.value  # type: ignore[assignment]  # checked against COMPARISONS
        if isinstance(left, TokenCount) and len(left.places) == 1 and isinstance(right, Constant):
            return Tokens(place=left.places[0], cmp=cmp, value=right.value)
        return Compare(left=left, cmp=cmp, right=right)

    def fireable(self) -> Expression:
        """Parse the argument list of ``fireable(...)``: several transitions mean any of them."""
        self.expect_op(value="(")
        transitions = [self.identifier()]
        while self.is_op(values=(",",)):
            self.take()
            transitions.append(self.identifier())
        self.expect_op(value=")")
        atoms = tuple(Enabled(transition=name) for name in transitions)
        return atoms[0] if len(atoms) == 1 else Or(args=atoms)

    def identifier(self) -> str:
        """Parse an element id: a bare word that is not a keyword, or a quoted string."""
        token = self.peek()
        if token.kind == "STRING" or (
            token.kind == "WORD" and token.value not in KEYWORDS and not token.value.isdigit()
        ):
            self.take()
            return token.value
        raise FormulaSyntaxError("expected an element id", position=token.position)

    def term(self) -> Term:
        """Parse an integer or a sum of places."""
        token = self.peek()
        if token.kind == "WORD" and token.value.isdigit():
            self.take()
            return Constant(value=int(token.value))
        places = [self.identifier()]
        while self.is_op(values=("+",)):
            self.take()
            places.append(self.identifier())
        return TokenCount(places=tuple(places))


def parse_expression(*, text: str) -> Expression:
    """Parse formula text into a syntax tree.

    Raises:
        FormulaSyntaxError: if the text is not a formula; ``position`` locates the fault.
    """
    return Parser(text=text).parse_all()


PRECEDENCE_IMPLIES = 1
PRECEDENCE_OR = 2
PRECEDENCE_AND = 3
PRECEDENCE_UNTIL = 4
PRECEDENCE_PREFIX = 5
PRECEDENCE_ATOM = 6


def quote_id(*, name: str) -> str:
    """Write an element id so that the parser reads it back: bare when safe, else quoted."""
    if (
        name
        and name not in KEYWORDS
        and not name.isdigit()
        and TOKEN.fullmatch(name) is not None
        and TOKEN.fullmatch(name).lastgroup == "WORD"  # type: ignore[union-attr]  # checked just above
    ):
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_term(*, term: Term) -> str:
    """Write a term."""
    if isinstance(term, Constant):
        return str(term.value)
    return " + ".join(quote_id(name=place) for place in term.places)


def precedence_of(*, expression: Expression) -> int:
    """Return how tightly an expression binds when printed."""
    match expression:
        case Implies():
            return PRECEDENCE_IMPLIES
        case Or():
            return PRECEDENCE_OR
        case And():
            return PRECEDENCE_AND
        case LtlUntil() | Tokens() | Compare():
            return PRECEDENCE_UNTIL  # a comparison is wrapped when it is an operand
        case Not() | LtlUnary() | CtlUnary():
            return PRECEDENCE_PREFIX
        case _:
            return PRECEDENCE_ATOM


def render_text(*, expression: Expression, minimum: int = 0) -> str:
    """Write a tree as text; operands that bind more loosely than ``minimum`` get parentheses.

    ``parse_expression(text=render_text(expression=e))`` gives back ``e``.
    """
    text = render_unparenthesized(expression=expression)
    return f"({text})" if precedence_of(expression=expression) < minimum else text


def render_unparenthesized(*, expression: Expression) -> str:  # noqa: PLR0911 - one return per operator
    """Write a tree without outer parentheses."""
    if isinstance(expression, Tokens):
        return f"{quote_id(name=expression.place)} {expression.cmp} {expression.value}"
    if isinstance(expression, Compare):
        left = render_term(term=expression.left)
        return f"{left} {expression.cmp} {render_term(term=expression.right)}"
    if isinstance(expression, Enabled):
        return f"fireable({quote_id(name=expression.transition)})"
    if isinstance(expression, Deadlock):
        return "deadlock"
    if isinstance(expression, Truth):
        return "true" if expression.value else "false"
    if isinstance(expression, Not):
        return "!" + render_text(expression=expression.arg, minimum=PRECEDENCE_ATOM)
    if isinstance(expression, LtlUnary | CtlUnary):
        operand = render_text(expression=expression.arg, minimum=PRECEDENCE_PREFIX + 1)
        if isinstance(expression.arg, LtlUnary | CtlUnary | Not):
            operand = render_text(expression=expression.arg, minimum=PRECEDENCE_PREFIX)
        return f"{expression.op} {operand}"
    if isinstance(expression, And):
        return " && ".join(
            render_text(expression=arg, minimum=PRECEDENCE_AND + 1) for arg in expression.args
        )
    if isinstance(expression, Or):
        return " || ".join(
            render_text(expression=arg, minimum=PRECEDENCE_OR + 1) for arg in expression.args
        )
    if isinstance(expression, Implies):
        left = render_text(expression=expression.left, minimum=PRECEDENCE_IMPLIES + 1)
        return f"{left} -> {render_text(expression=expression.right, minimum=PRECEDENCE_IMPLIES)}"
    if isinstance(expression, LtlUntil):
        left = render_text(expression=expression.left, minimum=PRECEDENCE_PREFIX)
        return f"{left} U {render_text(expression=expression.right, minimum=PRECEDENCE_PREFIX)}"
    # Inside the brackets the parser reads U as the separator, so an operand that holds an LTL
    # until must be parenthesized.
    quantifier = expression.op[0]
    operands = []
    for member in (expression.left, expression.right):
        written = render_text(expression=member)
        holds_until = any(
            isinstance(located.expression, LtlUntil)
            for located in subexpressions(expression=member, path="")
        )
        operands.append(f"({written})" if holds_until else written)
    return f"{quantifier}[{operands[0]} U {operands[1]}]"


def formula_from_text(
    *, text: str, formula_id: str, logic: Logic | None, gloss: str, origin: Origin
) -> Formula:
    """Parse text into a formula; without ``logic`` it follows from the operators used.

    Raises:
        FormulaSyntaxError: if the text is not a formula or mixes LTL and CTL operators.
    """
    expression = parse_expression(text=text)
    operators = {
        located.expression.op
        for located in subexpressions(expression=expression, path="")
        if isinstance(located.expression, LtlUnary | LtlUntil | CtlUnary | CtlUntil)
    }
    has_ltl = bool(operators & {"G", "F", "X", "U"})
    has_ctl = bool(operators - {"G", "F", "X", "U"})
    if has_ltl and has_ctl and logic is None:
        raise FormulaSyntaxError("the formula mixes LTL and CTL operators", position=0)
    chosen: Logic = logic or ("ctl" if has_ctl else "ltl" if has_ltl else "state")
    return Formula(id=formula_id, logic=chosen, ast=expression, gloss=gloss, origin=origin)
