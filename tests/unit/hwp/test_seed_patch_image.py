"""Seed Patch 모드 이미지 삽입 테스트 (BUG-243)."""

import base64
import pathlib
import struct

import pytest

from udf.parsers.hwp.parse import parse_hwp
from udf.parsers.hwp.records import (
    HWPTAG_BIN_DATA,
    HWPTAG_CTRL_HEADER,
    HWPTAG_ID_MAPPINGS,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_TEXT,
    HWPTAG_SHAPE_COMPONENT,
    HWPTAG_SHAPE_COMPONENT_PIC,
    iter_records,
)
from udf.renderers.hwp import render_hwp
from udf.renderers.hwp.body_writer import inject_image_gso
from udf.renderers.hwp.docinfo_patch import add_bindata_record
from udf.renderers.hwp.body_builder import build_image_gso_records
from udf.schema.blocks import ImageBlock

_FIXTURES = pathlib.Path(__file__).resolve().parent.parent.parent / "fixtures" / "hwp"

_1X1_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestAddBindataRecord:
    def test_adds_bindata_and_updates_idmappings(self):
        src = str(_FIXTURES / "f01_plain_text.hwp")
        doc = parse_hwp(src)
        assert doc.verbatim and doc.verbatim.docinfo_stream
        docinfo = base64.b64decode(doc.verbatim.docinfo_stream)

        old_bd_count = sum(1 for r in iter_records(docinfo) if r.tag_id == HWPTAG_BIN_DATA)
        old_idmap = next(r for r in iter_records(docinfo) if r.tag_id == HWPTAG_ID_MAPPINGS)
        old_idmap_bd = struct.unpack_from("<I", old_idmap.payload, 0)[0]

        new_docinfo, bin_item_id = add_bindata_record(docinfo, "png")

        assert bin_item_id == old_bd_count + 1
        new_bd_count = sum(1 for r in iter_records(new_docinfo) if r.tag_id == HWPTAG_BIN_DATA)
        assert new_bd_count == old_bd_count + 1
        new_idmap = next(r for r in iter_records(new_docinfo) if r.tag_id == HWPTAG_ID_MAPPINGS)
        new_idmap_bd = struct.unpack_from("<I", new_idmap.payload, 0)[0]
        assert new_idmap_bd == old_idmap_bd + 1

    def test_multiple_adds(self):
        src = str(_FIXTURES / "f01_plain_text.hwp")
        doc = parse_hwp(src)
        docinfo = base64.b64decode(doc.verbatim.docinfo_stream)

        docinfo, id1 = add_bindata_record(docinfo, "jpg")
        docinfo, id2 = add_bindata_record(docinfo, "png")

        assert id2 == id1 + 1
        bd_records = [r for r in iter_records(docinfo) if r.tag_id == HWPTAG_BIN_DATA]
        assert len(bd_records) >= 2


class TestInjectImageGso:
    def _make_section(self):
        """Build a minimal section stream with one paragraph."""
        from udf.renderers.hwp.body_writer import _serialize_record
        from udf.parsers.hwp.records import HwpRecord

        ph_payload = bytearray(22)
        struct.pack_into("<I", ph_payload, 0, 1)  # charCnt=1 (just CR)
        struct.pack_into("<H", ph_payload, 12, 1)  # csCount=1
        ph = HwpRecord(HWPTAG_PARA_HEADER, 0, bytes(ph_payload), 0)

        pt_payload = b"\x0d\x00"
        pt = HwpRecord(HWPTAG_PARA_TEXT, 1, pt_payload, 0)

        pcs = HwpRecord(0x43, 1, struct.pack("<II", 0, 0), 0)

        records = [ph, pt, pcs]
        data = b""
        offset = 0
        result = []
        for r in records:
            s = _serialize_record(r)
            result.append(HwpRecord(r.tag_id, r.level, r.payload, offset))
            offset += len(s)
            data += s
        return data

    def test_inject_increases_charcnt(self):
        section = self._make_section()
        records_before = list(iter_records(section))
        ph_offset = records_before[0].offset

        gso_records = build_image_gso_records(1, 5000, 3000)

        result = inject_image_gso(section, ph_offset, gso_records)

        records_after = list(iter_records(result))
        new_ph = records_after[0]
        new_cc = struct.unpack_from("<I", new_ph.payload, 0)[0] & 0x3FFFFFFF
        assert new_cc == 9  # 8 (GSO inline) + 1 (CR)

    def test_inject_adds_gso_records(self):
        section = self._make_section()
        records_before = list(iter_records(section))
        ph_offset = records_before[0].offset

        gso_records = build_image_gso_records(1, 5000, 3000)

        result = inject_image_gso(section, ph_offset, gso_records)

        tags = [r.tag_id for r in iter_records(result)]
        assert HWPTAG_CTRL_HEADER in tags
        assert HWPTAG_SHAPE_COMPONENT in tags
        assert HWPTAG_SHAPE_COMPONENT_PIC in tags

    def test_inject_preserves_existing_text(self):
        from udf.renderers.hwp.body_writer import _serialize_record
        from udf.parsers.hwp.records import HwpRecord

        ph_payload = bytearray(22)
        text = "Hello"
        pt_data = text.encode("utf-16-le") + b"\x0d\x00"
        cc = len(pt_data) // 2
        struct.pack_into("<I", ph_payload, 0, cc)
        struct.pack_into("<H", ph_payload, 12, 1)

        data = _serialize_record(HwpRecord(HWPTAG_PARA_HEADER, 0, bytes(ph_payload), 0))
        ph_off = 0
        data += _serialize_record(HwpRecord(HWPTAG_PARA_TEXT, 1, pt_data, 0))
        data += _serialize_record(HwpRecord(0x43, 1, struct.pack("<II", 0, 0), 0))

        gso_records = build_image_gso_records(1, 5000, 3000)
        result = inject_image_gso(data, ph_off, gso_records)

        pt_rec = next(r for r in iter_records(result) if r.tag_id == HWPTAG_PARA_TEXT)
        pt_text_part = pt_rec.payload[:10]
        assert pt_text_part == text.encode("utf-16-le")
        assert pt_rec.payload.endswith(b"\x0d\x00")
        assert len(pt_rec.payload) == len(pt_data) + 16  # +16B GSO inline


class TestSeedPatchImageE2E:
    def test_add_image_to_hwp(self, tmp_path):
        """Parse HWP → add ImageBlock → render via Seed Patch → verify OLE streams."""
        src = str(_FIXTURES / "f01_plain_text.hwp")
        doc = parse_hwp(src)
        assert doc.verbatim is not None

        img_path = tmp_path / "test.png"
        img_path.write_bytes(_1X1_PNG)

        img_block = ImageBlock(
            id="b_new_img",
            type="image",
            src=str(img_path),
            width=50.0,
            height=50.0,
        )
        first_block_id = doc.blocks[0].id
        doc.add_block(img_block, after=first_block_id)

        out_path = str(tmp_path / "output.hwp")
        render_hwp(doc, out_path, validate=False)

        import olefile
        ole = olefile.OleFileIO(out_path)
        streams = ["/".join(s) for s in ole.listdir()]
        bin_streams = [s for s in streams if s.startswith("BinData/")]
        ole.close()

        assert len(bin_streams) >= 1, f"Expected BinData stream, got: {streams}"

    def test_add_image_preserves_text(self, tmp_path):
        """Adding image should preserve original text content."""
        src = str(_FIXTURES / "f01_plain_text.hwp")
        doc_orig = parse_hwp(src)
        orig_texts = [
            "".join(i.text for i in b.inlines if hasattr(i, "text"))
            for b in doc_orig.blocks
            if hasattr(b, "inlines")
        ]

        doc = parse_hwp(src)
        img_path = tmp_path / "test.png"
        img_path.write_bytes(_1X1_PNG)
        img_block = ImageBlock(
            id="b_new_img", type="image",
            src=str(img_path), width=50.0, height=50.0,
        )
        doc.add_block(img_block, after=doc.blocks[0].id)

        out_path = str(tmp_path / "output.hwp")
        render_hwp(doc, out_path, validate=False)

        doc_out = parse_hwp(out_path)
        out_texts = [
            "".join(i.text for i in b.inlines if hasattr(i, "text"))
            for b in doc_out.blocks
            if hasattr(b, "inlines")
        ]
        for orig_t in orig_texts:
            if orig_t.strip():
                assert any(orig_t.rstrip() in ot for ot in out_texts), \
                    f"Original text '{orig_t[:40]}...' not found in output"

    def test_no_image_stays_seed_patch(self, tmp_path):
        """Without new images, regular Seed Patch should still work."""
        src = str(_FIXTURES / "f01_plain_text.hwp")
        doc = parse_hwp(src)
        out_path = str(tmp_path / "output.hwp")
        render_hwp(doc, out_path, validate=False)

        doc_out = parse_hwp(out_path)
        assert len(doc_out.blocks) > 0
