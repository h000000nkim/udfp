"""OMML (Office Math Markup Language) → LaTeX 변환.

DOCX 파서가 m:oMath XML 요소를 받아 LaTeX 문자열로 변환한다.
지원: frac, sqrt, sub/sup, delimiter, nary, bar, accent, func, limLow/limUpp,
      matrix, sSub, sSup, sSubSup, eqArr, groupChr.
"""

from __future__ import annotations

from lxml import etree

_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _mt(tag: str) -> str:
    return f"{{{_M}}}{tag}"


_NARY_CHAR_TO_LATEX: dict[str, str] = {
    "∑": r"\sum",
    "∏": r"\prod",
    "∐": r"\coprod",
    "∫": r"\int",
    "∬": r"\iint",
    "∭": r"\iiint",
    "∮": r"\oint",
    "⋃": r"\bigcup",
    "⋂": r"\bigcap",
}

_ACCENT_CHAR_TO_LATEX: dict[str, str] = {
    "̂": r"\hat",
    "̅": r"\bar",
    "⃗": r"\vec",
    "̇": r"\dot",
    "̈": r"\ddot",
    "̃": r"\tilde",
    "̆": r"\breve",
    "̌": r"\check",
    "̂": r"\widehat",
    "̃": r"\widetilde",
    "⃗": r"\overrightarrow",
}

_UNICODE_TO_LATEX: dict[str, str] = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\varepsilon", "ζ": r"\zeta", "η": r"\eta",
    "θ": r"\theta", "ι": r"\iota", "κ": r"\kappa", "λ": r"\lambda",
    "μ": r"\mu", "ν": r"\nu", "ξ": r"\xi", "π": r"\pi",
    "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau", "υ": r"\upsilon",
    "φ": r"\varphi", "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega",
    "Α": r"\Alpha", "Β": r"\Beta", "Γ": r"\Gamma", "Δ": r"\Delta",
    "Θ": r"\Theta", "Λ": r"\Lambda", "Ξ": r"\Xi", "Π": r"\Pi",
    "Σ": r"\Sigma", "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega",
    "∞": r"\infty", "∂": r"\partial", "∇": r"\nabla",
    "±": r"\pm", "∓": r"\mp", "×": r"\times", "÷": r"\div",
    "⋅": r"\cdot", "≤": r"\leq", "≥": r"\geq", "≠": r"\neq",
    "≈": r"\approx", "≡": r"\equiv", "∼": r"\sim",
    "∈": r"\in", "∉": r"\notin",
    "⊂": r"\subset", "⊃": r"\supset", "⊆": r"\subseteq", "⊇": r"\supseteq",
    "∪": r"\cup", "∩": r"\cap",
    "…": r"\ldots", "⋯": r"\cdots", "⋮": r"\vdots", "⋱": r"\ddots",
    "→": r"\rightarrow", "←": r"\leftarrow", "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow", "⇐": r"\Leftarrow", "⇔": r"\Leftrightarrow",
    "∀": r"\forall", "∃": r"\exists",
    "∠": r"\angle", "⊥": r"\perp", "∥": r"\parallel",
    "¬": r"\neg", "∧": r"\land", "∨": r"\lor",
    "↦": r"\mapsto",
    "′": "'",
}


def omml_to_latex(omath_el: etree._Element) -> str:
    """Convert an m:oMath XML element to a LaTeX string."""
    return _convert_element(omath_el).strip()


def _convert_element(el: etree._Element) -> str:
    tag = _local(el.tag)
    handler = _HANDLERS.get(tag)
    if handler:
        return handler(el)
    return _convert_children(el)


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _convert_children(el: etree._Element) -> str:
    parts: list[str] = []
    for child in el:
        parts.append(_convert_element(child))
    return "".join(parts)


def _handle_r(el: etree._Element) -> str:
    """m:r — run of text."""
    parts: list[str] = []
    is_normal = False
    rpr = el.find(_mt("rPr"))
    if rpr is not None:
        sty = rpr.find(_mt("sty"))
        if sty is not None and sty.get(_mt("val"), sty.get("val", "")) == "p":
            is_normal = True
    for child in el:
        if _local(child.tag) == "t" and child.text:
            text = child.text
            converted = _convert_text(text)
            if is_normal and converted == text and len(text) > 1:
                parts.append(r"\mathrm{" + converted + "}")
            else:
                parts.append(converted)
    return "".join(parts)


def _convert_text(text: str) -> str:
    result: list[str] = []
    for ch in text:
        if ch in _UNICODE_TO_LATEX:
            if result and result[-1] and result[-1][-1].isalpha():
                result.append(" ")
            result.append(_UNICODE_TO_LATEX[ch])
        else:
            result.append(ch)
    return "".join(result)


def _handle_sSup(el: etree._Element) -> str:
    """m:sSup — superscript."""
    e = el.find(_mt("e"))
    sup = el.find(_mt("sup"))
    base = _convert_children(e) if e is not None else ""
    exp = _convert_children(sup) if sup is not None else ""
    if len(exp) == 1:
        return f"{base}^{exp}"
    return f"{base}^{{{exp}}}"


def _handle_sSub(el: etree._Element) -> str:
    """m:sSub — subscript."""
    e = el.find(_mt("e"))
    sub = el.find(_mt("sub"))
    base = _convert_children(e) if e is not None else ""
    idx = _convert_children(sub) if sub is not None else ""
    if len(idx) == 1:
        return f"{base}_{idx}"
    return f"{base}_{{{idx}}}"


def _handle_sSubSup(el: etree._Element) -> str:
    """m:sSubSup — subscript + superscript."""
    e = el.find(_mt("e"))
    sub = el.find(_mt("sub"))
    sup = el.find(_mt("sup"))
    base = _convert_children(e) if e is not None else ""
    idx = _convert_children(sub) if sub is not None else ""
    exp = _convert_children(sup) if sup is not None else ""
    return f"{base}_{{{idx}}}^{{{exp}}}"


def _handle_f(el: etree._Element) -> str:
    """m:f — fraction."""
    num = el.find(_mt("num"))
    den = el.find(_mt("den"))
    n = _convert_children(num) if num is not None else ""
    d = _convert_children(den) if den is not None else ""
    fpr = el.find(_mt("fPr"))
    if fpr is not None:
        typ = fpr.find(_mt("type"))
        if typ is not None:
            val = typ.get(_mt("val"), typ.get("val", ""))
            if val == "lin":
                return f"{n}/{d}"
            if val == "noBar":
                return rf"\binom{{{n}}}{{{d}}}"
    return rf"\frac{{{n}}}{{{d}}}"


def _handle_rad(el: etree._Element) -> str:
    """m:rad — radical (sqrt, nth root)."""
    deg = el.find(_mt("deg"))
    e = el.find(_mt("e"))
    body = _convert_children(e) if e is not None else ""
    deg_hide = False
    pr = el.find(_mt("radPr"))
    if pr is not None:
        dh = pr.find(_mt("degHide"))
        if dh is not None:
            val = dh.get(_mt("val"), dh.get("val", ""))
            if val in ("1", "on", "true"):
                deg_hide = True
    if deg_hide or deg is None:
        return rf"\sqrt{{{body}}}"
    deg_text = _convert_children(deg)
    if not deg_text.strip():
        return rf"\sqrt{{{body}}}"
    return rf"\sqrt[{deg_text}]{{{body}}}"


def _handle_d(el: etree._Element) -> str:
    """m:d — delimiter (parentheses, brackets, etc.)."""
    beg_chr = "("
    end_chr = ")"
    dpr = el.find(_mt("dPr"))
    if dpr is not None:
        bc = dpr.find(_mt("begChr"))
        if bc is not None:
            beg_chr = bc.get(_mt("val"), bc.get("val", "("))
        ec = dpr.find(_mt("endChr"))
        if ec is not None:
            end_chr = ec.get(_mt("val"), ec.get("val", ")"))
    parts: list[str] = []
    for e_el in el.findall(_mt("e")):
        parts.append(_convert_children(e_el))
    inner = ", ".join(parts) if len(parts) > 1 else (parts[0] if parts else "")
    left = _delim_to_latex(beg_chr, is_left=True)
    right = _delim_to_latex(end_chr, is_left=False)
    return f"{left}{inner}{right}"


def _delim_to_latex(ch: str, *, is_left: bool) -> str:
    if not ch or ch == "":
        return ""
    special = {"{": r"\{", "}": r"\}", "⌊": r"\lfloor", "⌋": r"\rfloor",
               "⌈": r"\lceil", "⌉": r"\rceil", "⟨": r"\langle", "⟩": r"\rangle",
               "‖": r"\|", "|": "|"}
    if ch in special:
        return rf"\left{special[ch]}" if is_left else rf"\right{special[ch]}"
    return rf"\left{ch}" if is_left else rf"\right{ch}"


def _handle_nary(el: etree._Element) -> str:
    """m:nary — n-ary operator (sum, integral, etc.)."""
    pr = el.find(_mt("naryPr"))
    chr_val = "∫"
    if pr is not None:
        c = pr.find(_mt("chr"))
        if c is not None:
            chr_val = c.get(_mt("val"), c.get("val", "∫"))
    op = _NARY_CHAR_TO_LATEX.get(chr_val, chr_val)
    sub_el = el.find(_mt("sub"))
    sup_el = el.find(_mt("sup"))
    e_el = el.find(_mt("e"))
    sub_text = _convert_children(sub_el) if sub_el is not None else ""
    sup_text = _convert_children(sup_el) if sup_el is not None else ""
    body = _convert_children(e_el) if e_el is not None else ""
    result = op
    if sub_text.strip():
        result += f"_{{{sub_text}}}"
    if sup_text.strip():
        result += f"^{{{sup_text}}}"
    if body.strip():
        result += f" {body}"
    return result


def _handle_bar(el: etree._Element) -> str:
    """m:bar — overbar or underbar."""
    pr = el.find(_mt("barPr"))
    pos_val = "top"
    if pr is not None:
        pos = pr.find(_mt("pos"))
        if pos is not None:
            pos_val = pos.get(_mt("val"), pos.get("val", "top"))
    e = el.find(_mt("e"))
    body = _convert_children(e) if e is not None else ""
    if pos_val == "bot":
        return rf"\underline{{{body}}}"
    return rf"\overline{{{body}}}"


def _handle_acc(el: etree._Element) -> str:
    """m:acc — accent (hat, vec, dot, etc.)."""
    pr = el.find(_mt("accPr"))
    chr_val = "̂"
    if pr is not None:
        c = pr.find(_mt("chr"))
        if c is not None:
            chr_val = c.get(_mt("val"), c.get("val", "̂"))
    cmd = _ACCENT_CHAR_TO_LATEX.get(chr_val, r"\hat")
    e = el.find(_mt("e"))
    body = _convert_children(e) if e is not None else ""
    return f"{cmd}{{{body}}}"


def _handle_func(el: etree._Element) -> str:
    """m:func — function application (sin, cos, lim, etc.)."""
    fname = el.find(_mt("fName"))
    e = el.find(_mt("e"))
    name = _convert_children(fname) if fname is not None else ""
    body = _convert_children(e) if e is not None else ""
    name = name.strip()
    known_funcs = {"sin", "cos", "tan", "cot", "sec", "csc",
                   "log", "ln", "exp", "lim", "min", "max",
                   "inf", "sup", "det", "dim", "gcd", "deg"}
    if name in known_funcs:
        return rf"\{name} {body}"
    if name:
        return rf"\operatorname{{{name}}} {body}"
    return body


def _handle_limLow(el: etree._Element) -> str:
    """m:limLow — lower limit."""
    e = el.find(_mt("e"))
    lim = el.find(_mt("lim"))
    base = _convert_children(e) if e is not None else ""
    limit = _convert_children(lim) if lim is not None else ""
    return f"{base}_{{{limit}}}"


def _handle_limUpp(el: etree._Element) -> str:
    """m:limUpp — upper limit."""
    e = el.find(_mt("e"))
    lim = el.find(_mt("lim"))
    base = _convert_children(e) if e is not None else ""
    limit = _convert_children(lim) if lim is not None else ""
    return f"{base}^{{{limit}}}"


def _handle_eqArr(el: etree._Element) -> str:
    """m:eqArr — equation array (aligned)."""
    rows: list[str] = []
    for e_el in el.findall(_mt("e")):
        rows.append(_convert_children(e_el))
    return r"\begin{aligned}" + r" \\ ".join(rows) + r"\end{aligned}"


def _handle_m(el: etree._Element) -> str:
    """m:m — matrix."""
    rows: list[str] = []
    for mr in el.findall(_mt("mr")):
        cols: list[str] = []
        for e_el in mr.findall(_mt("e")):
            cols.append(_convert_children(e_el))
        rows.append(" & ".join(cols))
    return r"\begin{matrix}" + r" \\ ".join(rows) + r"\end{matrix}"


def _handle_groupChr(el: etree._Element) -> str:
    """m:groupChr — group character (underbrace, overbrace)."""
    pr = el.find(_mt("groupChrPr"))
    chr_val = "⏟"
    pos_val = "bot"
    if pr is not None:
        c = pr.find(_mt("chr"))
        if c is not None:
            chr_val = c.get(_mt("val"), c.get("val", "⏟"))
        p = pr.find(_mt("pos"))
        if p is not None:
            pos_val = p.get(_mt("val"), p.get("val", "bot"))
    e = el.find(_mt("e"))
    body = _convert_children(e) if e is not None else ""
    if chr_val == "⏟" or pos_val == "bot":
        return rf"\underbrace{{{body}}}"
    return rf"\overbrace{{{body}}}"


def _handle_borderBox(el: etree._Element) -> str:
    """m:borderBox — boxed expression."""
    e = el.find(_mt("e"))
    body = _convert_children(e) if e is not None else ""
    return rf"\boxed{{{body}}}"


def _handle_sPre(el: etree._Element) -> str:
    """m:sPre — pre-subscript/superscript."""
    sub = el.find(_mt("sub"))
    sup = el.find(_mt("sup"))
    e = el.find(_mt("e"))
    base = _convert_children(e) if e is not None else ""
    idx = _convert_children(sub) if sub is not None else ""
    exp = _convert_children(sup) if sup is not None else ""
    return f"{{}}_{{{idx}}}^{{{exp}}}{base}"


def _skip(_el: etree._Element) -> str:
    return ""


_HANDLERS: dict[str, any] = {
    "r": _handle_r,
    "sSup": _handle_sSup,
    "sSub": _handle_sSub,
    "sSubSup": _handle_sSubSup,
    "f": _handle_f,
    "rad": _handle_rad,
    "d": _handle_d,
    "nary": _handle_nary,
    "bar": _handle_bar,
    "acc": _handle_acc,
    "func": _handle_func,
    "limLow": _handle_limLow,
    "limUpp": _handle_limUpp,
    "eqArr": _handle_eqArr,
    "m": _handle_m,
    "groupChr": _handle_groupChr,
    "borderBox": _handle_borderBox,
    "sPre": _handle_sPre,
    "oMath": _convert_children,
    "oMathPara": _convert_children,
    "e": _convert_children,
    "num": _convert_children,
    "den": _convert_children,
    "deg": _convert_children,
    "sub": _convert_children,
    "sup": _convert_children,
    "lim": _convert_children,
    "fName": _convert_children,
    # Skip property elements
    "sSupPr": _skip,
    "sSubPr": _skip,
    "sSubSupPr": _skip,
    "fPr": _skip,
    "radPr": _skip,
    "dPr": _skip,
    "naryPr": _skip,
    "barPr": _skip,
    "accPr": _skip,
    "funcPr": _skip,
    "limLowPr": _skip,
    "limUppPr": _skip,
    "eqArrPr": _skip,
    "mPr": _skip,
    "groupChrPr": _skip,
    "borderBoxPr": _skip,
    "sPrePr": _skip,
    "ctrlPr": _skip,
    "rPr": _skip,
    "oMathParaPr": _skip,
}
