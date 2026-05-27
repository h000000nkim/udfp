"""HWP 수식 파서 단위 테스트 — 스펙 revision 1.3 전체 커버리지"""

import struct

from udf.schema import EquationBlock
from udf.pipeline.verbatim import GlobalResources
from udf.parsers.hwp.body import parse_section
from udf.parsers.hwp.doc_info import DocInfoResult
from udf.parsers.hwp.equation import (
    EqBigg,
    EqCases,
    EqChoose,
    EqColor,
    EqDeco,
    EqDelimited,
    EqFont,
    EqFrac,
    EqFunc,
    EqGroup,
    EqLeftScript,
    EqMatrix,
    EqNewline,
    EqNot,
    EqPile,
    EqRel,
    EqScript,
    EqSpace,
    EqSqrt,
    EqSymbol,
    EqText,
    hwp_script_to_latex,
    parse,
    to_latex,
    tokenize,
)
from udf.parsers.hwp.records import (
    HWPTAG_CTRL_HEADER,
    HWPTAG_EQEDIT,
    HWPTAG_LIST_HEADER,
    HwpRecord,
)


def _make_record(tag_id: int, level: int, payload: bytes) -> bytes:
    size = len(payload)
    header = (tag_id & 0x3FF) | ((level & 0x3FF) << 10) | (min(size, 0xFFE) << 20)
    return struct.pack("<I", header) + payload


def _ctrl_header_payload(ctrl_id: str) -> bytes:
    buf = bytearray(12)
    buf[0:4] = ctrl_id.encode("ascii")[::-1]
    return bytes(buf)


def _eqedit_payload(script: str) -> bytes:
    encoded = script.encode("utf-16-le")
    char_count = len(script)
    return struct.pack("<IH", 0, char_count) + encoded


# ═══════════════════════════════════════════════════════════════════════
# 토크나이저
# ═══════════════════════════════════════════════════════════════════════


class TestTokenizer:
    def test_simple(self) -> None:
        assert tokenize("x^2") == ["x", "^", "2"]

    def test_braces(self) -> None:
        assert tokenize("{a+b} over {c}") == ["{", "a", "+", "b", "}", "over", "{", "c", "}"]

    def test_tilde_backtick(self) -> None:
        tokens = tokenize("a ~ b ` c")
        assert "~" in tokens
        assert "`" in tokens

    def test_quoted_long_word(self) -> None:
        tokens = tokenize('"longwordhere" + x')
        assert "longwordhere" in tokens

    def test_hash_newline(self) -> None:
        tokens = tokenize("a # b")
        assert "#" in tokens

    def test_arrow(self) -> None:
        assert "->" in tokenize("x -> y")

    def test_double_arrow(self) -> None:
        assert "<->" in tokenize("A <-> B")

    def test_nine_char_split(self) -> None:
        """9자 초과 단어 자동 분리."""
        tokens = tokenize("abcdefghijkl")
        assert tokens == ["abcdefghi", "jkl"]

    def test_quoted_preserves_long(self) -> None:
        """큰따옴표로 묶으면 9자 규칙 무시."""
        tokens = tokenize('"abcdefghijkl"')
        assert tokens == ["abcdefghijkl"]

    def test_ampersand(self) -> None:
        tokens = tokenize("a & b")
        assert "&" in tokens

    def test_multi_char_operators(self) -> None:
        assert "=>" in tokenize("A => B")
        assert "!=" in tokenize("a != b")
        assert "==" in tokenize("a == b")
        assert "<<" in tokenize("a << b")
        assert ">>" in tokenize("a >> b")


# ═══════════════════════════════════════════════════════════════════════
# AST 파서
# ═══════════════════════════════════════════════════════════════════════


class TestParser:
    def test_simple_text(self) -> None:
        ast = parse("x")
        assert isinstance(ast, EqText)
        assert ast.text == "x"

    def test_superscript(self) -> None:
        ast = parse("x ^ 2")
        assert isinstance(ast, EqScript)
        assert ast.sup is not None

    def test_subscript(self) -> None:
        ast = parse("H _ 2")
        assert isinstance(ast, EqScript)
        assert ast.sub is not None

    def test_both_scripts(self) -> None:
        """x _ {a} ^ b — 중괄호로 아래첨자 범위를 명시해야 양쪽 첨자."""
        ast = parse("x _ {a} ^ b")
        assert isinstance(ast, EqScript)
        assert ast.sub is not None
        assert ast.sup is not None

    def test_fraction_over(self) -> None:
        ast = parse("a over b")
        assert isinstance(ast, EqFrac)
        assert ast.has_line is True

    def test_fraction_atop(self) -> None:
        ast = parse("x atop y")
        assert isinstance(ast, EqFrac)
        assert ast.has_line is False

    def test_grouped_fraction(self) -> None:
        ast = parse("{a+b} over {c+d}")
        assert isinstance(ast, EqFrac)

    def test_sqrt(self) -> None:
        ast = parse("sqrt 2")
        assert isinstance(ast, EqSqrt)

    def test_sqrt_group(self) -> None:
        ast = parse("sqrt {x+1}")
        assert isinstance(ast, EqSqrt)

    def test_decoration_hat(self) -> None:
        ast = parse("hat x")
        assert isinstance(ast, EqDeco)
        assert ast.kind == "hat"

    def test_decoration_bar(self) -> None:
        ast = parse("bar A")
        assert isinstance(ast, EqDeco)
        assert ast.kind == "bar"

    def test_decoration_vec(self) -> None:
        ast = parse("vec v")
        assert isinstance(ast, EqDeco)
        assert ast.kind == "vec"

    def test_greek_symbol(self) -> None:
        ast = parse("alpha")
        assert isinstance(ast, EqSymbol)
        assert ast.name == "alpha"

    def test_function(self) -> None:
        ast = parse("sin")
        assert isinstance(ast, EqFunc)
        assert ast.name == "sin"

    def test_newline(self) -> None:
        ast = parse("a # b")
        assert isinstance(ast, EqGroup)
        has_newline = any(isinstance(c, EqNewline) for c in ast.children)
        assert has_newline

    def test_space(self) -> None:
        ast = parse("a ~ b")
        assert isinstance(ast, EqGroup)
        has_space = any(isinstance(c, EqSpace) for c in ast.children)
        assert has_space

    def test_left_right(self) -> None:
        ast = parse("LEFT ( a + b RIGHT )")
        assert isinstance(ast, EqDelimited)
        assert ast.left == "("
        assert ast.right == ")"

    def test_matrix(self) -> None:
        ast = parse("matrix{a & b # c & d}")
        assert isinstance(ast, EqMatrix)
        assert len(ast.rows) == 2
        assert len(ast.rows[0]) == 2

    def test_pmatrix(self) -> None:
        ast = parse("pmatrix{1 & 0 # 0 & 1}")
        assert isinstance(ast, EqMatrix)
        assert ast.style == "paren"

    def test_bmatrix(self) -> None:
        ast = parse("bmatrix{a & b # c & d}")
        assert isinstance(ast, EqMatrix)
        assert ast.style == "bracket"

    def test_dmatrix(self) -> None:
        ast = parse("dmatrix{a & b # c & d}")
        assert isinstance(ast, EqMatrix)
        assert ast.style == "det"

    def test_cases(self) -> None:
        ast = parse("cases{2x+y=4 # 3x-4y=-1}")
        assert isinstance(ast, EqCases)
        assert len(ast.rows) == 2

    def test_pile(self) -> None:
        ast = parse("pile{a # b # c}")
        assert isinstance(ast, EqPile)
        assert len(ast.rows) == 3
        assert ast.align == "center"

    def test_lpile(self) -> None:
        ast = parse("lpile{x # y}")
        assert isinstance(ast, EqPile)
        assert ast.align == "left"

    def test_rpile(self) -> None:
        ast = parse("rpile{m # n}")
        assert isinstance(ast, EqPile)
        assert ast.align == "right"

    def test_empty(self) -> None:
        ast = parse("")
        assert isinstance(ast, EqGroup)

    def test_nested_fraction_script(self) -> None:
        """중첩: 분수 안에 첨자."""
        ast = parse("{x^2} over {y_3}")
        assert isinstance(ast, EqFrac)

    def test_integral_with_limits(self) -> None:
        ast = parse("int _ 0 ^ 1 f(x)")
        assert isinstance(ast, EqGroup)

    def test_sum_with_limits(self) -> None:
        ast = parse("sum _ {i=1} ^ n")
        assert isinstance(ast, EqScript)

    def test_bigg(self) -> None:
        """Parse 'bigg (' → EqBigg with content '('.

        bigg 키워드는 다음 토큰을 확대 괄호로 처리.
        """
        ast = parse("bigg (")
        assert isinstance(ast, EqBigg)
        assert isinstance(ast.content, EqText)
        assert ast.content.text == "("

    def test_not(self) -> None:
        """Parse 'not =' → EqNot with content '='.

        not 키워드는 다음 문자에 취소선(부정) 적용.
        """
        ast = parse("not =")
        assert isinstance(ast, EqNot)
        assert isinstance(ast.content, EqText)
        assert ast.content.text == "="

    def test_font_rm(self) -> None:
        """Parse 'rm ABC' → EqFont(style='rm') with content text 'ABC'.

        rm 키워드는 roman(직립) 폰트 스타일 적용.
        """
        ast = parse("rm ABC")
        assert isinstance(ast, EqFont)
        assert ast.style == "rm"
        assert isinstance(ast.content, EqText)
        assert ast.content.text == "ABC"

    def test_font_bold(self) -> None:
        """Parse 'bold X' → EqFont(style='bold').

        bold 키워드는 굵은 폰트 스타일 적용.
        """
        ast = parse("bold X")
        assert isinstance(ast, EqFont)
        assert ast.style == "bold"

    def test_color(self) -> None:
        """Parse 'COLOR {255,0,0} {red}' → EqColor(r=255, g=0, b=0).

        COLOR 키워드는 RGB 색상 지정. 첫 인자가 R,G,B 값.
        """
        ast = parse("COLOR {255,0,0} {red}")
        assert isinstance(ast, EqColor)
        assert ast.r == 255
        assert ast.g == 0
        assert ast.b == 0

    def test_choose(self) -> None:
        """Parse 'CHOOSE k' → EqChoose node.

        CHOOSE는 조합(nCk) 표기 생성.
        """
        ast = parse("CHOOSE k")
        assert isinstance(ast, EqChoose)

    def test_eqalign(self) -> None:
        """Parse 'EQALIGN {x & = & 1 # y & = & 2}' → EqMatrix(2 rows x 3 cols).

        EQALIGN은 정렬 행렬. &로 열 구분, #으로 행 구분.
        """
        ast = parse("EQALIGN {x & = & 1 # y & = & 2}")
        assert isinstance(ast, EqMatrix)
        assert len(ast.rows) == 2
        assert len(ast.rows[0]) == 3

    # ──── from/to 대체 구문 ────

    def test_from_to_integral(self) -> None:
        """스펙 §2.3: int from 0 to 3 → ∫₀³"""
        ast = parse("int from 0 to 3")
        assert isinstance(ast, EqScript)
        assert ast.sub is not None
        assert ast.sup is not None

    def test_from_to_sum(self) -> None:
        ast = parse("sum from {i=1} to n")
        assert isinstance(ast, EqScript)
        assert ast.sub is not None
        assert ast.sup is not None

    def test_from_only(self) -> None:
        ast = parse("int from 0")
        assert isinstance(ast, EqScript)
        assert ast.sub is not None
        assert ast.sup is None

    def test_to_only(self) -> None:
        ast = parse("sum to N")
        assert isinstance(ast, EqScript)
        assert ast.sub is None
        assert ast.sup is not None

    # ──── 중위(infix) CHOOSE/BINOM ────

    def test_choose_infix(self) -> None:
        """스펙: [전체항] CHOOSE [선택항]"""
        ast = parse("n CHOOSE k")
        assert isinstance(ast, EqChoose)
        assert isinstance(ast.n, EqText)
        assert ast.n.text == "n"
        assert isinstance(ast.k, EqText)
        assert ast.k.text == "k"

    def test_binom_infix(self) -> None:
        ast = parse("{n+1} BINOM {r}")
        assert isinstance(ast, EqChoose)

    def test_choose_prefix_fallback(self) -> None:
        """CHOOSE가 줄 맨 앞에 오면 전위(prefix)로 처리."""
        ast = parse("CHOOSE k")
        assert ast is not None

    # ──── 중위 LSUB/LSUP ────

    def test_lsub_infix(self) -> None:
        """스펙: x LSUB y → 왼쪽 아래첨자."""
        ast = parse("x LSUB y")
        assert isinstance(ast, EqLeftScript)
        assert isinstance(ast.base, EqText)
        assert ast.base.text == "x"
        assert ast.lsub is not None

    def test_lsup_infix(self) -> None:
        """스펙: x LSUP y → 왼쪽 윗첨자."""
        ast = parse("x LSUP y")
        assert isinstance(ast, EqLeftScript)
        assert isinstance(ast.base, EqText)
        assert ast.base.text == "x"
        assert ast.lsup is not None

    # ──── 중위 REL/BUILDREL ────

    def test_rel_infix(self) -> None:
        """스펙: A REL <-> {+2} {-5} B → 화살표 위 아래 주석."""
        ast = parse("A REL <-> {+2} {-5}")
        assert isinstance(ast, EqRel)
        assert isinstance(ast.left, EqText)
        assert ast.left.text == "A"
        assert ast.top is not None
        assert ast.bottom is not None

    def test_buildrel_infix(self) -> None:
        ast = parse("A BUILDREL <-> {+2}")
        assert isinstance(ast, EqRel)
        assert isinstance(ast.left, EqText)
        assert ast.left.text == "A"
        assert ast.bottom is None


# ═══════════════════════════════════════════════════════════════════════
# LaTeX 변환
# ═══════════════════════════════════════════════════════════════════════


class TestHwpScriptToLatex:
    def test_fraction(self) -> None:
        result = hwp_script_to_latex("a over b")
        assert r"\frac" in result
        assert "a" in result
        assert "b" in result

    def test_grouped_fraction(self) -> None:
        result = hwp_script_to_latex("{a+b} over {c+d}")
        assert r"\frac" in result
        assert "a+b" in result or ("a" in result and "b" in result)

    def test_sqrt(self) -> None:
        result = hwp_script_to_latex("sqrt 2")
        assert r"\sqrt" in result

    def test_sqrt_group(self) -> None:
        result = hwp_script_to_latex("sqrt {x+1}")
        assert r"\sqrt" in result

    def test_superscript(self) -> None:
        result = hwp_script_to_latex("x ^ 2")
        assert "^" in result
        assert "2" in result

    def test_subscript(self) -> None:
        result = hwp_script_to_latex("H _ 2")
        assert "_" in result

    def test_integral(self) -> None:
        result = hwp_script_to_latex("int _ 0 ^ 1 f(x) dx")
        assert r"\int" in result

    def test_sum(self) -> None:
        result = hwp_script_to_latex("sum _ {i=1} ^ n")
        assert r"\sum" in result

    def test_greek_lower(self) -> None:
        result = hwp_script_to_latex("alpha + beta")
        assert r"\alpha" in result
        assert r"\beta" in result

    def test_greek_upper(self) -> None:
        result = hwp_script_to_latex("Gamma + Delta")
        assert r"\Gamma" in result
        assert r"\Delta" in result

    def test_limit(self) -> None:
        result = hwp_script_to_latex("lim _ {x -> 0}")
        assert r"\lim" in result
        assert r"\rightarrow" in result

    def test_hat_decoration(self) -> None:
        result = hwp_script_to_latex("hat x")
        assert r"\widehat" in result

    def test_bar_decoration(self) -> None:
        result = hwp_script_to_latex("bar A")
        assert r"\overline" in result

    def test_vec_decoration(self) -> None:
        result = hwp_script_to_latex("vec v")
        assert r"\overrightarrow" in result

    def test_trig_function(self) -> None:
        result = hwp_script_to_latex("sin theta")
        assert r"\sin" in result
        assert r"\theta" in result

    def test_tilde_space(self) -> None:
        result = hwp_script_to_latex("a ~ b")
        assert r"\ " in result

    def test_hash_newline(self) -> None:
        result = hwp_script_to_latex("a # b")
        assert r"\\" in result

    def test_infinity(self) -> None:
        result = hwp_script_to_latex("inf")
        assert r"\infty" in result

    def test_relation_leq(self) -> None:
        result = hwp_script_to_latex("a LEQ b")
        assert r"\leq" in result

    def test_relation_geq(self) -> None:
        result = hwp_script_to_latex("a GEQ b")
        assert r"\geq" in result

    def test_empty_script(self) -> None:
        assert hwp_script_to_latex("") == ""

    def test_matrix(self) -> None:
        result = hwp_script_to_latex("matrix{a & b # c & d}")
        assert r"\begin{matrix}" in result
        assert r"\end{matrix}" in result
        assert "&" in result
        assert r"\\" in result

    def test_pmatrix(self) -> None:
        result = hwp_script_to_latex("pmatrix{1 & 0 # 0 & 1}")
        assert r"\begin{pmatrix}" in result

    def test_bmatrix(self) -> None:
        result = hwp_script_to_latex("bmatrix{x & y # z & w}")
        assert r"\begin{bmatrix}" in result

    def test_dmatrix(self) -> None:
        result = hwp_script_to_latex("dmatrix{a & b # c & d}")
        assert r"\begin{vmatrix}" in result

    def test_cases(self) -> None:
        result = hwp_script_to_latex("cases{2x+y=4 # 3x-4y=-1}")
        assert r"\begin{cases}" in result
        assert r"\end{cases}" in result

    def test_pile(self) -> None:
        result = hwp_script_to_latex("pile{a # b # c}")
        assert r"\begin{gathered}" in result

    def test_left_right(self) -> None:
        result = hwp_script_to_latex("LEFT ( x + y RIGHT )")
        assert r"\left" in result
        assert r"\right" in result

    def test_times(self) -> None:
        result = hwp_script_to_latex("2 times 5")
        assert r"\times" in result

    def test_atop(self) -> None:
        result = hwp_script_to_latex("x atop y")
        assert r"\atop" in result

    def test_bigg_fraction(self) -> None:
        """스펙 예시: bigg / {x+y} over {x-y}"""
        result = hwp_script_to_latex("bigg /")
        assert r"\bigg" in result

    def test_not_equal(self) -> None:
        result = hwp_script_to_latex("not =")
        assert r"\cancel" in result

    def test_font_rm(self) -> None:
        result = hwp_script_to_latex("rm ABC")
        assert r"\mathrm" in result

    def test_font_bold(self) -> None:
        result = hwp_script_to_latex("bold X")
        assert r"\mathbf" in result

    def test_color(self) -> None:
        result = hwp_script_to_latex("COLOR {255,0,255} {3}")
        assert r"\textcolor" in result
        assert "255" in result

    def test_partial(self) -> None:
        result = hwp_script_to_latex("PARTIAL")
        assert r"\partial" in result

    def test_nabla(self) -> None:
        result = hwp_script_to_latex("NABLA")
        assert r"\nabla" in result

    def test_forall(self) -> None:
        result = hwp_script_to_latex("FORALL")
        assert r"\forall" in result

    def test_exists(self) -> None:
        result = hwp_script_to_latex("EXIST")
        assert r"\exists" in result

    def test_therefore(self) -> None:
        result = hwp_script_to_latex("THEREFORE")
        assert r"\therefore" in result

    def test_arrows(self) -> None:
        assert r"\leftarrow" in hwp_script_to_latex("larrow")
        assert r"\rightarrow" in hwp_script_to_latex("rarrow")
        assert r"\Rightarrow" in hwp_script_to_latex("RARROW")
        assert r"\Leftarrow" in hwp_script_to_latex("LARROW")
        assert r"\uparrow" in hwp_script_to_latex("uparrow")
        assert r"\downarrow" in hwp_script_to_latex("downarrow")
        assert r"\mapsto" in hwp_script_to_latex("mapsto")

    def test_dots(self) -> None:
        assert r"\cdots" in hwp_script_to_latex("cdots")
        assert r"\ldots" in hwp_script_to_latex("LDOTS")
        assert r"\vdots" in hwp_script_to_latex("VDOTS")
        assert r"\ddots" in hwp_script_to_latex("DDOTS")

    def test_set_ops(self) -> None:
        assert r"\subset" in hwp_script_to_latex("SUBSET")
        assert r"\supset" in hwp_script_to_latex("SUPSET")
        assert r"\in" in hwp_script_to_latex("IN")
        assert r"\emptyset" in hwp_script_to_latex("EMPTYSET")

    def test_quarter_space(self) -> None:
        result = hwp_script_to_latex("a ` b")
        assert r"\," in result

    def test_reserved_words(self) -> None:
        result = hwp_script_to_latex("if x for y")
        assert r"\mathrm{if}" in result
        assert r"\mathrm{for}" in result

    # ──── from/to LaTeX ────

    def test_from_to_integral_latex(self) -> None:
        """스펙 §2.3: int from 0 to 3"""
        result = hwp_script_to_latex("int from 0 to 3")
        assert r"\int" in result
        assert "_{0}" in result
        assert "^{3}" in result

    def test_from_to_sum_latex(self) -> None:
        result = hwp_script_to_latex("sum from {i=1} to n")
        assert r"\sum" in result
        assert "i" in result and "1" in result
        assert "^{n}" in result

    # ──── 중위 CHOOSE LaTeX ────

    def test_choose_infix_latex(self) -> None:
        result = hwp_script_to_latex("n CHOOSE k")
        assert r"\binom{n}{k}" == result

    def test_binom_infix_latex(self) -> None:
        result = hwp_script_to_latex("{n+1} BINOM {r}")
        assert r"\binom" in result
        assert "n" in result and "1" in result and "r" in result

    # ──── 중위 LSUB/LSUP LaTeX ────

    def test_lsub_infix_latex(self) -> None:
        result = hwp_script_to_latex("x LSUB y")
        assert "{}_{y}" in result
        assert "x" in result

    def test_lsup_infix_latex(self) -> None:
        result = hwp_script_to_latex("x LSUP y")
        assert "{}^{y}" in result
        assert "x" in result

    # ──── 중위 REL LaTeX ────

    def test_rel_infix_latex(self) -> None:
        result = hwp_script_to_latex("A REL <-> {+2} {-5}")
        assert r"\overset" in result
        assert r"\underset" in result
        assert "A" in result

    def test_buildrel_infix_latex(self) -> None:
        result = hwp_script_to_latex("A BUILDREL <-> {+2}")
        assert r"\overset" in result
        assert "A" in result

    # ──── udarrow ────

    def test_udarrow(self) -> None:
        assert r"\updownarrow" in hwp_script_to_latex("udarrow")

    # ──── 화학식 (스펙 §1.1.3 예시) ────

    def test_chemistry_formula(self) -> None:
        """rm 2H_2 O = 2H_2 + O_2 (스펙 §1.1.3)."""
        result = hwp_script_to_latex("rm 2H_2")
        assert r"\mathrm" in result

    # ──── 스펙 §2 예제 검증 ────

    def test_spec_example_fraction(self) -> None:
        """스펙 §2.1: 1 over 2"""
        result = hwp_script_to_latex("1 over 2")
        assert r"\frac{1}{2}" in result

    def test_spec_example_demorgan(self) -> None:
        """스펙 §2.2: De Morgan's 법칙"""
        result = hwp_script_to_latex("bar {A UNION B} = bar A INTER bar B")
        assert r"\overline" in result
        assert r"\bigcup" in result or r"\cup" in result

    def test_spec_example_power_root(self) -> None:
        """스펙 §2.3: 거듭제곱근 — x^{n-1} + sqrt{y}"""
        result = hwp_script_to_latex("x ^ {n-1} + sqrt {y}")
        assert "^" in result
        assert r"\sqrt" in result

    def test_spec_example_matrix(self) -> None:
        """스펙 §2.4: 간단한 행렬"""
        result = hwp_script_to_latex(
            "matrix{a_{1}&b_{1}&c_{1} # a_{2}&b_{2}&c_{2} # a_{3}&b_{3}&c_{3}}"
        )
        assert r"\begin{matrix}" in result
        assert "&" in result

    def test_spec_example_limit_sum(self) -> None:
        """스펙 §2.5: 극한과 총합"""
        result = hwp_script_to_latex("lim _ {n -> inf} sum _ {k=1} ^ n a_k")
        assert r"\lim" in result
        assert r"\sum" in result
        assert r"\infty" in result

    def test_spec_example_demorgan_full(self) -> None:
        """스펙 §2.2: (A UNION B)^C = A^C INTER B^C"""
        result = hwp_script_to_latex(
            "(A UNION B) ^ C = A ^ C INTER B ^ C"
        )
        assert r"\bigcup" in result or r"\cup" in result
        assert r"\bigcap" in result or r"\cap" in result

    def test_spec_from_to_cube_root(self) -> None:
        """스펙 §2.3: int from 0 to 3 ^3 sqrt{x^2 +1}dx"""
        result = hwp_script_to_latex("int from 0 to 3 ^ 3 sqrt {x ^ 2 +1} dx")
        assert r"\int" in result
        assert r"\sqrt" in result

    def test_spec_bigg_example(self) -> None:
        """스펙 §1.2: {a+b} over {a-b} bigg / {x+y} over {x-y}"""
        result = hwp_script_to_latex("{a+b} over {a-b} bigg / {x+y} over {x-y}")
        assert r"\frac" in result
        assert r"\bigg" in result

    def test_spec_lim_arrow_inf(self) -> None:
        """스펙 §1.2: y= lim _{x -> 0} {1} over {x}"""
        result = hwp_script_to_latex("y= lim _ {x -> 0} {1} over {x}")
        assert r"\lim" in result
        assert r"\rightarrow" in result
        assert r"\frac" in result

    def test_spec_smallunion_inter(self) -> None:
        """스펙 §1.2: U=(A SMALLUNION B) SMALLINTER C"""
        result = hwp_script_to_latex("U=(A SMALL UNION B) SMALL INTER C")
        assert r"\bigcup" in result or r"\cup" in result

    def test_spec_sum_bounds(self) -> None:
        """스펙 §1.2: sum_{x=0} ^{inf}"""
        result = hwp_script_to_latex("sum _ {x=0} ^ {inf}")
        assert r"\sum" in result
        assert r"\infty" in result

    def test_spec_matrix_full(self) -> None:
        """스펙 §2.4: X = bmatrix{42&52&48&58 # 4&5&4&3}"""
        result = hwp_script_to_latex(
            "X = bmatrix { 42 & 52 & 48 & 58 # 4 & 5 & 4 & 3 }"
        )
        assert r"\begin{bmatrix}" in result
        assert "42" in result
        assert "58" in result


# ═══════════════════════════════════════════════════════════════════════
# parse_section 통합 (EQEDIT 태그에서 EquationBlock 추출)
# ═══════════════════════════════════════════════════════════════════════


class TestParseEquation:
    """합성 eqed CTRL_HEADER → EquationBlock 파싱."""

    def _empty_info(self) -> DocInfoResult:
        return DocInfoResult(global_resources=GlobalResources())

    def _eq_stream(self, script: str) -> bytes:
        eq_payload = _eqedit_payload(script)
        return (
            _make_record(HWPTAG_CTRL_HEADER, 0, _ctrl_header_payload("eqed"))
            + _make_record(HWPTAG_LIST_HEADER, 1, bytes(32))
            + _make_record(HWPTAG_EQEDIT, 1, eq_payload)
        )

    def test_equation_parsed(self) -> None:
        stream = self._eq_stream("x ^ 2 + y ^ 2 = r ^ 2")
        blocks, verb_map = parse_section(stream, self._empty_info())
        assert len(blocks) == 1
        blk = blocks[0]
        assert isinstance(blk, EquationBlock)
        assert blk.hwp_script == "x ^ 2 + y ^ 2 = r ^ 2"
        assert blk.latex is not None
        assert blk.verbatim_ref is not None

    def test_equation_with_fraction(self) -> None:
        stream = self._eq_stream("a over b")
        blocks, _ = parse_section(stream, self._empty_info())
        blk = blocks[0]
        assert isinstance(blk, EquationBlock)
        assert blk.hwp_script == "a over b"
        assert r"\frac" in blk.latex

    def test_equation_with_greek(self) -> None:
        stream = self._eq_stream("alpha + beta = gamma")
        blocks, _ = parse_section(stream, self._empty_info())
        blk = blocks[0]
        assert isinstance(blk, EquationBlock)
        assert r"\alpha" in blk.latex
        assert r"\beta" in blk.latex

    def test_equation_with_matrix(self) -> None:
        stream = self._eq_stream("matrix{a & b # c & d}")
        blocks, _ = parse_section(stream, self._empty_info())
        blk = blocks[0]
        assert isinstance(blk, EquationBlock)
        assert r"\begin{matrix}" in blk.latex

    def test_empty_eqedit(self) -> None:
        stream = (
            _make_record(HWPTAG_CTRL_HEADER, 0, _ctrl_header_payload("eqed"))
            + _make_record(HWPTAG_LIST_HEADER, 1, bytes(32))
            + _make_record(HWPTAG_EQEDIT, 1, b"")
        )
        blocks, _ = parse_section(stream, self._empty_info())
        blk = blocks[0]
        assert isinstance(blk, EquationBlock)
        assert blk.hwp_script == ""

    def test_no_eqedit_tag(self) -> None:
        stream = (
            _make_record(HWPTAG_CTRL_HEADER, 0, _ctrl_header_payload("eqed"))
            + _make_record(HWPTAG_LIST_HEADER, 1, bytes(32))
        )
        blocks, _ = parse_section(stream, self._empty_info())
        blk = blocks[0]
        assert isinstance(blk, EquationBlock)
        assert blk.hwp_script is None


# ═══════════════════════════════════════════════════════════════════════
# MD 렌더링
# ═══════════════════════════════════════════════════════════════════════


class TestEquationMdRender:
    def test_latex_rendered(self) -> None:
        from udf.renderers.md import render_md
        from udf.pipeline.document import UdfDocument
        from udf.schema.metadata import DocumentMetadata

        eq = EquationBlock(
            type="equation",
            id="eq_1",
            hwp_script="a over b",
            latex=r"\frac{a}{b}",
        )
        doc = UdfDocument(
            source_format="hwp",
            metadata=DocumentMetadata(),
            blocks=[eq],
        )
        md = render_md(doc, embed_ids=True)
        assert "$$" in md
        assert r"\frac{a}{b}" in md

    def test_no_latex_fallback(self) -> None:
        from udf.renderers.md import render_md
        from udf.pipeline.document import UdfDocument
        from udf.schema.metadata import DocumentMetadata

        eq = EquationBlock(
            type="equation",
            id="eq_2",
            hwp_script="x ^ 2",
            latex=None,
        )
        doc = UdfDocument(
            source_format="hwp",
            metadata=DocumentMetadata(),
            blocks=[eq],
        )
        md = render_md(doc, embed_ids=True)
        assert "hwp-equation" in md
        assert "x ^ 2" in md

    def test_empty_equation(self) -> None:
        from udf.renderers.md import render_md
        from udf.pipeline.document import UdfDocument
        from udf.schema.metadata import DocumentMetadata

        eq = EquationBlock(
            type="equation",
            id="eq_3",
        )
        doc = UdfDocument(
            source_format="hwp",
            metadata=DocumentMetadata(),
            blocks=[eq],
        )
        md = render_md(doc, embed_ids=True)
        assert "unsupported: equation" in md
