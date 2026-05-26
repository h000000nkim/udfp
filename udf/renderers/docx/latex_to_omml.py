"""LaTeX → OMML (Office Math Markup Language) 변환.

HWP 수식 파서(equation.py)가 생성하는 LaTeX 부분집합을 OMML XML로 변환한다.
지원: frac, sqrt, sub/sup, delimiter, nary, matrix, cases, accent,
      Greek/symbol, mathrm/mathbf, binom, overset/underset, cancel.
"""

from __future__ import annotations

import re

from lxml import etree

_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_NSMAP = {"m": _M}

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ",
    "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ",
    "omega": "ω",
    "Alpha": "Α", "Beta": "Β", "Gamma": "Γ", "Delta": "Δ",
    "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}

_SYMBOL = {
    "infty": "∞", "partial": "∂", "nabla": "∇",
    "pm": "±", "mp": "∓", "times": "×", "div": "÷",
    "cdot": "⋅", "leq": "≤", "geq": "≥", "neq": "≠",
    "approx": "≈", "equiv": "≡", "sim": "∼",
    "in": "∈", "notin": "∉",
    "subset": "⊂", "supset": "⊃", "subseteq": "⊆", "supseteq": "⊇",
    "cup": "∪", "cap": "∩",
    "ldots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱",
    "rightarrow": "→", "leftarrow": "←", "leftrightarrow": "↔",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔",
    "forall": "∀", "exists": "∃",
    "angle": "∠", "perp": "⊥", "parallel": "∥",
    "neg": "¬", "land": "∧", "lor": "∨",
    "to": "→", "mapsto": "↦",
}

_NARY = {
    "sum": "∑", "prod": "∏", "coprod": "∐",
    "int": "∫", "iint": "∬", "iiint": "∭", "oint": "∮",
    "bigcup": "⋃", "bigcap": "⋂",
}

_ACCENT = {
    "hat": "̂", "bar": "̅", "overline": "̅",
    "vec": "⃗", "dot": "̇", "ddot": "̈",
    "tilde": "̃", "breve": "̆", "check": "̌",
    "widehat": "̂", "widetilde": "̃", "overrightarrow": "⃗",
}

_DELIM_CHAR = {
    "(": "(", ")": ")",
    "[": "[", "]": "]",
    "\\{": "{", "\\}": "}",
    "\\lfloor": "⌊", "\\rfloor": "⌋",
    "\\lceil": "⌈", "\\rceil": "⌉",
    "\\langle": "⟨", "\\rangle": "⟩",
    "|": "|", "\\|": "‖",
    ".": "",
}

_TOK_RE = re.compile(
    r"\\begin\{[^}]+\}"
    r"|\\end\{[^}]+\}"
    r"|\\[a-zA-Z]+"
    r"|\\[{}|]"
    r"|\\\\|\\,|\\;|\\:|\\!"
    r"|\[|\]"
    r"|[{}^_&]"
    r"|[^\s{}\[\]^_&\\]+"
    r"|\s+"
)

_ROWSEP = "\\\\"


def _tokenize(latex: str) -> list[str]:
    return _TOK_RE.findall(latex)


def _mr(text: str, *, italic: bool = True) -> etree._Element:
    r = etree.Element(f"{{{_M}}}r", nsmap=_NSMAP)
    if not italic:
        rpr = etree.SubElement(r, f"{{{_M}}}rPr")
        sty = etree.SubElement(rpr, f"{{{_M}}}sty")
        sty.set(f"{{{_M}}}val", "p")
    t = etree.SubElement(r, f"{{{_M}}}t")
    t.text = text
    return r


class _Parser:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> str | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _advance(self) -> str | None:
        tok = self._peek()
        if tok is not None:
            self._pos += 1
        return tok

    def _expect(self, tok: str) -> None:
        self._advance()

    def parse_all(self) -> list[etree._Element]:
        elements: list[etree._Element] = []
        while self._peek() is not None:
            el = self._parse_expr()
            if el is not None:
                elements.append(el)
        return elements

    def _parse_group_elements(self) -> list[etree._Element]:
        self._expect("{")
        elements: list[etree._Element] = []
        while self._peek() not in ("}", None):
            el = self._parse_expr()
            if el is not None:
                elements.append(el)
        self._expect("}")
        return elements

    def _parse_single(self) -> etree._Element:
        tok = self._peek()
        if tok == "{":
            children = self._parse_group_elements()
            if len(children) == 1:
                return children[0]
            e = etree.Element(f"{{{_M}}}e", nsmap=_NSMAP)
            for c in children:
                e.append(c)
            return e
        if tok is not None:
            self._advance()
            if tok.startswith("\\"):
                cmd = tok[1:]
                if cmd in _GREEK:
                    return _mr(_GREEK[cmd])
                if cmd in _SYMBOL:
                    return _mr(_SYMBOL[cmd], italic=False)
            return _mr(tok)
        return _mr("")

    def _maybe_script(self, base: etree._Element) -> etree._Element:
        has_sub = has_sup = False
        sub_el = sup_el = None

        while self._peek() in ("_", "^"):
            op = self._advance()
            child = self._parse_single()
            if op == "_" and not has_sub:
                has_sub = True
                sub_el = child
            elif op == "^" and not has_sup:
                has_sup = True
                sup_el = child

        if not has_sub and not has_sup:
            return base

        base_e = etree.Element(f"{{{_M}}}e", nsmap=_NSMAP)
        if base.tag == f"{{{_M}}}e":
            for c in list(base):
                base_e.append(c)
        else:
            base_e.append(base)

        if has_sub and has_sup:
            el = etree.Element(f"{{{_M}}}sSubSup", nsmap=_NSMAP)
            el.append(base_e)
            s = etree.SubElement(el, f"{{{_M}}}sub")
            if sub_el is not None:
                s.append(sub_el)
            s = etree.SubElement(el, f"{{{_M}}}sup")
            if sup_el is not None:
                s.append(sup_el)
        elif has_sub:
            el = etree.Element(f"{{{_M}}}sSub", nsmap=_NSMAP)
            el.append(base_e)
            s = etree.SubElement(el, f"{{{_M}}}sub")
            if sub_el is not None:
                s.append(sub_el)
        else:
            el = etree.Element(f"{{{_M}}}sSup", nsmap=_NSMAP)
            el.append(base_e)
            s = etree.SubElement(el, f"{{{_M}}}sup")
            if sup_el is not None:
                s.append(sup_el)
        return el

    def _parse_expr(self) -> etree._Element | None:
        tok = self._peek()
        if tok is None or tok == "}":
            return None

        if tok.strip() == "":
            self._advance()
            return _mr(" ", italic=False)

        if tok == "{":
            children = self._parse_group_elements()
            if len(children) == 1:
                base = children[0]
            else:
                base = etree.Element(f"{{{_M}}}e", nsmap=_NSMAP)
                for c in children:
                    base.append(c)
            return self._maybe_script(base)

        if tok in ("^", "_"):
            self._advance()
            return None

        if tok == "&":
            self._advance()
            return None

        if tok == _ROWSEP:
            self._advance()
            return None

        if tok.startswith("\\"):
            return self._parse_command()

        self._advance()
        base = _mr(tok)
        return self._maybe_script(base)

    def _parse_command(self) -> etree._Element | None:
        tok = self._advance()
        if tok is None:
            return None

        if tok == _ROWSEP:
            return None
        if tok in ("\\,", "\\;", "\\:", "\\!"):
            return _mr(" ", italic=False)

        cmd = tok[1:]

        if cmd == "frac":
            return self._cmd_frac()
        if cmd == "sqrt":
            return self._cmd_sqrt()
        if cmd in ("left", "right"):
            return self._cmd_delim(cmd)
        if cmd in _NARY:
            return self._cmd_nary(cmd)
        if cmd in _ACCENT:
            return self._cmd_accent(cmd)
        if cmd in ("mathrm", "text", "textrm"):
            return self._cmd_font("p")
        if cmd == "mathbf":
            return self._cmd_font("b")
        if cmd == "mathit":
            return self._cmd_font("i")
        if cmd == "binom":
            return self._cmd_binom()
        if cmd == "overset":
            return self._cmd_overset()
        if cmd == "underset":
            return self._cmd_underset()
        if cmd == "overline":
            return self._cmd_accent("overline")
        if cmd == "cancel":
            return self._cmd_cancel()
        if cmd == "textcolor":
            return self._cmd_textcolor()
        if cmd == "scalebox":
            return self._cmd_scalebox()
        if cmd == "bigg":
            return self._parse_expr()
        if tok.startswith("\\begin{"):
            return self._cmd_env(tok)
        if cmd in _GREEK:
            return self._maybe_script(_mr(_GREEK[cmd]))
        if cmd in _SYMBOL:
            return self._maybe_script(_mr(_SYMBOL[cmd], italic=False))
        if cmd == "atop":
            return None

        return _mr(tok)

    def _cmd_frac(self) -> etree._Element:
        f = etree.Element(f"{{{_M}}}f", nsmap=_NSMAP)
        num = etree.SubElement(f, f"{{{_M}}}num")
        for c in self._parse_group_elements():
            num.append(c)
        den = etree.SubElement(f, f"{{{_M}}}den")
        for c in self._parse_group_elements():
            den.append(c)
        return self._maybe_script(f)

    def _cmd_sqrt(self) -> etree._Element:
        rad = etree.Element(f"{{{_M}}}rad", nsmap=_NSMAP)
        rp = etree.SubElement(rad, f"{{{_M}}}radPr")
        dh = etree.SubElement(rp, f"{{{_M}}}degHide")
        dh.set(f"{{{_M}}}val", "1")
        etree.SubElement(rad, f"{{{_M}}}deg")
        e = etree.SubElement(rad, f"{{{_M}}}e")
        for c in self._parse_group_elements():
            e.append(c)
        return self._maybe_script(rad)

    def _cmd_delim(self, side: str) -> etree._Element | None:
        if side == "right":
            return None

        left_tok = self._advance() or "("
        left_char = _DELIM_CHAR.get(left_tok, left_tok)

        inner: list[etree._Element] = []
        right_char = ")"
        while self._peek() is not None:
            if self._peek() == "\\right":
                self._advance()
                right_tok = self._advance() or ")"
                right_char = _DELIM_CHAR.get(right_tok, right_tok)
                break
            el = self._parse_expr()
            if el is not None:
                inner.append(el)

        d = etree.Element(f"{{{_M}}}d", nsmap=_NSMAP)
        dp = etree.SubElement(d, f"{{{_M}}}dPr")
        etree.SubElement(dp, f"{{{_M}}}begChr").set(f"{{{_M}}}val", left_char)
        etree.SubElement(dp, f"{{{_M}}}endChr").set(f"{{{_M}}}val", right_char)
        e = etree.SubElement(d, f"{{{_M}}}e")
        for c in inner:
            e.append(c)
        return self._maybe_script(d)

    def _cmd_nary(self, cmd: str) -> etree._Element:
        nary = etree.Element(f"{{{_M}}}nary", nsmap=_NSMAP)
        np = etree.SubElement(nary, f"{{{_M}}}naryPr")
        etree.SubElement(np, f"{{{_M}}}chr").set(f"{{{_M}}}val", _NARY[cmd])

        sub = etree.SubElement(nary, f"{{{_M}}}sub")
        sup = etree.SubElement(nary, f"{{{_M}}}sup")
        etree.SubElement(nary, f"{{{_M}}}e")

        while self._peek() in ("_", "^"):
            op = self._advance()
            children = self._parse_group_elements() if self._peek() == "{" else [self._parse_single()]
            target = sub if op == "_" else sup
            for c in children:
                target.append(c)

        return nary

    def _cmd_accent(self, cmd: str) -> etree._Element:
        acc = etree.Element(f"{{{_M}}}acc", nsmap=_NSMAP)
        ap = etree.SubElement(acc, f"{{{_M}}}accPr")
        etree.SubElement(ap, f"{{{_M}}}chr").set(f"{{{_M}}}val", _ACCENT[cmd])
        e = etree.SubElement(acc, f"{{{_M}}}e")
        for c in self._parse_group_elements():
            e.append(c)
        return self._maybe_script(acc)

    def _cmd_font(self, style: str) -> etree._Element:
        children = self._parse_group_elements()
        for c in children:
            if c.tag == f"{{{_M}}}r":
                rpr = c.find(f"{{{_M}}}rPr")
                if rpr is None:
                    rpr = etree.SubElement(c, f"{{{_M}}}rPr")
                    c.insert(0, rpr)
                sty = rpr.find(f"{{{_M}}}sty")
                if sty is None:
                    sty = etree.SubElement(rpr, f"{{{_M}}}sty")
                sty.set(f"{{{_M}}}val", style)
        if len(children) == 1:
            return children[0]
        wrapper = etree.Element(f"{{{_M}}}e", nsmap=_NSMAP)
        for c in children:
            wrapper.append(c)
        return wrapper

    def _cmd_binom(self) -> etree._Element:
        d = etree.Element(f"{{{_M}}}d", nsmap=_NSMAP)
        dp = etree.SubElement(d, f"{{{_M}}}dPr")
        etree.SubElement(dp, f"{{{_M}}}begChr").set(f"{{{_M}}}val", "(")
        etree.SubElement(dp, f"{{{_M}}}endChr").set(f"{{{_M}}}val", ")")
        e_outer = etree.SubElement(d, f"{{{_M}}}e")
        f = etree.SubElement(e_outer, f"{{{_M}}}f")
        fp = etree.SubElement(f, f"{{{_M}}}fPr")
        etree.SubElement(fp, f"{{{_M}}}type").set(f"{{{_M}}}val", "noBar")
        num = etree.SubElement(f, f"{{{_M}}}num")
        for c in self._parse_group_elements():
            num.append(c)
        den = etree.SubElement(f, f"{{{_M}}}den")
        for c in self._parse_group_elements():
            den.append(c)
        return self._maybe_script(d)

    def _cmd_overset(self) -> etree._Element:
        top = self._parse_group_elements()
        base = self._parse_group_elements()
        el = etree.Element(f"{{{_M}}}limUpp", nsmap=_NSMAP)
        e = etree.SubElement(el, f"{{{_M}}}e")
        for c in base:
            e.append(c)
        lim = etree.SubElement(el, f"{{{_M}}}lim")
        for c in top:
            lim.append(c)
        return el

    def _cmd_underset(self) -> etree._Element:
        bot = self._parse_group_elements()
        base = self._parse_group_elements()
        el = etree.Element(f"{{{_M}}}limLow", nsmap=_NSMAP)
        e = etree.SubElement(el, f"{{{_M}}}e")
        for c in base:
            e.append(c)
        lim = etree.SubElement(el, f"{{{_M}}}lim")
        for c in bot:
            lim.append(c)
        return el

    def _cmd_cancel(self) -> etree._Element:
        children = self._parse_group_elements()
        bb = etree.Element(f"{{{_M}}}borderBox", nsmap=_NSMAP)
        bp = etree.SubElement(bb, f"{{{_M}}}borderBoxPr")
        for attr in ("hideTop", "hideBot", "hideLeft", "hideRight"):
            etree.SubElement(bp, f"{{{_M}}}{attr}").set(f"{{{_M}}}val", "1")
        etree.SubElement(bp, f"{{{_M}}}strikeBLTR").set(f"{{{_M}}}val", "1")
        e = etree.SubElement(bb, f"{{{_M}}}e")
        for c in children:
            e.append(c)
        return bb

    def _cmd_textcolor(self) -> etree._Element | None:
        if self._peek() == "[":
            while self._peek() not in ("]", None):
                self._advance()
            if self._peek() == "]":
                self._advance()
        if self._peek() == "{":
            self._parse_group_elements()
        children = self._parse_group_elements() if self._peek() == "{" else []
        if len(children) == 1:
            return children[0]
        if children:
            wrapper = etree.Element(f"{{{_M}}}e", nsmap=_NSMAP)
            for c in children:
                wrapper.append(c)
            return wrapper
        return None

    def _cmd_scalebox(self) -> etree._Element | None:
        if self._peek() == "{":
            self._parse_group_elements()
        children = self._parse_group_elements() if self._peek() == "{" else []
        if len(children) == 1:
            return children[0]
        if children:
            wrapper = etree.Element(f"{{{_M}}}e", nsmap=_NSMAP)
            for c in children:
                wrapper.append(c)
            return wrapper
        return None

    def _cmd_env(self, begin_tok: str) -> etree._Element | None:
        env = begin_tok.split("{", 1)[1].rstrip("}")
        end_tok = f"\\end{{{env}}}"

        if env == "cases":
            return self._env_cases(end_tok)
        if env in ("matrix", "pmatrix", "bmatrix", "vmatrix", "Bmatrix",
                    "Vmatrix", "smallmatrix"):
            return self._env_matrix(env, end_tok)
        if env in ("gathered", "aligned"):
            return self._env_gathered(end_tok)

        inner: list[etree._Element] = []
        while self._peek() not in (end_tok, None):
            el = self._parse_expr()
            if el is not None:
                inner.append(el)
        if self._peek() == end_tok:
            self._advance()
        if len(inner) == 1:
            return inner[0]
        wrapper = etree.Element(f"{{{_M}}}e", nsmap=_NSMAP)
        for c in inner:
            wrapper.append(c)
        return wrapper

    def _collect_matrix_rows(self, end_tok: str) -> list[list[list[etree._Element]]]:
        """Collect matrix content into rows × cols × elements."""
        rows: list[list[list[etree._Element]]] = [[[]]]

        while self._peek() not in (end_tok, None):
            tok = self._peek()
            if tok == _ROWSEP:
                self._advance()
                rows.append([[]])
                continue
            if tok == "&":
                self._advance()
                rows[-1].append([])
                continue
            el = self._parse_expr()
            if el is not None:
                rows[-1][-1].append(el)

        if self._peek() == end_tok:
            self._advance()

        while rows and all(not cell for cell in rows[-1]):
            rows.pop()

        return rows

    def _build_matrix(self, rows: list[list[list[etree._Element]]]) -> etree._Element:
        m = etree.Element(f"{{{_M}}}m", nsmap=_NSMAP)
        for row_cells in rows:
            mr = etree.SubElement(m, f"{{{_M}}}mr")
            for cell_els in row_cells:
                e = etree.SubElement(mr, f"{{{_M}}}e")
                for el in cell_els:
                    e.append(el)
            if not row_cells:
                etree.SubElement(mr, f"{{{_M}}}e")
        return m

    def _env_cases(self, end_tok: str) -> etree._Element:
        rows = self._collect_matrix_rows(end_tok)
        d = etree.Element(f"{{{_M}}}d", nsmap=_NSMAP)
        dp = etree.SubElement(d, f"{{{_M}}}dPr")
        etree.SubElement(dp, f"{{{_M}}}begChr").set(f"{{{_M}}}val", "{")
        etree.SubElement(dp, f"{{{_M}}}endChr").set(f"{{{_M}}}val", "")
        e = etree.SubElement(d, f"{{{_M}}}e")
        e.append(self._build_matrix(rows))
        return d

    def _env_matrix(self, env: str, end_tok: str) -> etree._Element:
        rows = self._collect_matrix_rows(end_tok)
        inner = self._build_matrix(rows)

        delims = {
            "pmatrix": ("(", ")"), "bmatrix": ("[", "]"),
            "Bmatrix": ("{", "}"), "vmatrix": ("|", "|"),
            "Vmatrix": ("‖", "‖"),
        }
        if env in delims:
            left, right = delims[env]
            d = etree.Element(f"{{{_M}}}d", nsmap=_NSMAP)
            dp = etree.SubElement(d, f"{{{_M}}}dPr")
            etree.SubElement(dp, f"{{{_M}}}begChr").set(f"{{{_M}}}val", left)
            etree.SubElement(dp, f"{{{_M}}}endChr").set(f"{{{_M}}}val", right)
            e = etree.SubElement(d, f"{{{_M}}}e")
            e.append(inner)
            return d
        return inner

    def _env_gathered(self, end_tok: str) -> etree._Element:
        rows = self._collect_matrix_rows(end_tok)
        return self._build_matrix(rows)


def latex_to_omml(latex: str) -> etree._Element:
    """Convert a LaTeX string to an <m:oMath> element."""
    tokens = _tokenize(latex.strip())
    parser = _Parser(tokens)
    elements = parser.parse_all()
    omath = etree.Element(f"{{{_M}}}oMath", nsmap=_NSMAP)
    for el in elements:
        omath.append(el)
    return omath


def latex_to_omml_para(latex: str) -> etree._Element:
    """Convert a LaTeX string to a display-mode <m:oMathPara> element."""
    omath = latex_to_omml(latex)
    para = etree.Element(f"{{{_M}}}oMathPara", nsmap=_NSMAP)
    para.append(omath)
    return para
