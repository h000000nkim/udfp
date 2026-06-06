"""M2: latex_to_omml 단위 테스트."""

from __future__ import annotations

from lxml import etree

from udf.renderers.docx.latex_to_omml import latex_to_omml, latex_to_omml_para


def _xml_str(el: etree._Element) -> str:
    return etree.tostring(el, encoding="unicode")


class TestLatexToOmml:
    def test_simple_variable(self):
        result = latex_to_omml("x")
        assert "oMath" in result.tag
        xml = _xml_str(result)
        assert "x" in xml

    def test_fraction(self):
        result = latex_to_omml(r"\frac{a}{b}")
        xml = _xml_str(result)
        assert "<m:f>" in xml or "<m:f " in xml

    def test_sqrt(self):
        result = latex_to_omml(r"\sqrt{x}")
        xml = _xml_str(result)
        assert "<m:rad>" in xml or "<m:rad " in xml

    def test_superscript(self):
        result = latex_to_omml("x^2")
        xml = _xml_str(result)
        assert "<m:sSup>" in xml or "<m:sSup " in xml

    def test_subscript(self):
        result = latex_to_omml("x_i")
        xml = _xml_str(result)
        assert "<m:sSub>" in xml or "<m:sSub " in xml

    def test_greek_letter(self):
        result = latex_to_omml(r"\alpha + \beta")
        xml = _xml_str(result)
        assert "α" in xml
        assert "β" in xml

    def test_integral(self):
        result = latex_to_omml(r"\int_0^1 f(x) dx")
        xml = _xml_str(result)
        assert "<m:nary>" in xml or "<m:nary " in xml or "∫" in xml

    def test_empty_input(self):
        result = latex_to_omml("")
        assert "oMath" in result.tag


class TestLatexToOmmlPara:
    def test_wraps_in_omath_para(self):
        result = latex_to_omml_para("E=mc^2")
        assert "oMathPara" in result.tag
        children = list(result)
        assert any("oMath" in c.tag for c in children)
