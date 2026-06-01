"""HWPX 제너레이터 단위 테스트."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from udf.core.schema import (
    ColumnDef,
    DocumentMetadata,
    DrawingBlock,
    EndnoteBlock,
    EquationInline,
    FootnoteRefInline,
    HeadingBlock,
    ParagraphBlock,
    SectionDef,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
    TextInline,
    UdfDocument,
)
from udf.parsers.hwpx.parse import parse_hwpx
from udf.renderers.hwpx import generate_hwpx
from udf.renderers.hwpx.serialize import (
    blocks_to_section_xml,
    build_minimal_header_xml,
    build_content_hpf,
    build_container_xml,
    build_version_xml,
)

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "hwpx"


# ---------------------------------------------------------------------------
# 헬퍼: 최소 HWPX fixture를 프로그래밍으로 생성
# ---------------------------------------------------------------------------


def _build_minimal_hwpx(tmp_path: Path, text: str = "Hello HWPX") -> Path:
    """최소한의 유효 HWPX ZIP을 생성한다.

    이 함수로 만든 파일을 parse → generate → parse 라운드트립에 사용한다.
    """
    hwpx_path = tmp_path / "minimal.hwpx"

    # 최소 UdfDocument로 section XML 생성
    doc = UdfDocument(
        source_format="hwpx",
        blocks=[
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text=text)],
            ),
        ],
    )
    section_xml = blocks_to_section_xml(doc.blocks, doc)
    header_xml = build_minimal_header_xml(doc)
    content_hpf = build_content_hpf(section_count=1)
    container_xml = build_container_xml()
    version_xml = build_version_xml()

    with zipfile.ZipFile(str(hwpx_path), "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype first, stored
        mi = zipfile.ZipInfo("mimetype")
        mi.compress_type = zipfile.ZIP_STORED
        mi.extra = b""
        zf.writestr(mi, "application/hwp+zip")

        zf.writestr("version.xml", version_xml)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("Contents/header.xml", header_xml)
        zf.writestr("Contents/section0.xml", section_xml)
        zf.writestr("Contents/content.hpf", content_hpf)

    return hwpx_path


def _build_doc_with_blocks(blocks: list) -> UdfDocument:
    """블록 리스트에서 From Scratch용 UdfDocument를 만든다."""
    return UdfDocument(
        source_format="hwpx",
        blocks=blocks,
    )


# ---------------------------------------------------------------------------
# Seed Patch 모드 테스트
# ---------------------------------------------------------------------------


class TestSeedPatch:
    def test_seed_patch_preserves_structure(self, tmp_path):
        """Seed Patch로 생성 시 원본 ZIP의 entry 목록이 보존된다."""
        fixture = FIXTURES / "table_text.hwpx"
        if not fixture.exists():
            pytest.skip("Fixture not available")



        doc = parse_hwpx(str(fixture))
        output = tmp_path / "output.hwpx"
        generate_hwpx(doc, str(output))

        assert output.exists()
        with zipfile.ZipFile(str(output), "r") as zf:
            names = zf.namelist()
            assert "mimetype" in names
            assert "Contents/header.xml" in names
            assert "Contents/section0.xml" in names

    def test_seed_patch_mimetype_first(self, tmp_path):
        """Seed Patch 결과에서 mimetype이 첫 번째 entry이다."""
        fixture = FIXTURES / "table_text.hwpx"
        if not fixture.exists():
            pytest.skip("Fixture not available")



        doc = parse_hwpx(str(fixture))
        output = tmp_path / "output.hwpx"
        generate_hwpx(doc, str(output))

        with zipfile.ZipFile(str(output), "r") as zf:
            first = zf.infolist()[0]
            assert first.filename == "mimetype"
            assert first.compress_type == zipfile.ZIP_STORED

    def test_seed_patch_mimetype_content(self, tmp_path):
        """mimetype entry의 내용이 'application/hwp+zip'이다."""
        fixture = FIXTURES / "table_text.hwpx"
        if not fixture.exists():
            pytest.skip("Fixture not available")



        doc = parse_hwpx(str(fixture))
        output = tmp_path / "output.hwpx"
        generate_hwpx(doc, str(output))

        with zipfile.ZipFile(str(output), "r") as zf:
            mimetype = zf.read("mimetype")
            assert mimetype == b"application/hwp+zip"

    def test_seed_patch_preserves_all_entries(self, tmp_path):
        """원본의 모든 ZIP entry가 출력에도 존재한다."""
        fixture = FIXTURES / "table_text.hwpx"
        if not fixture.exists():
            pytest.skip("Fixture not available")



        doc = parse_hwpx(str(fixture))
        output = tmp_path / "output.hwpx"
        generate_hwpx(doc, str(output))

        with zipfile.ZipFile(str(fixture), "r") as orig_zf:
            orig_names = set(orig_zf.namelist())
        with zipfile.ZipFile(str(output), "r") as out_zf:
            out_names = set(out_zf.namelist())

        assert orig_names == out_names

    def test_seed_patch_section_xml_readable(self, tmp_path):
        """Seed Patch 결과의 section XML이 유효한 XML이다."""
        fixture = FIXTURES / "table_text.hwpx"
        if not fixture.exists():
            pytest.skip("Fixture not available")

        from lxml import etree


        doc = parse_hwpx(str(fixture))
        output = tmp_path / "output.hwpx"
        generate_hwpx(doc, str(output))

        with zipfile.ZipFile(str(output), "r") as zf:
            section_bytes = zf.read("Contents/section0.xml")
            # 유효한 XML이어야 함 — 파싱 실패 시 예외 발생
            root = etree.fromstring(section_bytes)
            assert root is not None


# ---------------------------------------------------------------------------
# From Scratch 모드 테스트
# ---------------------------------------------------------------------------


class TestFromScratch:
    def test_from_scratch_basic(self, tmp_path):
        """단순 단락에서 유효한 HWPX가 생성된다."""
        doc = _build_doc_with_blocks([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="테스트 문장입니다.")],
            ),
        ])
        output = tmp_path / "scratch.hwpx"
        generate_hwpx(doc, str(output))

        assert output.exists()
        with zipfile.ZipFile(str(output), "r") as zf:
            names = zf.namelist()
            assert "mimetype" in names
            assert "Contents/header.xml" in names
            assert "Contents/section0.xml" in names
            assert "Contents/content.hpf" in names
            assert "META-INF/container.xml" in names

    def test_from_scratch_mimetype(self, tmp_path):
        """From Scratch에서 mimetype이 첫 번째, stored, 올바른 값이다."""
        doc = _build_doc_with_blocks([
            ParagraphBlock(type="paragraph", id="b_0001", inlines=[TextInline(text="X")]),
        ])
        output = tmp_path / "scratch.hwpx"
        generate_hwpx(doc, str(output))

        with zipfile.ZipFile(str(output), "r") as zf:
            first = zf.infolist()[0]
            assert first.filename == "mimetype"
            assert first.compress_type == zipfile.ZIP_STORED
            assert zf.read("mimetype") == b"application/hwp+zip"

    def test_from_scratch_heading(self, tmp_path):
        """HeadingBlock이 section XML에 올바르게 직렬화된다."""
        doc = _build_doc_with_blocks([
            HeadingBlock(
                type="heading",
                id="b_0001",
                level=1,
                text="제목 1",
            ),
            ParagraphBlock(
                type="paragraph",
                id="b_0002",
                inlines=[TextInline(text="본문입니다.")],
            ),
        ])
        output = tmp_path / "heading.hwpx"
        generate_hwpx(doc, str(output))

        from lxml import etree

        with zipfile.ZipFile(str(output), "r") as zf:
            section_bytes = zf.read("Contents/section0.xml")
            root = etree.fromstring(section_bytes)

        NS = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"}
        paragraphs = root.findall("hp:p", NS)
        # secPr 단락 + heading 단락 + body 단락 = 최소 3개
        assert len(paragraphs) >= 3

        # 텍스트 확인: 어딘가에 "제목 1" 텍스트가 존재해야 함
        all_text = etree.tostring(root, encoding="unicode")
        assert "제목 1" in all_text
        assert "본문입니다." in all_text

    def test_from_scratch_table(self, tmp_path):
        """TableBlock이 section XML에 올바르게 직렬화된다."""
        doc = _build_doc_with_blocks([
            TableBlock(
                type="table",
                id="b_0001",
                rows=[
                    TableRow(cells=[
                        TableCell(
                            id="c_0001",
                            content=[ParagraphBlock(
                                type="paragraph",
                                id="b_0002",
                                inlines=[TextInline(text="셀A")],
                            )],
                        ),
                        TableCell(
                            id="c_0002",
                            content=[ParagraphBlock(
                                type="paragraph",
                                id="b_0003",
                                inlines=[TextInline(text="셀B")],
                            )],
                        ),
                    ]),
                    TableRow(cells=[
                        TableCell(
                            id="c_0003",
                            content=[ParagraphBlock(
                                type="paragraph",
                                id="b_0004",
                                inlines=[TextInline(text="셀C")],
                            )],
                        ),
                        TableCell(
                            id="c_0004",
                            content=[ParagraphBlock(
                                type="paragraph",
                                id="b_0005",
                                inlines=[TextInline(text="셀D")],
                            )],
                        ),
                    ]),
                ],
            ),
        ])
        output = tmp_path / "table.hwpx"
        generate_hwpx(doc, str(output))

        from lxml import etree

        with zipfile.ZipFile(str(output), "r") as zf:
            section_bytes = zf.read("Contents/section0.xml")
            root = etree.fromstring(section_bytes)

        NS = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"}

        # tbl 요소 존재 확인
        tbls = root.findall(".//hp:tbl", NS)
        assert len(tbls) == 1

        tbl = tbls[0]
        assert tbl.get("rowCnt") == "2"
        assert tbl.get("colCnt") == "2"

        # 행 확인
        trs = tbl.findall("hp:tr", NS)
        assert len(trs) == 2

        # 셀 텍스트 확인
        all_text = etree.tostring(root, encoding="unicode")
        for text in ("셀A", "셀B", "셀C", "셀D"):
            assert text in all_text

    def test_from_scratch_valid_zip(self, tmp_path):
        """생성된 HWPX가 유효한 ZIP이다."""
        doc = _build_doc_with_blocks([
            ParagraphBlock(type="paragraph", id="b_0001", inlines=[TextInline(text="A")]),
        ])
        output = tmp_path / "valid.hwpx"
        generate_hwpx(doc, str(output))

        # BadZipFile이 발생하지 않아야 함
        with zipfile.ZipFile(str(output), "r") as zf:
            assert zf.testzip() is None  # None = 에러 없음

    def test_from_scratch_empty_paragraph(self, tmp_path):
        """빈 단락도 유효한 HWPX를 생성한다."""
        doc = _build_doc_with_blocks([
            ParagraphBlock(type="paragraph", id="b_0001", inlines=[]),
        ])
        output = tmp_path / "empty_para.hwpx"
        generate_hwpx(doc, str(output))

        assert output.exists()
        with zipfile.ZipFile(str(output), "r") as zf:
            assert zf.testzip() is None


# ---------------------------------------------------------------------------
# 라운드트립 테스트
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_roundtrip_parse_generate_parse(self, tmp_path):
        """parse → generate → parse 라운드트립에서 블록 수가 보존된다."""
        fixture = FIXTURES / "report_form.hwpx"
        if not fixture.exists():
            pytest.skip("Fixture not available")



        # 1) 원본 파싱
        doc1 = parse_hwpx(str(fixture))
        block_count_1 = len(doc1.blocks)
        assert block_count_1 > 0

        # 2) 생성 (Seed Patch 모드)
        output = tmp_path / "roundtrip.hwpx"
        generate_hwpx(doc1, str(output))
        assert output.exists()

        # 3) 재파싱
        doc2 = parse_hwpx(str(output))
        block_count_2 = len(doc2.blocks)

        # Seed Patch 모드에서는 원본 section XML을 그대로 보존하므로
        # 블록 수가 동일해야 함
        assert block_count_2 == block_count_1

    def test_roundtrip_text_preserved(self, tmp_path):
        """라운드트립 후 텍스트 내용이 보존된다."""
        fixture = FIXTURES / "report_form.hwpx"
        if not fixture.exists():
            pytest.skip("Fixture not available")



        doc1 = parse_hwpx(str(fixture))

        output = tmp_path / "roundtrip.hwpx"
        generate_hwpx(doc1, str(output))
        doc2 = parse_hwpx(str(output))

        def _extract_texts(doc):
            texts = []
            for b in doc.blocks:
                if hasattr(b, "inlines"):
                    for i in b.inlines:
                        if isinstance(i, TextInline):
                            texts.append(i.text)
                elif hasattr(b, "text"):
                    texts.append(b.text)
            return texts

        texts1 = _extract_texts(doc1)
        texts2 = _extract_texts(doc2)
        assert texts1 == texts2

    def test_roundtrip_from_scratch_preserves_text(self, tmp_path):
        """From Scratch 라운드트립: 생성 후 parse에서 텍스트가 보존된다."""
        doc = _build_doc_with_blocks([
            ParagraphBlock(
                type="paragraph",
                id="b_0001",
                inlines=[TextInline(text="라운드트립 테스트 문장")],
            ),
            ParagraphBlock(
                type="paragraph",
                id="b_0002",
                inlines=[TextInline(text="두 번째 단락")],
            ),
        ])

        output = tmp_path / "scratch_rt.hwpx"
        generate_hwpx(doc, str(output))



        doc2 = parse_hwpx(str(output))

        texts = []
        for b in doc2.blocks:
            if hasattr(b, "inlines"):
                for i in b.inlines:
                    if isinstance(i, TextInline):
                        texts.append(i.text)

        assert "라운드트립 테스트 문장" in texts
        assert "두 번째 단락" in texts

    def test_roundtrip_table_preserved(self, tmp_path):
        """Seed Patch 라운드트립에서 테이블 블록이 보존된다."""
        fixture = FIXTURES / "table_text.hwpx"
        if not fixture.exists():
            pytest.skip("Fixture not available")



        doc1 = parse_hwpx(str(fixture))
        tables1 = [b for b in doc1.blocks if b.type == "table"]

        output = tmp_path / "roundtrip_table.hwpx"
        generate_hwpx(doc1, str(output))

        doc2 = parse_hwpx(str(output))
        tables2 = [b for b in doc2.blocks if b.type == "table"]

        assert len(tables2) == len(tables1)

        if tables1 and tables2:
            assert len(tables2[0].rows) == len(tables1[0].rows)


# ---------------------------------------------------------------------------
# Serializer 단위 테스트
# ---------------------------------------------------------------------------


class TestSerializer:
    def test_blocks_to_section_xml_returns_bytes(self):
        doc = _build_doc_with_blocks([
            ParagraphBlock(type="paragraph", id="b_0001", inlines=[TextInline(text="X")]),
        ])
        result = blocks_to_section_xml(doc.blocks, doc)
        assert isinstance(result, bytes)
        assert result.startswith(b"<?xml")

    def test_section_xml_valid(self):
        """생성된 section XML이 well-formed이다."""
        from lxml import etree

        doc = _build_doc_with_blocks([
            ParagraphBlock(type="paragraph", id="b_0001", inlines=[TextInline(text="X")]),
        ])
        result = blocks_to_section_xml(doc.blocks, doc)
        root = etree.fromstring(result)
        assert root.tag.endswith("}sec") or root.tag == "sec"

    def test_minimal_header_xml_valid(self):
        """최소 header XML이 well-formed이다."""
        from lxml import etree

        doc = _build_doc_with_blocks([])
        result = build_minimal_header_xml(doc)
        assert isinstance(result, bytes)
        root = etree.fromstring(result)
        assert root.tag.endswith("}head") or root.tag == "head"

    def test_content_hpf_valid(self):
        from lxml import etree

        result = build_content_hpf(section_count=2)
        root = etree.fromstring(result)
        assert root.tag.endswith("}package")

    def test_container_xml_valid(self):
        from lxml import etree

        result = build_container_xml()
        root = etree.fromstring(result)
        assert root.tag.endswith("}container")

    def test_version_xml_valid(self):
        from lxml import etree

        result = build_version_xml()
        root = etree.fromstring(result)
        assert root.tag.endswith("}HCFVersion")

    def test_heading_in_section_xml(self):
        """HeadingBlock이 section XML에 포함된다."""
        doc = _build_doc_with_blocks([
            HeadingBlock(type="heading", id="b_0001", level=2, text="소제목"),
        ])
        result = blocks_to_section_xml(doc.blocks, doc)
        assert "소제목".encode("utf-8") in result

    def test_table_in_section_xml(self):
        """TableBlock이 section XML에 <hp:tbl>로 포함된다."""
        doc = _build_doc_with_blocks([
            TableBlock(
                type="table",
                id="b_0001",
                rows=[
                    TableRow(cells=[
                        TableCell(
                            id="c_0001",
                            content=[ParagraphBlock(
                                type="paragraph",
                                id="b_0002",
                                inlines=[TextInline(text="내용")],
                            )],
                        ),
                    ]),
                ],
            ),
        ])
        result = blocks_to_section_xml(doc.blocks, doc)
        xml_str = result.decode("utf-8")
        assert "tbl" in xml_str
        assert "내용" in xml_str


# ---------------------------------------------------------------------------
# Section properties in generated HWPX
# ---------------------------------------------------------------------------


class TestSectionPropsInHwpx:
    def _make_doc_with_section(self, **sect_kwargs) -> UdfDocument:
        return UdfDocument(
            source_format="hwpx",
            metadata=DocumentMetadata(
                sections=[SectionDef(**sect_kwargs)],
            ),
            blocks=[ParagraphBlock(
                type="paragraph", id="b_1",
                inlines=[TextInline(text="test")],
            )],
        )

    def test_landscape_emitted(self):
        doc = self._make_doc_with_section(
            page_width=792.0, page_height=612.0,
            orientation="landscape",
        )
        xml = blocks_to_section_xml(doc.blocks, doc).decode("utf-8")
        assert 'landscape="true"' in xml

    def test_portrait_default(self):
        doc = self._make_doc_with_section(
            page_width=595.28, page_height=841.86,
        )
        xml = blocks_to_section_xml(doc.blocks, doc).decode("utf-8")
        assert 'landscape="WIDELY"' in xml

    def test_columns_emitted(self):
        doc = self._make_doc_with_section(
            page_width=595.28, page_height=841.86,
            columns=ColumnDef(count=2, gap=36.0, same_width=True),
        )
        xml = blocks_to_section_xml(doc.blocks, doc).decode("utf-8")
        assert 'multiColumn' in xml
        assert 'count="2"' in xml
        assert 'gap="3600"' in xml  # 36pt * 100
        assert 'sameWidth="1"' in xml

    def test_no_columns_when_single(self):
        doc = self._make_doc_with_section(
            page_width=595.28, page_height=841.86,
        )
        xml = blocks_to_section_xml(doc.blocks, doc).decode("utf-8")
        assert 'multiColumn' not in xml


class TestBlockTypeCoverageHwpx:
    """HWPX 직렬화에서 추가 블록 타입 지원 검증."""

    def _make_doc(self, blocks):
        return UdfDocument(
            source_format="hwpx",
            metadata=DocumentMetadata(
                sections=[SectionDef(
                    page_width=595.28, page_height=841.86,
                )],
            ),
            blocks=blocks,
        )

    def test_textbox_block_content(self):
        doc = self._make_doc([
            TextBoxBlock(
                type="text_box", id="tb_1",
                content=[
                    ParagraphBlock(
                        type="paragraph", id="tb_p1",
                        inlines=[TextInline(text="텍스트박스 내용")],
                    ),
                ],
            ),
        ])
        xml = blocks_to_section_xml(doc.blocks, doc).decode("utf-8")
        assert "텍스트박스 내용" in xml

    def test_endnote_block_skipped(self):
        doc = self._make_doc([
            EndnoteBlock(
                type="endnote", id="en_1", ref="1",
                content=[
                    ParagraphBlock(
                        type="paragraph", id="en_p1",
                        inlines=[TextInline(text="미주")],
                    ),
                ],
            ),
            ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[TextInline(text="본문")],
            ),
        ])
        xml = blocks_to_section_xml(doc.blocks, doc).decode("utf-8")
        assert "본문" in xml

    def test_equation_inline_in_paragraph(self):
        doc = self._make_doc([
            ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[
                    TextInline(text="공식: "),
                    EquationInline(latex="a+b"),
                ],
            ),
        ])
        xml = blocks_to_section_xml(doc.blocks, doc).decode("utf-8")
        assert "a+b" in xml

    def test_footnote_ref_inline_in_paragraph(self):
        doc = self._make_doc([
            ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[
                    TextInline(text="본문"),
                    FootnoteRefInline(ref_id="1", number=1),
                ],
            ),
        ])
        xml = blocks_to_section_xml(doc.blocks, doc).decode("utf-8")
        assert "본문" in xml


class TestHwpxLossReport:
    def test_drawing_block_records_loss(self, tmp_path):
        doc = UdfDocument(
            source_format="hwpx",
            blocks=[
                ParagraphBlock(type="paragraph", id="b_0", inlines=[TextInline(text="text")]),
                DrawingBlock(type="drawing", id="d_0"),
            ],
        )
        out = str(tmp_path / "out.hwpx")
        generate_hwpx(doc, out)
        assert doc.loss_report is not None
        assert any("drawing" in b.description for b in doc.loss_report.lossy_blocks)

    def test_from_scratch_sets_loss_report(self, tmp_path):
        doc = UdfDocument(
            source_format="hwpx",
            blocks=[
                ParagraphBlock(type="paragraph", id="b_0", inlines=[TextInline(text="hello")]),
            ],
        )
        out = str(tmp_path / "out.hwpx")
        generate_hwpx(doc, out)
        assert doc.loss_report is not None
        assert doc.loss_report.total_blocks == 1


class TestHwpxCharPrIDRef:
    """Phase 15d: HWPX charPrIDRef 동적 생성 검증."""

    def test_bold_inline_gets_unique_charpr(self):
        doc = UdfDocument(
            source_format="hwpx",
            blocks=[
                ParagraphBlock(type="paragraph", id="b1", inlines=[
                    TextInline(text="normal"),
                    TextInline(text="bold", bold=True),
                ]),
            ],
        )
        section_xml = blocks_to_section_xml(doc.blocks, doc).decode("utf-8")
        header_xml = build_minimal_header_xml(doc).decode("utf-8")
        assert "charPrIDRef" in section_xml
        assert "charPr" in header_xml
        assert "bold" in header_xml.lower() or "fontBold" in header_xml

    def test_multiple_styles_create_multiple_charpr(self):
        doc = UdfDocument(
            source_format="hwpx",
            blocks=[
                ParagraphBlock(type="paragraph", id="b1", inlines=[
                    TextInline(text="plain"),
                    TextInline(text="bold", bold=True),
                    TextInline(text="italic", italic=True),
                    TextInline(text="both", bold=True, italic=True),
                ]),
            ],
        )
        blocks_to_section_xml(doc.blocks, doc)
        header_xml = build_minimal_header_xml(doc).decode("utf-8")
        assert header_xml.count("charPr ") >= 3  # default + bold + italic + both

    def test_colored_inline_in_header(self):
        doc = UdfDocument(
            source_format="hwpx",
            blocks=[
                ParagraphBlock(type="paragraph", id="b1", inlines=[
                    TextInline(text="red text", color="#ff0000"),
                ]),
            ],
        )
        blocks_to_section_xml(doc.blocks, doc)
        header_xml = build_minimal_header_xml(doc).decode("utf-8")
        assert "textColor" in header_xml
