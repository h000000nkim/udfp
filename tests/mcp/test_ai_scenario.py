"""Phase 10f: AI 시나리오 테스트 — 이미지→문서 생성 워크플로우 시뮬레이션.

AI가 문서 이미지를 분석한 결과를 create tool로 전달하여
HWP/DOCX/HWPX 문서를 생성하는 E2E 시나리오.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from udfp.server import create_server


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def tools():
    server = create_server()
    return {t.fn.__name__: t.fn for t in server._tool_manager._tools.values()}


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ------------------------------------------------------------------
# 시나리오 1: 간단한 보고서 (제목 + 표 + 본문)
# ------------------------------------------------------------------


class TestScenarioReport:
    """AI가 보고서 이미지를 보고 생성하는 시나리오."""

    BLOCKS = [
        {"type": "heading", "level": 1, "text": "2026년 5월 월간 보고서",
         "fmt": {"bold": True, "size": 18}},
        {"type": "paragraph", "text": ""},
        {"type": "paragraph", "text": "작성일: 2026-05-26",
         "fmt": {"align": "right", "size": 10}},
        {"type": "paragraph", "text": ""},
        {"type": "heading", "level": 2, "text": "1. 실적 요약"},
        {"type": "table", "rows": [
            [{"text": "항목", "fmt": {"bold": True}, "bg": "#4472C4"},
             {"text": "목표", "fmt": {"bold": True}, "bg": "#4472C4"},
             {"text": "실적", "fmt": {"bold": True}, "bg": "#4472C4"},
             {"text": "달성률", "fmt": {"bold": True}, "bg": "#4472C4"}],
            [{"text": "매출"}, {"text": "1,500만원"}, {"text": "1,200만원"}, {"text": "80%"}],
            [{"text": "신규고객"}, {"text": "50명"}, {"text": "62명"}, {"text": "124%"}],
            [{"text": "이탈률"}, {"text": "5%"}, {"text": "3.2%"}, {"text": "달성"}],
        ], "col_widths": [80, 80, 80, 60], "header_rows": 1, "border": "single"},
        {"type": "paragraph", "text": ""},
        {"type": "heading", "level": 2, "text": "2. 주요 이슈"},
        {"type": "list", "ordered": True, "items": [
            "서버 마이그레이션 완료 (5/15)",
            "신규 기능 A 배포 예정 (6/1)",
            "고객 불만 건수 전월 대비 20% 감소",
        ]},
        {"type": "paragraph", "text": ""},
        {"type": "heading", "level": 2, "text": "3. 다음 달 계획"},
        {"type": "paragraph", "text": "6월에는 신규 기능 B 개발에 집중하며, "
         "마케팅 예산을 20% 증액하여 신규 고객 유치를 강화할 예정입니다."},
        {"type": "paragraph", "text": ""},
        {"type": "paragraph", "text": "이상입니다.", "fmt": {"align": "right"}},
    ]

    PAGE = {"paper": "A4", "margin_top": 25, "margin_bottom": 25,
            "margin_left": 30, "margin_right": 30}

    META = {"title": "2026년 5월 월간 보고서", "author": "홍길동"}

    @pytest.mark.parametrize("fmt", ["hwp", "docx", "hwpx"])
    def test_generate_report(self, tools, tmp_dir, fmt):
        out = os.path.join(tmp_dir, f"report.{fmt}")
        result = _run(tools["create"](
            blocks=self.BLOCKS,
            format=fmt,
            output_path=out,
            page=self.PAGE,
            metadata=self.META,
        ))
        assert "Created:" in result
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
        data = json.loads(result.split("\n\n", 1)[1])
        assert data["metadata"]["title"] == "2026년 5월 월간 보고서"
        assert len(data["blocks"]) >= 10


# ------------------------------------------------------------------
# 시나리오 2: 이력서/양식 (인라인 서식 복합)
# ------------------------------------------------------------------


class TestScenarioResume:
    """AI가 이력서 양식 이미지를 보고 생성하는 시나리오."""

    BLOCKS = [
        {"type": "heading", "level": 1, "text": "이 력 서",
         "fmt": {"size": 24, "bold": True}},
        {"type": "paragraph", "text": ""},
        {"type": "table", "rows": [
            [{"text": "성명", "fmt": {"bold": True}, "bg": "#F2F2F2"},
             {"text": "홍길동"},
             {"text": "생년월일", "fmt": {"bold": True}, "bg": "#F2F2F2"},
             {"text": "1990.01.15"}],
            [{"text": "연락처", "fmt": {"bold": True}, "bg": "#F2F2F2"},
             {"text": "010-1234-5678"},
             {"text": "이메일", "fmt": {"bold": True}, "bg": "#F2F2F2"},
             {"text": "hong@example.com"}],
            [{"text": "주소", "fmt": {"bold": True}, "bg": "#F2F2F2"},
             {"text": "서울시 강남구 테헤란로 123", "colspan": 3}, None, None],
        ], "col_widths": [60, 120, 60, 120], "border": "single"},
        {"type": "paragraph", "text": ""},
        {"type": "heading", "level": 2, "text": "학력사항"},
        {"type": "table", "rows": [
            [{"text": "기간", "fmt": {"bold": True}, "bg": "#F2F2F2"},
             {"text": "학교명", "fmt": {"bold": True}, "bg": "#F2F2F2"},
             {"text": "전공", "fmt": {"bold": True}, "bg": "#F2F2F2"},
             {"text": "학위", "fmt": {"bold": True}, "bg": "#F2F2F2"}],
            [{"text": "2009.03~2013.02"}, {"text": "서울대학교"}, {"text": "컴퓨터공학"}, {"text": "학사"}],
            [{"text": "2013.03~2015.02"}, {"text": "KAIST"}, {"text": "AI"}, {"text": "석사"}],
        ], "col_widths": [90, 100, 80, 50], "header_rows": 1, "border": "single"},
        {"type": "paragraph", "text": ""},
        {"type": "heading", "level": 2, "text": "경력사항"},
        {"type": "table", "rows": [
            [{"text": "기간", "fmt": {"bold": True}, "bg": "#F2F2F2"},
             {"text": "회사명", "fmt": {"bold": True}, "bg": "#F2F2F2"},
             {"text": "직위", "fmt": {"bold": True}, "bg": "#F2F2F2"},
             {"text": "업무내용", "fmt": {"bold": True}, "bg": "#F2F2F2"}],
            [{"text": "2015.03~2020.12"}, {"text": "네이버"}, {"text": "시니어 개발자"}, {"text": "검색 엔진 개발"}],
            [{"text": "2021.01~현재"}, {"text": "카카오"}, {"text": "테크 리드"}, {"text": "AI 플랫폼 구축"}],
        ], "col_widths": [90, 80, 80, 110], "header_rows": 1, "border": "single"},
    ]

    @pytest.mark.parametrize("fmt", ["hwp", "docx", "hwpx"])
    def test_generate_resume(self, tools, tmp_dir, fmt):
        out = os.path.join(tmp_dir, f"resume.{fmt}")
        result = _run(tools["create"](
            blocks=self.BLOCKS,
            format=fmt,
            output_path=out,
            page={"paper": "A4", "margin_top": 20, "margin_left": 25, "margin_right": 25},
            metadata={"title": "이력서 - 홍길동"},
        ))
        assert "Created:" in result
        assert os.path.getsize(out) > 0


# ------------------------------------------------------------------
# 시나리오 3: 다단/복합 레이아웃
# ------------------------------------------------------------------


class TestScenarioComplex:
    """제목+본문+코드+수식 혼합 문서."""

    BLOCKS = [
        {"type": "heading", "level": 1, "text": "기술 문서"},
        {"type": "paragraph", "text": "이 문서는 다양한 블록 타입을 포함합니다."},
        {"type": "heading", "level": 2, "text": "코드 예제"},
        {"type": "code", "code": "def hello():\n    print('Hello, World!')", "language": "python"},
        {"type": "heading", "level": 2, "text": "수식"},
        {"type": "equation", "latex": "\\int_0^\\infty e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}"},
        {"type": "heading", "level": 2, "text": "인용"},
        {"type": "quote", "text": "The best way to predict the future is to invent it. - Alan Kay"},
        {"type": "horizontal_rule"},
        {"type": "paragraph", "inlines": [
            {"text": "이 문장에는 "},
            {"text": "볼드", "fmt": {"bold": True}},
            {"text": ", "},
            {"text": "이탤릭", "fmt": {"italic": True}},
            {"text": ", "},
            {"text": "밑줄", "fmt": {"underline": True}},
            {"text": "이 포함됩니다."},
        ]},
        {"type": "page_break"},
        {"type": "heading", "level": 2, "text": "2페이지"},
        {"type": "paragraph", "text": "페이지 나눔 후 내용입니다."},
    ]

    @pytest.mark.parametrize("fmt", ["hwp", "docx", "hwpx", "md"])
    def test_generate_complex(self, tools, tmp_dir, fmt):
        out = os.path.join(tmp_dir, f"complex.{fmt}")
        result = _run(tools["create"](
            blocks=self.BLOCKS,
            format=fmt,
            output_path=out,
            metadata={"title": "기술 문서"},
        ))
        assert "Created:" in result
        assert os.path.exists(out)


# ------------------------------------------------------------------
# 시나리오 5: insert_blocks로 점진적 빌드
# ------------------------------------------------------------------


class TestScenarioIncrementalBuild:
    """빈 문서에서 시작하여 점진적으로 블록을 추가."""

    def test_incremental_build(self, tools, tmp_dir):
        hwp = os.path.join(tmp_dir, "incremental.hwp")

        _run(tools["create"](
            blocks=[{"type": "heading", "level": 1, "text": "문서 제목"}],
            format="hwp",
            output_path=hwp,
        ))

        _run(tools["insert_blocks"](
            path=hwp,
            blocks=[
                {"type": "paragraph", "text": "서론입니다."},
                {"type": "heading", "level": 2, "text": "본론"},
            ],
            output_path=hwp,
        ))

        _run(tools["insert_blocks"](
            path=hwp,
            blocks=[
                {"type": "paragraph", "text": "본론 내용입니다."},
                {"type": "table", "rows": [["A", "B"], ["C", "D"]]},
            ],
            output_path=hwp,
        ))

        data = json.loads(_run(tools["read"](path=hwp)))
        types = [b["type"] for b in data["blocks"]]
        assert "heading" in types
        assert "paragraph" in types
        assert "table" in types
        assert len(data["blocks"]) >= 5
