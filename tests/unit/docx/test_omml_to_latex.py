"""A1: omml_to_latex 역변환 단위 테스트 + latex↔omml 라운드트립."""

from __future__ import annotations

from lxml import etree

from udf.parsers.docx.omml_to_latex import omml_to_latex
from udf.renderers.docx.latex_to_omml import latex_to_omml

_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _omath(*children: etree._Element) -> etree._Element:
    root = etree.Element(f"{{{_M}}}oMath", nsmap={"m": _M})
    for c in children:
        root.append(c)
    return root


def _run(text: str) -> etree._Element:
    r = etree.SubElement(etree.Element("dummy"), f"{{{_M}}}r")
    t = etree.SubElement(r, f"{{{_M}}}t")
    t.text = text
    return r


def _frac(num_text: str, den_text: str) -> etree._Element:
    f = etree.Element(f"{{{_M}}}f")
    num = etree.SubElement(f, f"{{{_M}}}num")
    num.append(_run(num_text))
    den = etree.SubElement(f, f"{{{_M}}}den")
    den.append(_run(den_text))
    return f


def _ssup(base_text: str, exp_text: str) -> etree._Element:
    s = etree.Element(f"{{{_M}}}sSup")
    e = etree.SubElement(s, f"{{{_M}}}e")
    e.append(_run(base_text))
    sup = etree.SubElement(s, f"{{{_M}}}sup")
    sup.append(_run(exp_text))
    return s


def _ssub(base_text: str, idx_text: str) -> etree._Element:
    s = etree.Element(f"{{{_M}}}sSub")
    e = etree.SubElement(s, f"{{{_M}}}e")
    e.append(_run(base_text))
    sub = etree.SubElement(s, f"{{{_M}}}sub")
    sub.append(_run(idx_text))
    return s


def _rad(deg_text: str | None, base_text: str) -> etree._Element:
    rad = etree.Element(f"{{{_M}}}rad")
    pr = etree.SubElement(rad, f"{{{_M}}}radPr")
    if deg_text is None:
        hide = etree.SubElement(pr, f"{{{_M}}}degHide")
        hide.set(f"{{{_M}}}val", "1")
    deg = etree.SubElement(rad, f"{{{_M}}}deg")
    if deg_text:
        deg.append(_run(deg_text))
    e = etree.SubElement(rad, f"{{{_M}}}e")
    e.append(_run(base_text))
    return rad


class TestOmmlToLatexBasic:
    def test_plain_text(self):
        omath = _omath(_run("x"))
        assert omml_to_latex(omath) == "x"

    def test_fraction(self):
        omath = _omath(_frac("a", "b"))
        result = omml_to_latex(omath)
        assert r"\frac" in result
        assert "a" in result
        assert "b" in result

    def test_superscript(self):
        omath = _omath(_ssup("x", "2"))
        result = omml_to_latex(omath)
        assert "x" in result
        assert "^" in result
        assert "2" in result

    def test_subscript(self):
        omath = _omath(_ssub("x", "i"))
        result = omml_to_latex(omath)
        assert "x" in result
        assert "_" in result
        assert "i" in result

    def test_sqrt(self):
        omath = _omath(_rad(None, "x"))
        result = omml_to_latex(omath)
        assert r"\sqrt" in result
        assert "x" in result

    def test_greek_letter(self):
        omath = _omath(_run("α"))
        result = omml_to_latex(omath)
        assert r"\alpha" in result

    def test_empty_omath(self):
        omath = _omath()
        assert omml_to_latex(omath) == ""


class TestOmmlLatexRoundtrip:
    """latex → omml → latex 라운드트립: 의미적 동등성 검증."""

    def _roundtrip(self, latex: str) -> str:
        omml_el = latex_to_omml(latex)
        return omml_to_latex(omml_el)

    def test_simple_var(self):
        assert "x" in self._roundtrip("x")

    def test_fraction_roundtrip(self):
        result = self._roundtrip(r"\frac{a}{b}")
        assert r"\frac" in result
        assert "a" in result and "b" in result

    def test_superscript_roundtrip(self):
        result = self._roundtrip("x^2")
        assert "x" in result and "2" in result and "^" in result

    def test_subscript_roundtrip(self):
        result = self._roundtrip("x_i")
        assert "x" in result and "i" in result and "_" in result

    def test_greek_roundtrip(self):
        result = self._roundtrip(r"\alpha + \beta")
        assert r"\alpha" in result
        assert r"\beta" in result

    def test_sqrt_roundtrip(self):
        result = self._roundtrip(r"\sqrt{x}")
        assert r"\sqrt" in result
        assert "x" in result
