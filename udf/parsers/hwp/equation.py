"""HWP equation script to LaTeX converter.

Based on the Hancom spec "HWP Document File Structure - Equation rev 1.3".
HWP equations use a proprietary TeX-inspired syntax, converted via a
tokenizer -> recursive-descent parser -> AST -> LaTeX renderer pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

# ═══════════════════════════════════════════════════════════════════════
# AST 노드
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class EqNode:
    """Base AST node for HWP equation expressions."""

    pass


@dataclass
class EqText(EqNode):
    """Plain text node."""

    text: str


@dataclass
class EqGroup(EqNode):
    """Grouped sequence of child nodes."""

    children: list[EqNode] = field(default_factory=list)


@dataclass
class EqFrac(EqNode):
    """Fraction (numerator over denominator)."""

    numer: EqNode
    denom: EqNode
    has_line: bool = True


@dataclass
class EqScript(EqNode):
    """Superscript and/or subscript attached to a base."""

    base: EqNode
    sup: EqNode | None = None
    sub: EqNode | None = None


@dataclass
class EqLeftScript(EqNode):
    """Left-side superscript/subscript."""

    base: EqNode
    lsup: EqNode | None = None
    lsub: EqNode | None = None


@dataclass
class EqSqrt(EqNode):
    """Square root."""

    content: EqNode


@dataclass
class EqDeco(EqNode):
    """Decoration (hat, bar, tilde, etc.) over content."""

    kind: str
    content: EqNode


@dataclass
class EqFunc(EqNode):
    """Named function (sin, cos, log, etc.)."""

    name: str


@dataclass
class EqSymbol(EqNode):
    """Named symbol (Greek letters, operators, etc.)."""

    name: str


@dataclass
class EqDelimited(EqNode):
    """Content enclosed in left/right delimiters."""

    left: str
    right: str
    content: EqNode


@dataclass
class EqMatrix(EqNode):
    """Matrix with rows and columns."""

    rows: list[list[EqNode]] = field(default_factory=list)
    style: str = "plain"


@dataclass
class EqCases(EqNode):
    """Cases environment (piecewise definition)."""

    rows: list[EqNode] = field(default_factory=list)


@dataclass
class EqPile(EqNode):
    """Vertical stack of expressions."""

    rows: list[EqNode] = field(default_factory=list)
    align: str = "center"


@dataclass
class EqNewline(EqNode):
    """Explicit line break within an equation."""

    pass


@dataclass
class EqSpace(EqNode):
    """Explicit spacing."""

    size: str = "full"


@dataclass
class EqAlign(EqNode):
    """Alignment marker."""

    pass


@dataclass
class EqNot(EqNode):
    """Negation (strike-through) of content."""

    content: EqNode


@dataclass
class EqBigg(EqNode):
    """Enlarged delimiter/content."""

    content: EqNode


@dataclass
class EqColor(EqNode):
    """Color-annotated content."""

    r: int
    g: int
    b: int
    content: EqNode


@dataclass
class EqFont(EqNode):
    """Font-style-annotated content."""

    style: str
    content: EqNode


@dataclass
class EqScale(EqNode):
    """Scaled content."""

    factor: int
    content: EqNode


@dataclass
class EqChoose(EqNode):
    """Binomial coefficient (n choose k)."""

    n: EqNode
    k: EqNode


@dataclass
class EqRel(EqNode):
    """Relation with arrow between left and right."""

    left: EqNode
    right: EqNode
    arrow: str
    top: EqNode | None = None
    bottom: EqNode | None = None


@dataclass
class EqBigOp(EqNode):
    """Big operator (sum, product, integral, etc.)."""

    name: str


@dataclass
class EqLongdiv(EqNode):
    """Long division."""

    divisor: EqNode
    content: EqNode


# ═══════════════════════════════════════════════════════════════════════
# 기호 매핑 테이블 (스펙 §1.2.4 전체)
# ═══════════════════════════════════════════════════════════════════════

_GREEK_UPPER: dict[str, str] = {
    "Alpha": r"\Alpha", "Beta": r"\Beta", "Gamma": r"\Gamma",
    "Delta": r"\Delta", "Epsilon": r"\Epsilon", "Zeta": r"\Zeta",
    "Eta": r"\Eta", "Theta": r"\Theta", "Iota": r"\Iota",
    "Kappa": r"\Kappa", "Lambda": r"\Lambda", "Mu": r"\Mu",
    "Nu": r"\Nu", "Xi": r"\Xi", "Omicron": "O",
    "Pi": r"\Pi", "Rho": r"\Rho", "Sigma": r"\Sigma",
    "Tau": r"\Tau", "Upsilon": r"\Upsilon", "Phi": r"\Phi",
    "Chi": r"\Chi", "Psi": r"\Psi", "Omega": r"\Omega",
}

_GREEK_LOWER: dict[str, str] = {
    "alpha": r"\alpha", "beta": r"\beta", "gamma": r"\gamma",
    "delta": r"\delta", "epsilon": r"\epsilon", "zeta": r"\zeta",
    "eta": r"\eta", "theta": r"\theta", "iota": r"\iota",
    "kappa": r"\kappa", "lambda": r"\lambda", "mu": r"\mu",
    "nu": r"\nu", "xi": r"\xi", "omicron": "o",
    "pi": r"\pi", "rho": r"\rho", "sigma": r"\sigma",
    "tau": r"\tau", "upsilon": r"\upsilon", "phi": r"\phi",
    "chi": r"\chi", "psi": r"\psi", "omega": r"\omega",
}

_GREEK_VARIANTS: dict[str, str] = {
    "vartheta": r"\vartheta", "varpi": r"\varpi",
    "varsigma": r"\varsigma", "varupsilon": r"\varupsilon",
    "varphi": r"\varphi", "varepsilon": r"\varepsilon",
}

_SPECIAL_SYMBOLS: dict[str, str] = {
    "ALEPH": r"\aleph", "HBAR": r"\hbar", "IMATH": r"\imath",
    "JMATH": r"\jmath", "OHM": r"\Omega",
    "ELL": r"\ell", "LITER": r"\ell",
    "WP": r"\wp", "IMAG": r"\Im", "ANGSTROM": r"\text{\AA}",
}

_SET_RELATION: dict[str, str] = {
    "PROD": r"\prod", "COPROD": r"\coprod",
    "INTER": r"\bigcap", "CAP": r"\cap", "SQCAP": r"\sqcap",
    "SQCUP": r"\sqcup", "OPLUS": r"\oplus", "OMINUS": r"\ominus",
    "OTIMES": r"\otimes", "ODOT": r"\odot", "OSLASH": r"\oslash",
    "VEE": r"\vee", "WEDGE": r"\wedge",
    "SUBSET": r"\subset", "SUPSET": r"\supset",
    "SUBSETEQ": r"\subseteq", "SUPSETEQ": r"\supseteq",
    "SQSUBSET": r"\sqsubset", "SQSUPSET": r"\sqsupset",
    "SQSUBSETEQ": r"\sqsubseteq", "SQSUPSETEQ": r"\sqsupseteq",
    "IN": r"\in", "OWNS": r"\ni", "notin": r"\notin",
    "LEQ": r"\leq", "GEQ": r"\geq",
    "<<": r"\ll", ">>": r"\gg", "LLL": r"\lll",
    ">>>": r"\ggg",
    "PREC": r"\prec", "SUCC": r"\succ", "UPLUS": r"\uplus",
}

_ARITHMETIC_LOGIC: dict[str, str] = {
    "PLUSMINUS": r"\pm", "MINUSPLUS": r"\mp",
    "times": r"\times", "TIMES": r"\times",
    "DIV": r"\div", "DIVIDE": r"\div",
    "CDOT": r"\cdot", "cdot": r"\cdot",
    "CIRC": r"\circ", "BULLET": r"\bullet",
    "DEG": r"^{\circ}", "AST": r"\ast", "STAR": r"\star",
    "BIGCIRC": r"\bigcirc",
    "EMPTYSET": r"\emptyset", "THEREFORE": r"\therefore",
    "BECAUSE": r"\because", "IDENTICAL": r"\equiv",
    "EXIST": r"\exists",
    "neq": r"\neq", "!=": r"\neq",
    "DOTEQ": r"\doteq",
    "image": r"\Im", "REIMAGE": r"\Re",
    "SIM": r"\sim", "APPROX": r"\approx",
    "SIMEQ": r"\simeq", "CONG": r"\cong",
    "==": r"\equiv", "EQUIV": r"\equiv",
    "ASYMP": r"\asymp", "ISO": r"\cong",
    "DIAMOND": r"\diamond", "DSUM": r"\oplus",
    "FORALL": r"\forall", "prime": "'", "PARTIAL": r"\partial",
    "inf": r"\infty", "INF": r"\infty",
    "LNOT": r"\lnot",
    "PROPTO": r"\propto", "XOR": r"\veebar",
    "TRIANGLED": r"\triangledown",
    "DAGGER": r"\dagger", "DDAGGER": r"\ddagger",
}

_ARROWS: dict[str, str] = {
    "larrow": r"\leftarrow", "rarrow": r"\rightarrow",
    "uparrow": r"\uparrow", "downarrow": r"\downarrow",
    "LARROW": r"\Leftarrow", "RARROW": r"\Rightarrow",
    "UPARROW": r"\Uparrow", "DOWNARROW": r"\Downarrow",
    "lrarrow": r"\leftrightarrow", "udarrow": r"\updownarrow",
    "UDARROW": r"\Updownarrow", "LRARROW": r"\Leftrightarrow",
    "nwarrow": r"\nwarrow", "searrow": r"\searrow",
    "nearrow": r"\nearrow", "swarrow": r"\swarrow",
    "hookleft": r"\hookleftarrow", "hookright": r"\hookrightarrow",
    "mapsto": r"\mapsto",
    "vert": "|", "VERT": r"\|",
    "->": r"\rightarrow", "<-": r"\leftarrow",
    "<->": r"\leftrightarrow",
    "<=>": r"\Leftrightarrow",
    "=>": r"\Rightarrow",
}

_OTHER_SYMBOLS: dict[str, str] = {
    "cdots": r"\cdots", "CDOTS": r"\cdots",
    "LDOTS": r"\ldots", "ldots": r"\ldots",
    "VDOTS": r"\vdots", "vdots": r"\vdots",
    "DDOTS": r"\ddots", "ddots": r"\ddots",
    "TRIANGLE": r"\triangle", "ANGLE": r"\angle",
    "MSANGLE": r"\measuredangle", "SANGLE": r"\sphericalangle",
    "RTANGLE": r"\Box",
    "VDASH": r"\vdash", "HLEFT": r"\dashv",
    "BOT": r"\bot", "TOP": r"\top", "MODELS": r"\models",
    "LAPLACE": r"\mathcal{L}",
    "CENTIGRADE": r"{}^{\circ}\text{C}",
    "FAHRENHEIT": r"{}^{\circ}\text{F}",
    "LSLANT": r"/", "RSLANT": r"\backslash",
    "att": r"\textcircled{att}",
    "hund": r"\textperthousand",
    "thou": r"\textpertenthousand",
    "well": r"\#", "base": r"\triangle",
    "benzene": r"\bigcirc",
    "NABLA": r"\nabla",
}

SYMBOL_MAP: dict[str, str] = {}
SYMBOL_MAP.update(_GREEK_UPPER)
SYMBOL_MAP.update(_GREEK_LOWER)
SYMBOL_MAP.update(_GREEK_VARIANTS)
SYMBOL_MAP.update(_SPECIAL_SYMBOLS)
SYMBOL_MAP.update(_SET_RELATION)
SYMBOL_MAP.update(_ARITHMETIC_LOGIC)
SYMBOL_MAP.update(_OTHER_SYMBOLS)
SYMBOL_MAP.update(_ARROWS)

# ═══════════════════════════════════════════════════════════════════════
# 기본 함수 (항상 로만체, 스펙 §1.1.3)
# ═══════════════════════════════════════════════════════════════════════

FUNC_NAMES: frozenset[str] = frozenset({
    "sin", "cos", "tan", "cot", "log", "ln", "lg",
    "sec", "cosec", "csc", "arcsin", "arccos", "arctan",
    "exp", "Exp", "arc", "limLim",
    "max", "min", "sinh", "cosh", "tanh", "coth", "mod",
    "det", "gcd", "asin", "acos", "atan", "lcm",
})

RESERVED_WORDS: frozenset[str] = frozenset({
    "if", "for", "and", "hom", "ker", "deg", "arg", "dim", "Pr",
})

# 장식 명령 (스펙 §1.2.1)
DECO_CMDS: dict[str, str] = {
    "acute": r"\acute", "ACUTE": r"\acute",
    "grave": r"\grave", "GRAVE": r"\grave",
    "dot": r"\dot", "DOT": r"\dot",
    "ddot": r"\ddot", "DDOT": r"\ddot",
    "hat": r"\widehat", "HAT": r"\widehat",
    "check": r"\check", "CHECK": r"\check",
    "bar": r"\overline", "BAR": r"\overline",
    "vec": r"\overrightarrow", "VEC": r"\overrightarrow",
    "dyad": r"\overleftrightarrow", "DYAD": r"\overleftrightarrow",
    "under": r"\underline", "UNDER": r"\underline",
    "arch": r"\overset{\frown}", "ARCH": r"\overset{\frown}",
    "tilde": r"\widetilde", "TILDE": r"\widetilde",
}

# 큰 연산자 (적분/합/곱 — 스펙 §1.2 기본 명령어)
BIG_OP_CMDS: dict[str, str] = {
    "int": r"\int", "INT": r"\int",
    "oint": r"\oint", "OINT": r"\oint",
    "dint": r"\iint", "DINT": r"\iint",
    "tint": r"\iiint", "TINT": r"\iiint",
    "odint": r"\oiint", "ODINT": r"\oiint",
    "otint": r"\oiiint", "OTINT": r"\oiiint",
    "sum": r"\sum", "SUM": r"\sum",
    "prod": r"\prod",
    "union": r"\bigcup", "UNION": r"\bigcup",
    "inter": r"\bigcap",
    "lim": r"\lim", "Lim": r"\lim",
}

# 구조 명령 (블록을 취하는 명령)
_MATRIX_CMDS = {"matrix", "MATRIX", "pmatrix", "PMATRIX",
                "bmatrix", "BMATRIX", "dmatrix", "DMATRIX",
                "col", "lcol", "rcol"}
_PILE_CMDS = {"pile", "PILE", "lpile", "LPILE", "rpile", "RPILE"}
_CASES_CMDS = {"cases", "CASES"}
_CHOOSE_CMDS = {"CHOOSE", "BINOM"}

# ═══════════════════════════════════════════════════════════════════════
# 토크나이저
# ═══════════════════════════════════════════════════════════════════════

_SPECIAL_CHARS = frozenset("{}^_#&~`")
_WORD_BREAK_CHARS = frozenset("=+,<>")
_MAX_WORD_LEN = 9


def tokenize(script: str) -> list[str]:
    """Tokenize an HWP equation script string.

    Splits the script into a list of tokens following the HWP equation
    grammar rules (special chars, multi-char operators, 9-char word limit).

    Parameters
    ----------
    script : str
        Raw HWP equation script text.

    Returns
    -------
    list[str]
        Ordered list of tokens.
    """
    tokens: list[str] = []
    i = 0
    n = len(script)

    while i < n:
        ch = script[i]

        if ch in " \t\r\n":
            i += 1
            continue

        if ch in _SPECIAL_CHARS:
            tokens.append(ch)
            i += 1
            continue

        if ch == '"':
            j = script.find('"', i + 1)
            if j == -1:
                j = n
            tokens.append(script[i + 1 : j])
            i = j + 1
            continue

        # 다문자 연산자 검사
        two = script[i : i + 2] if i + 1 < n else ""
        three = script[i : i + 3] if i + 2 < n else ""
        four = script[i : i + 4] if i + 3 < n else ""

        if four == ">>>>" or three == ">>>":
            tokens.append(three)
            i += 3
            continue
        if three in ("<->", "<=>", ">>>"):
            tokens.append(three)
            i += 3
            continue
        if two in ("->", "<-", "=>", "!=", "==", "<<", ">>", ">=", "<="):
            tokens.append(two)
            i += 2
            continue

        # 일반 단어
        j = i

        # 수학 연산자 문자가 첫 글자면 한 글자만 소비
        if script[j] in _WORD_BREAK_CHARS:
            tokens.append(script[j])
            i = j + 1
            continue

        while j < n and script[j] not in " \t\r\n" and script[j] not in _SPECIAL_CHARS and script[j] != '"':
            # 다문자 연산자 시작이면 중단
            if j > i:
                rest2 = script[j : j + 2]
                if rest2 in ("->", "<-", "=>", "!=", "==", "<<", ">>", ">=", "<="):
                    break
                rest3 = script[j : j + 3]
                if rest3 in ("<->", "<=>", ">>>"):
                    break
                if script[j] in _WORD_BREAK_CHARS:
                    break
            j += 1

        word = script[i:j]
        if len(word) > _MAX_WORD_LEN:
            # 9자 자동 분리 규칙
            for k in range(0, len(word), _MAX_WORD_LEN):
                chunk = word[k : k + _MAX_WORD_LEN]
                if chunk:
                    tokens.append(chunk)
        else:
            tokens.append(word)
        i = j

    return tokens


# ═══════════════════════════════════════════════════════════════════════
# 재귀 하강 파서
# ═══════════════════════════════════════════════════════════════════════


class _Parser:
    """Recursive-descent parser for HWP equation token streams."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> str | None:
        """Return the current token without consuming it."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def advance(self) -> str:
        """Consume and return the current token."""
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, val: str) -> None:
        """Consume the current token if it matches *val*."""
        tok = self.peek()
        if tok == val:
            self.advance()

    def at_end(self) -> bool:
        """Return True if all tokens have been consumed."""
        return self.pos >= len(self.tokens)

    # ---------------------------------------------------------------
    # equation ::= line ('#' line)*
    # ---------------------------------------------------------------
    def parse_equation(self) -> EqNode:
        """Parse a full equation (top-level entry point)."""
        lines: list[EqNode] = [self._parse_line()]
        while self.peek() == "#":
            self.advance()
            lines.append(self._parse_line())
        if len(lines) == 1:
            return lines[0]
        return EqGroup(children=[
            item
            for i, line in enumerate(lines)
            for item in (([EqNewline()] if i > 0 else []) + [line])
        ])

    # ---------------------------------------------------------------
    # line ::= expr*
    # ---------------------------------------------------------------
    def _parse_line(self) -> EqNode:
        children: list[EqNode] = []
        while not self.at_end() and self.peek() not in ("#", "}"):
            node = self._parse_expr()
            if node is not None:
                children.append(node)
        if len(children) == 1:
            return children[0]
        return EqGroup(children=children)

    # ---------------------------------------------------------------
    # expr ::= term (('over'|'atop') term)?
    # ---------------------------------------------------------------
    def _parse_expr(self) -> EqNode | None:
        left = self._parse_term()
        if left is None:
            return None

        tok = self.peek()
        if tok is None:
            return left

        tok_lower = tok.lower()
        tok_upper = tok.upper()

        if tok_lower in ("over", "atop"):
            has_line = tok_lower == "over"
            self.advance()
            right = self._parse_term()
            if right is None:
                right = EqText("")
            return EqFrac(numer=left, denom=right, has_line=has_line)

        if tok_upper in ("CHOOSE", "BINOM"):
            self.advance()
            k = self._parse_term()
            if k is None:
                k = EqText("")
            return EqChoose(n=left, k=k)

        if tok_upper in ("LSUB", "LSUP"):
            cmd = self.advance().upper()
            arg = self._parse_term()
            if arg is None:
                arg = EqText("")
            if cmd == "LSUB":
                return EqLeftScript(base=left, lsub=arg)
            return EqLeftScript(base=left, lsup=arg)

        if tok_upper in ("REL", "BUILDREL"):
            cmd = self.advance().upper()
            arrow_tok = self.advance() if not self.at_end() else "<->"
            top = self._parse_term() or EqText("")
            bottom = None
            if cmd == "REL":
                bottom = self._parse_term()
            return EqRel(
                left=left, right=EqText(""),
                arrow=arrow_tok, top=top, bottom=bottom,
            )

        return left

    # ---------------------------------------------------------------
    # term ::= atom script? | prefix_cmd term | '{' equation '}'
    # ---------------------------------------------------------------
    def _parse_term(self) -> EqNode | None:
        tok = self.peek()
        if tok is None or tok in ("#", "}"):
            return None

        # 중괄호 그룹
        if tok == "{":
            return self._parse_brace_group()

        # LEFT ... RIGHT 구분자
        if tok in ("LEFT", "left"):
            return self._parse_delimited()

        # 구조 명령 (블록 취하는 것들)
        tok_lower = tok.lower()
        if tok_lower in ("matrix", "pmatrix", "bmatrix", "dmatrix"):
            return self._parse_matrix()
        if tok_lower in ("cases",):
            return self._parse_cases()
        if tok_lower in ("pile", "lpile", "rpile"):
            return self._parse_pile()
        if tok.upper() in ("CHOOSE", "BINOM"):
            return self._parse_choose()
        if tok.upper() in ("LONGDIV",):
            return self._parse_longdiv()
        if tok.upper() in ("LADDER", "SLADDER"):
            return self._parse_ladder()
        if tok.upper() in ("EQALIGN",):
            return self._parse_eqalign()

        # LSUB, LSUP
        if tok.upper() in ("LSUB", "LSUP"):
            return self._parse_left_script()

        # REL, BUILDREL
        if tok.upper() in ("REL", "BUILDREL"):
            return self._parse_rel()

        # COLOR
        if tok.upper() == "COLOR":
            return self._parse_color()

        # SMALL prefix (첨자 없는 집합 기호)
        if tok.upper() == "SMALL":
            self.advance()
            inner = self._parse_term()
            return inner if inner else EqText("")

        # 장식 명령 (prefix)
        if tok in DECO_CMDS:
            self.advance()
            arg = self._parse_term()
            if arg is None:
                arg = EqText("")
            return EqDeco(kind=tok, content=arg)

        # SQRT
        if tok_lower == "sqrt":
            self.advance()
            arg = self._parse_term()
            if arg is None:
                arg = EqText("")
            return EqSqrt(content=arg)

        # NOT
        if tok_lower == "not":
            self.advance()
            arg = self._parse_term()
            if arg is None:
                arg = EqText("")
            return EqNot(content=arg)

        # BIGG / bigg
        if tok_lower == "bigg":
            self.advance()
            arg = self._parse_term()
            if arg is None:
                arg = EqText("")
            return EqBigg(content=arg)

        # 폰트 명령 rm, it, bold
        if tok in ("rm", "it", "bold"):
            self.advance()
            arg = self._parse_term()
            if arg is None:
                arg = EqText("")
            return EqFont(style=tok, content=arg)

        # scale
        if tok_lower == "scale":
            self.advance()
            factor_tok = self.peek()
            factor = 100
            if factor_tok is not None and factor_tok.isdigit():
                factor = int(self.advance())
            arg = self._parse_term()
            if arg is None:
                arg = EqText("")
            return EqScale(factor=factor, content=arg)

        # 큰 연산자 (int, sum, prod, lim 등)
        if tok in BIG_OP_CMDS:
            self.advance()
            node = EqBigOp(name=tok)
            return self._attach_scripts(node)

        # 공백
        if tok == "~":
            self.advance()
            return EqSpace(size="full")
        if tok == "`":
            self.advance()
            return EqSpace(size="quarter")

        # 세로 칸 맞춤
        if tok == "&":
            self.advance()
            return EqAlign()

        # over/atop은 expr에서 처리하므로 여기서는 atom
        if tok.lower() in ("over", "atop"):
            return None

        # 일반 atom
        self.advance()
        node: EqNode
        if tok in SYMBOL_MAP:
            node = EqSymbol(name=tok)
        elif tok in FUNC_NAMES or tok in RESERVED_WORDS:
            node = EqFunc(name=tok)
        else:
            node = EqText(text=tok)

        return self._attach_scripts(node)

    # ---------------------------------------------------------------
    # script ::= '^' atom | '_' atom | 조합
    # ---------------------------------------------------------------
    def _attach_scripts(self, base: EqNode) -> EqNode:
        sup: EqNode | None = None
        sub: EqNode | None = None

        while True:
            saved = self.pos
            while self.peek() in ("`", "~"):
                self.advance()

            tok = self.peek()
            if tok in ("^", "_", "from", "FROM", "to", "TO"):
                self.advance()
                arg = self._parse_script_arg()
                if arg is None:
                    arg = EqText("")
                if tok in ("^", "to", "TO"):
                    sup = arg
                else:
                    sub = arg
            else:
                self.pos = saved
                break

        if sup is not None or sub is not None:
            return EqScript(base=base, sup=sup, sub=sub)
        return base

    def _parse_script_arg(self) -> EqNode | None:
        """^/_ 뒤의 인자: 중괄호 그룹 또는 단일 atom (재귀 첨자 없음)."""
        tok = self.peek()
        if tok is None:
            return None
        if tok == "{":
            return self._parse_brace_group()
        # 단일 토큰만 소비 (첨자 재귀 방지)
        self.advance()
        if tok in SYMBOL_MAP:
            return EqSymbol(name=tok)
        if tok in FUNC_NAMES or tok in RESERVED_WORDS:
            return EqFunc(name=tok)
        return EqText(text=tok)

    # ---------------------------------------------------------------
    # { equation }
    # ---------------------------------------------------------------
    def _parse_brace_group(self) -> EqNode:
        self.expect("{")
        node = self.parse_equation()
        self.expect("}")
        return node

    # ---------------------------------------------------------------
    # LEFT delim ... RIGHT delim
    # ---------------------------------------------------------------
    def _parse_delimited(self) -> EqNode:
        self.advance()  # LEFT
        left_delim = self.advance() if not self.at_end() else "("

        children: list[EqNode] = []
        while not self.at_end():
            tok = self.peek()
            if tok is not None and tok.lower() == "right":
                break
            node = self._parse_expr()
            if node is not None:
                children.append(node)
            if self.peek() == "#":
                self.advance()
                children.append(EqNewline())

        right_delim = ""
        if self.peek() is not None and self.peek().lower() == "right":  # type: ignore[union-attr]
            self.advance()
            if not self.at_end():
                right_delim = self.advance()

        content = EqGroup(children=children) if len(children) != 1 else children[0]
        return EqDelimited(left=left_delim, right=right_delim, content=content)

    # ---------------------------------------------------------------
    # matrix/pmatrix/bmatrix/dmatrix { row & row # row & row }
    # ---------------------------------------------------------------
    def _parse_matrix(self) -> EqNode:
        cmd = self.advance().lower()
        style_map = {
            "matrix": "plain", "pmatrix": "paren",
            "bmatrix": "bracket", "dmatrix": "det",
        }
        style = style_map.get(cmd, "plain")

        if self.peek() != "{":
            return EqMatrix(style=style)

        rows = self._parse_grid()
        return EqMatrix(rows=rows, style=style)

    # ---------------------------------------------------------------
    # cases { row # row }
    # ---------------------------------------------------------------
    def _parse_cases(self) -> EqNode:
        self.advance()  # cases
        if self.peek() != "{":
            return EqCases()
        rows = self._parse_rows()
        return EqCases(rows=rows)

    # ---------------------------------------------------------------
    # pile/lpile/rpile { row # row }
    # ---------------------------------------------------------------
    def _parse_pile(self) -> EqNode:
        cmd = self.advance().lower()
        align_map = {"pile": "center", "lpile": "left", "rpile": "right"}
        align = align_map.get(cmd, "center")

        if self.peek() != "{":
            return EqPile(align=align)
        rows = self._parse_rows()
        return EqPile(rows=rows, align=align)

    # ---------------------------------------------------------------
    # CHOOSE / BINOM: [n] CHOOSE [k] 또는 [n] BINOM [k]
    # ---------------------------------------------------------------
    def _parse_choose(self) -> EqNode:
        self.advance()  # CHOOSE/BINOM
        # CHOOSE는 보통 {n} CHOOSE {k} 구문이지만
        # 스펙에서는 [전체항] CHOOSE [선택항] 으로 나옴
        # 실제로는 이전 토큰이 n, 다음이 k — 하지만 파서에서는
        # CHOOSE 앞에 이미 term이 파싱됐을 수 있음
        # 여기서는 다음 term만 파싱하고, caller에서 이전 term과 합침
        k = self._parse_term()
        if k is None:
            k = EqText("")
        return EqChoose(n=EqText(""), k=k)

    # ---------------------------------------------------------------
    # LONGDIV { divisor }{ content }
    # ---------------------------------------------------------------
    def _parse_longdiv(self) -> EqNode:
        self.advance()  # LONGDIV
        divisor = self._parse_term() or EqText("")
        content = self._parse_term() or EqText("")
        return EqLongdiv(divisor=divisor, content=content)

    # ---------------------------------------------------------------
    # LADDER / SLADDER { ... }
    # ---------------------------------------------------------------
    def _parse_ladder(self) -> EqNode:
        cmd = self.advance()
        content = self._parse_term() or EqText("")
        # LADDER/SLADDER는 LaTeX에 대응이 없으므로 텍스트로 표현
        return EqFont(style="rm", content=EqGroup(children=[
            EqText(f"\\text{{{cmd}}}("),
            content,
            EqText(")"),
        ]))

    # ---------------------------------------------------------------
    # EQALIGN { ... & ... # ... & ... }
    # ---------------------------------------------------------------
    def _parse_eqalign(self) -> EqNode:
        self.advance()  # EQALIGN
        if self.peek() != "{":
            return EqGroup()
        rows = self._parse_grid()
        return EqMatrix(rows=rows, style="align")

    # ---------------------------------------------------------------
    # LSUB / LSUP
    # ---------------------------------------------------------------
    def _parse_left_script(self) -> EqNode:
        cmd = self.advance().upper()
        arg = self._parse_term() or EqText("")

        # LSUB/LSUP: base LSUB y → {}_{y}base 또는 base LSUP y → {}^{y}base
        # 스펙: x LSUB y → 왼쪽 아래첨자, x LSUP y → 왼쪽 위첨자
        # 실제 구조: [arg] [다음term] — arg가 왼쪽첨자, 다음이 base
        # 하지만 파서에서 x는 이미 파싱됨 → 여기서는 arg만 반환
        if cmd == "LSUB":
            return EqLeftScript(base=EqText(""), lsub=arg)
        return EqLeftScript(base=EqText(""), lsup=arg)

    # ---------------------------------------------------------------
    # REL <-> {top} {bottom} / BUILDREL <-> {top}
    # ---------------------------------------------------------------
    def _parse_rel(self) -> EqNode:
        cmd = self.advance().upper()
        arrow_tok = self.advance() if not self.at_end() else "<->"
        top = self._parse_term() or EqText("")
        bottom = None
        if cmd == "REL":
            bottom = self._parse_term()
        return EqRel(
            left=EqText(""), right=EqText(""),
            arrow=arrow_tok, top=top, bottom=bottom,
        )

    # ---------------------------------------------------------------
    # COLOR {R,G,B} {content}
    # ---------------------------------------------------------------
    def _parse_color(self) -> EqNode:
        self.advance()  # COLOR
        color_spec = self._parse_term() or EqText("0,0,0")
        content = self._parse_term() or EqText("")
        r, g, b = 0, 0, 0
        color_str = ""
        if isinstance(color_spec, EqText):
            color_str = color_spec.text
        elif isinstance(color_spec, EqGroup):
            color_str = "".join(
                c.text if isinstance(c, EqText) else "" for c in color_spec.children
            )
        if color_str:
            parts = color_str.split(",")
            if len(parts) >= 3:
                try:
                    r, g, b = int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip())
                except ValueError:
                    pass
        return EqColor(r=r, g=g, b=b, content=content)

    # ---------------------------------------------------------------
    # 내부 유틸: { row # row } → list[EqNode]
    # ---------------------------------------------------------------
    def _parse_rows(self) -> list[EqNode]:
        self.expect("{")
        rows: list[EqNode] = []
        while not self.at_end() and self.peek() != "}":
            row_children: list[EqNode] = []
            while not self.at_end() and self.peek() not in ("#", "}"):
                node = self._parse_expr()
                if node is not None:
                    row_children.append(node)
            if len(row_children) == 1:
                rows.append(row_children[0])
            else:
                rows.append(EqGroup(children=row_children))
            if self.peek() == "#":
                self.advance()
        self.expect("}")
        return rows

    # ---------------------------------------------------------------
    # 내부 유틸: { row & col # row & col } → list[list[EqNode]]
    # ---------------------------------------------------------------
    def _parse_grid(self) -> list[list[EqNode]]:
        self.expect("{")
        rows: list[list[EqNode]] = []
        current_row: list[EqNode] = []

        while not self.at_end() and self.peek() != "}":
            cell_children: list[EqNode] = []
            while not self.at_end() and self.peek() not in ("&", "#", "}"):
                node = self._parse_expr()
                if node is not None:
                    cell_children.append(node)
            cell = EqGroup(children=cell_children) if len(cell_children) != 1 else (cell_children[0] if cell_children else EqText(""))
            current_row.append(cell)

            if self.peek() == "&":
                self.advance()
            elif self.peek() == "#":
                self.advance()
                rows.append(current_row)
                current_row = []
            else:
                break

        if current_row:
            rows.append(current_row)
        self.expect("}")
        return rows


def parse(script: str) -> EqNode:
    """Parse an HWP equation script string into an AST.

    Parameters
    ----------
    script : str
        Raw HWP equation script text.

    Returns
    -------
    EqNode
        Root AST node (typically an ``EqGroup``).
    """
    if not script or not script.strip():
        return EqGroup()
    tokens = tokenize(script)
    if not tokens:
        return EqGroup()
    parser = _Parser(tokens)
    return parser.parse_equation()


# ═══════════════════════════════════════════════════════════════════════
# LaTeX 렌더러
# ═══════════════════════════════════════════════════════════════════════


def to_latex(node: EqNode) -> str:
    """Render an equation AST node to a LaTeX string.

    Parameters
    ----------
    node : EqNode
        Root (or sub-) node of the equation AST.

    Returns
    -------
    str
        LaTeX representation of the equation.
    """
    if isinstance(node, EqText):
        return node.text

    if isinstance(node, EqGroup):
        parts = [to_latex(c) for c in node.children]
        return " ".join(p for p in parts if p)

    if isinstance(node, EqFrac):
        n = to_latex(node.numer)
        d = to_latex(node.denom)
        if node.has_line:
            return rf"\frac{{{n}}}{{{d}}}"
        return rf"{{{n} \atop {d}}}"

    if isinstance(node, EqScript):
        base = to_latex(node.base)
        result = base
        if node.sub is not None:
            s = to_latex(node.sub)
            result += f"_{{{s}}}"
        if node.sup is not None:
            s = to_latex(node.sup)
            result += f"^{{{s}}}"
        return result

    if isinstance(node, EqLeftScript):
        base = to_latex(node.base)
        prefix = ""
        if node.lsub is not None:
            s = to_latex(node.lsub)
            prefix += f"{{}}_{{{s}}}"
        if node.lsup is not None:
            s = to_latex(node.lsup)
            prefix += f"{{}}^{{{s}}}"
        return prefix + base

    if isinstance(node, EqSqrt):
        c = to_latex(node.content)
        return rf"\sqrt{{{c}}}"

    if isinstance(node, EqDeco):
        latex_cmd = DECO_CMDS.get(node.kind, r"\hat")
        c = to_latex(node.content)
        return rf"{latex_cmd}{{{c}}}"

    if isinstance(node, EqFunc):
        name = node.name
        if name in RESERVED_WORDS:
            return rf"\mathrm{{{name}}}"
        return rf"\{name}"

    if isinstance(node, EqSymbol):
        return SYMBOL_MAP.get(node.name, node.name)

    if isinstance(node, EqDelimited):
        left = _delim_to_latex(node.left)
        right = _delim_to_latex(node.right)
        c = to_latex(node.content)
        return rf"\left{left} {c} \right{right}"

    if isinstance(node, EqMatrix):
        env = _matrix_env(node.style)
        row_strs = []
        for row in node.rows:
            cells = [to_latex(cell) for cell in row]
            row_strs.append(" & ".join(cells))
        body = r" \\ ".join(row_strs)
        return rf"\begin{{{env}}} {body} \end{{{env}}}"

    if isinstance(node, EqCases):
        row_strs = [to_latex(r) for r in node.rows]
        body = r" \\ ".join(row_strs)
        return rf"\begin{{cases}} {body} \end{{cases}}"

    if isinstance(node, EqPile):
        env_map = {"center": "gathered", "left": "aligned", "right": "aligned"}
        env = env_map.get(node.align, "gathered")
        row_strs = [to_latex(r) for r in node.rows]
        body = r" \\ ".join(row_strs)
        return rf"\begin{{{env}}} {body} \end{{{env}}}"

    if isinstance(node, EqNewline):
        return r"\\"

    if isinstance(node, EqSpace):
        if node.size == "quarter":
            return r"\,"
        return r"\ "

    if isinstance(node, EqAlign):
        return "&"

    if isinstance(node, EqNot):
        c = to_latex(node.content)
        return rf"\cancel{{{c}}}"

    if isinstance(node, EqBigg):
        c = to_latex(node.content)
        return rf"\bigg {c}"

    if isinstance(node, EqColor):
        c = to_latex(node.content)
        return rf"\textcolor[RGB]{{{node.r},{node.g},{node.b}}}{{{c}}}"

    if isinstance(node, EqFont):
        c = to_latex(node.content)
        if node.style == "rm":
            return rf"\mathrm{{{c}}}"
        if node.style == "bold":
            return rf"\mathbf{{{c}}}"
        if node.style == "it":
            return c
        return c

    if isinstance(node, EqScale):
        c = to_latex(node.content)
        if node.factor != 100:
            return rf"\scalebox{{{node.factor / 100:.2f}}}{{{c}}}"
        return c

    if isinstance(node, EqChoose):
        n = to_latex(node.n)
        k = to_latex(node.k)
        return rf"\binom{{{n}}}{{{k}}}"

    if isinstance(node, EqRel):
        left_str = to_latex(node.left) if node.left else ""
        arrow_latex = SYMBOL_MAP.get(node.arrow, node.arrow)
        top = to_latex(node.top) if node.top else ""
        bottom = to_latex(node.bottom) if node.bottom else ""
        right_str = to_latex(node.right) if node.right else ""
        if bottom:
            arrow_part = rf"\overset{{{top}}}{{\underset{{{bottom}}}{{{arrow_latex}}}}}"
        else:
            arrow_part = rf"\overset{{{top}}}{{{arrow_latex}}}"
        parts = [p for p in (left_str, arrow_part, right_str) if p]
        return " ".join(parts)

    if isinstance(node, EqBigOp):
        return BIG_OP_CMDS.get(node.name, rf"\{node.name}")

    if isinstance(node, EqLongdiv):
        divisor = to_latex(node.divisor)
        content = to_latex(node.content)
        return rf"{divisor} \overline{{\smash){{{content}}}}}"

    return ""


def _delim_to_latex(d: str) -> str:
    m = {
        "(": "(", ")": ")",
        "[": "[", "]": "]",
        "lbrace": r"\{", "rbrace": r"\}",
        "|": "|", "||": r"\|",
        "lfloor": r"\lfloor", "rfloor": r"\rfloor",
        "lceil": r"\lceil", "rceil": r"\rceil",
        "langle": r"\langle", "rangle": r"\rangle",
        ".": ".",
    }
    if d in m:
        return m[d]
    if d in ("{", r"\{"):
        return r"\{"
    if d in ("}", r"\}"):
        return r"\}"
    return d


def _matrix_env(style: str) -> str:
    return {
        "plain": "matrix",
        "paren": "pmatrix",
        "bracket": "bmatrix",
        "det": "vmatrix",
        "align": "aligned",
    }.get(style, "matrix")


# ═══════════════════════════════════════════════════════════════════════
# 공개 API
# ═══════════════════════════════════════════════════════════════════════


def hwp_script_to_latex(script: str) -> str:
    """Convert an HWP equation script to LaTeX in one step.

    Convenience wrapper that tokenizes, parses, and renders to LaTeX.

    Parameters
    ----------
    script : str
        Raw HWP equation script text.

    Returns
    -------
    str
        LaTeX string, or empty string if *script* is blank.
    """
    if not script or not script.strip():
        return ""
    ast = parse(script)
    return to_latex(ast)
