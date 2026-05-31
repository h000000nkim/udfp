"""UdfDocument — DocumentSchema + conversion infrastructure (verbatim, container, loss report)."""

from __future__ import annotations

import itertools
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

import base64
import os

from udf.schema.blocks import (
    Block,
    CommentBlock,
    DrawingBlock,
    HeadingBlock,
    FooterBlock,
    FootnoteBlock,
    EndnoteBlock,
    HeaderBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    OutlineItem,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TextBoxBlock,
)
from udf.schema.formats import BlockFormat
from udf.schema.document import DocumentSchema
from udf.schema.extensions import FormatExtension
from udf.schema.inlines import Inline, TextInline

from .container import ConversionTrace, OriginalContainer
from .loss import LossReport
from .verbatim import VerbatimLayer

_auto_id_counter = itertools.count(1)


def _next_auto_id(prefix: str) -> str:
    """Generate a unique auto-incrementing ID with the given prefix."""
    return f"{prefix}_{next(_auto_id_counter)}"


class UdfDocument(BaseModel):
    """Central API for manipulating documents in Universal Document Format.

    UdfDocument wraps a format-agnostic DocumentSchema (Document Model) and
    provides high-level operations for block/inline CRUD, text search/replace,
    table manipulation, and rendering to various output formats.

    It can be constructed from a file path (auto-detecting format), a dict,
    or keyword arguments. Lossless same-format roundtrips are supported via
    the verbatim layer; cross-format conversions carry a LossReport.

    Attributes
    ----------
    udf : str
        Schema version identifier.
    source_format : str
        Original format of the parsed document (e.g. "hwp", "docx", "pdf").
    document : DocumentSchema
        The format-agnostic document content (blocks, metadata, page boundaries).
    verbatim : VerbatimLayer or None
        Raw byte preservation layer for lossless same-format roundtrip.
    original_container : OriginalContainer or None
        Original file backup for Seed Patch mode generation.
    conversion_trace : ConversionTrace or None
        Parsing history and provenance.
    loss_report : LossReport or None
        Report of information lost during conversion.
    extensions : dict[str, FormatExtension]
        Format-specific properties (e.g. HWP emboss, DOCX tracked changes).
    outline : list[OutlineItem]
        Document outline / table of contents structure.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    udf: str = "1.0"
    source_format: str
    document: DocumentSchema = Field(default_factory=DocumentSchema)
    verbatim: VerbatimLayer | None = None
    original_container: OriginalContainer | None = None
    conversion_trace: ConversionTrace | None = None
    loss_report: LossReport | None = None
    extensions: dict[str, FormatExtension] = {}
    outline: list[OutlineItem] = []
    _content_modified: bool = False
    _image_cache: dict[str, bytes] = {}

    def __init__(self, path_or_data: Any = None, /, **kwargs: Any) -> None:
        """Create a UdfDocument from a file path, dict, or keyword arguments.

        Parameters
        ----------
        path_or_data : str, Path, or dict, optional
            If a string/Path, the file is parsed using the auto-detected format.
            If a dict, it is used as model data. If None, keyword args are used.
        **kwargs
            Keyword arguments forwarded to the Pydantic model. May include
            ``blocks``, ``metadata``, ``source_format``, etc.
        """
        if path_or_data is not None and not isinstance(path_or_data, dict):
            path = str(path_or_data)
            from udf.formats import get_registry
            from udf.parsers.detect import detect

            fmt = detect(path).format
            registry = get_registry()
            parser_fn = registry.resolve_parser(fmt)
            parsed = parser_fn(path)
            super().__init__(**parsed.model_dump())
        elif path_or_data is not None:
            super().__init__(**path_or_data, **kwargs)
        else:
            if "blocks" in kwargs or "metadata" in kwargs:
                doc_kwargs: dict[str, Any] = {}
                if "blocks" in kwargs:
                    doc_kwargs["blocks"] = kwargs.pop("blocks")
                if "metadata" in kwargs:
                    doc_kwargs["metadata"] = kwargs.pop("metadata")
                if "page_boundaries" in kwargs:
                    doc_kwargs["page_boundaries"] = kwargs.pop("page_boundaries")
                if "document" not in kwargs:
                    kwargs["document"] = DocumentSchema(**doc_kwargs)
            super().__init__(**kwargs)
        self._image_cache = {}

    # ------------------------------------------------------------------
    # Backward-compat aliases
    # ------------------------------------------------------------------

    @property
    def blocks(self) -> list:
        """Shortcut to ``document.blocks``."""
        return self.document.blocks

    @blocks.setter
    def blocks(self, value: list) -> None:
        """Set the document blocks list."""
        self.document.blocks = value

    @property
    def metadata(self):
        """Shortcut to ``document.metadata``."""
        return self.document.metadata

    @metadata.setter
    def metadata(self, value) -> None:
        """Set the document metadata."""
        self.document.metadata = value

    @property
    def page_boundaries(self) -> list:
        """Shortcut to ``document.page_boundaries``."""
        return self.document.page_boundaries

    @page_boundaries.setter
    def page_boundaries(self, value: list) -> None:
        """Set the page boundaries list."""
        self.document.page_boundaries = value

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UdfDocument:
        """Construct a UdfDocument from a dictionary.

        Parameters
        ----------
        data : dict[str, Any]
            Dictionary representation of the document.

        Returns
        -------
        UdfDocument
            The validated document instance.
        """
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> UdfDocument:
        """Construct a UdfDocument from a JSON string.

        Parameters
        ----------
        json_str : str
            JSON-encoded document.

        Returns
        -------
        UdfDocument
            The validated document instance.
        """
        return cls.model_validate_json(json_str)

    @classmethod
    def empty(cls, source_format: str = "udf") -> UdfDocument:
        """Create an empty document with no blocks.

        Parameters
        ----------
        source_format : str, default "udf"
            The source format label for the empty document.
        """
        return cls(source_format=source_format, blocks=[])

    # ------------------------------------------------------------------
    # 텍스트 검색/치환
    # ------------------------------------------------------------------

    def replace_text(self, old: str, new: str) -> int:
        """Replace all occurrences of a substring across all blocks.

        Parameters
        ----------
        old : str
            The substring to find.
        new : str
            The replacement string.

        Returns
        -------
        int
            Total number of replacements made.
        """
        count = 0
        for block in self.blocks:
            count += _replace_text_in_block(block, old, new)
        if count > 0:
            self._content_modified = True
        return count

    def find_text(self, pattern: str) -> list[dict[str, Any]]:
        """Search for a regex pattern across all blocks.

        Parameters
        ----------
        pattern : str
            Regular expression pattern to search for.

        Returns
        -------
        list of dict
            Each match dict contains ``block_id``, ``text``, ``start``, ``end``.
        """
        import re
        compiled = re.compile(pattern)
        matches: list[dict[str, Any]] = []
        for block in self.blocks:
            _find_text_in_block(block, compiled, matches)
        return matches

    # ------------------------------------------------------------------
    # 블록 CRUD (deep — 전체 트리 재귀 탐색)
    # ------------------------------------------------------------------

    def get_block(self, block_id: str) -> Block | None:
        """Retrieve a block by ID, searching the entire tree recursively.

        Parameters
        ----------
        block_id : str
            The unique block identifier to search for.

        Returns
        -------
        Block or None
            The found block, or None if no block with that ID exists.
        """
        block, _, _ = _find_block_deep(self.blocks, block_id)
        return block

    def find_blocks(
        self,
        block_type: str | None = None,
        **filters: Any,
    ) -> list[Block]:
        """Find all blocks matching a type and/or attribute filters.

        Parameters
        ----------
        block_type : str or None
            Block type string (e.g. "paragraph", "table"). None matches all.
        **filters
            Additional attribute equality checks (e.g. ``level=2``).

        Returns
        -------
        list of Block
            All matching blocks found via deep traversal.
        """
        result: list[Block] = []
        _collect_blocks(self.blocks, block_type, filters, result)
        return result

    def add_block(
        self,
        block: Block,
        *,
        parent_id: str | None = None,
        after: str | None = None,
    ) -> None:
        """Insert a block into the document tree.

        Parameters
        ----------
        block : Block
            The block to insert.
        parent_id : str or None
            If given, insert into the content list of this parent block.
        after : str or None
            If given, insert after the block with this ID.
        """
        self._cache_image_if_needed(block)
        if parent_id is not None:
            parent = self.get_block(parent_id)
            if parent is not None:
                target = _get_content_list(parent)
                if target is not None:
                    if after is None:
                        target.append(block)
                    else:
                        for i, b in enumerate(target):
                            if b.id == after:
                                target.insert(i + 1, block)
                                return
                        target.append(block)
                    return
        if after is None:
            self.blocks.append(block)
            return
        for i, b in enumerate(self.blocks):
            if b.id == after:
                self.blocks.insert(i + 1, block)
                return
        self.blocks.append(block)

    def remove_block(self, block_id: str) -> Block | None:
        """Remove a block by ID from anywhere in the tree.

        Returns
        -------
        Block or None
            The removed block, or None if not found.
        """
        block, parent_list, idx = _find_block_deep(self.blocks, block_id)
        if block is not None and parent_list is not None and idx is not None:
            self._content_modified = True
            return parent_list.pop(idx)
        return None

    def move_block(
        self,
        block_id: str,
        *,
        parent_id: str | None = None,
        after: str | None = None,
    ) -> bool:
        """Move a block to a new position in the tree.

        Parameters
        ----------
        block_id : str
            ID of the block to move.
        parent_id : str or None
            Target parent block ID. None means top-level.
        after : str or None
            Insert after this block ID within the target.

        Returns
        -------
        bool
            True if the block was found and moved, False otherwise.
        """
        removed = self.remove_block(block_id)
        if removed is None:
            return False
        self.add_block(removed, parent_id=parent_id, after=after)
        return True

    # ------------------------------------------------------------------
    # Inline 조작
    # ------------------------------------------------------------------

    def get_inline(self, block_id: str, idx: int) -> Inline | None:
        """Get an inline element by block ID and index.

        Parameters
        ----------
        block_id : str
            ID of the block containing the inline.
        idx : int
            Zero-based index of the inline element.

        Returns
        -------
        Inline or None
            The inline element, or None if not found or index out of range.
        """
        inlines = self._get_inlines_for(block_id)
        if inlines is not None and 0 <= idx < len(inlines):
            return inlines[idx]
        return None

    def set_inline_text(self, block_id: str, idx: int, text: str) -> None:
        """Set the text content of an inline element at the given index.

        Parameters
        ----------
        block_id : str
            ID of the block containing the inline.
        idx : int
            Zero-based index of the inline element.
        text : str
            New text content to set.
        """
        block = self.get_block(block_id)
        if block is None:
            return
        self._content_modified = True
        if isinstance(block, HeadingBlock):
            block.text = text
            if block.inlines and 0 <= idx < len(block.inlines):
                inline = block.inlines[idx]
                if hasattr(inline, "text"):
                    block.inlines[idx] = inline.model_copy(update={"text": text})
            elif idx == 0 and not block.inlines:
                block.inlines.append(TextInline(type="text", text=text))
            return
        inlines = _get_inlines(block)
        if inlines is None:
            return
        if 0 <= idx < len(inlines):
            inline = inlines[idx]
            if hasattr(inline, "text"):
                inlines[idx] = inline.model_copy(update={"text": text})
        elif idx == 0 and not inlines:
            inlines.append(TextInline(type="text", text=text))

    def set_inline_format(self, block_id: str, idx: int, **fmt: Any) -> None:
        """Update formatting attributes of an inline element.

        Parameters
        ----------
        block_id : str
            ID of the block containing the inline.
        idx : int
            Zero-based index of the inline element.
        **fmt
            Formatting attributes to update (e.g. ``bold=True``).
        """
        inlines = self._get_inlines_for(block_id)
        if inlines is not None and 0 <= idx < len(inlines):
            inline = inlines[idx]
            valid = {k: v for k, v in fmt.items() if k in type(inline).model_fields}
            if valid:
                inlines[idx] = inline.model_copy(update=valid)
                self._content_modified = True

    def add_inline(
        self, block_id: str, inline: Inline, *, at: int | None = None,
    ) -> None:
        """Append or insert an inline element into a block's inline list.

        Parameters
        ----------
        block_id : str
            Target block ID.
        inline : Inline
            The inline element to add.
        at : int or None
            Insertion index. None appends to the end.
        """
        inlines = self._get_inlines_for(block_id)
        if inlines is None:
            return
        self._content_modified = True
        if at is None:
            inlines.append(inline)
        else:
            inlines.insert(at, inline)

    def remove_inline(self, block_id: str, idx: int) -> Inline | None:
        """Remove an inline element by index.

        Parameters
        ----------
        block_id : str
            ID of the block containing the inline.
        idx : int
            Zero-based index of the inline element to remove.

        Returns
        -------
        Inline or None
            The removed inline element, or None if index was invalid.
        """
        inlines = self._get_inlines_for(block_id)
        if inlines is not None and 0 <= idx < len(inlines):
            self._content_modified = True
            return inlines.pop(idx)
        return None

    def split_inline(self, block_id: str, idx: int, offset: int) -> None:
        """Split a text inline into two at the given character offset.

        Parameters
        ----------
        block_id : str
            Block containing the inline.
        idx : int
            Index of the inline to split.
        offset : int
            Character position at which to split. Must be within (0, len).
        """
        inlines = self._get_inlines_for(block_id)
        if inlines is None or not (0 <= idx < len(inlines)):
            return
        inline = inlines[idx]
        if not hasattr(inline, "text"):
            return
        text = inline.text
        if not (0 < offset < len(text)):
            return
        left = inline.model_copy(update={"text": text[:offset]})
        right = inline.model_copy(update={"text": text[offset:]})
        inlines[idx] = left
        inlines.insert(idx + 1, right)

    def _get_inlines_for(self, block_id: str) -> list | None:
        """Retrieve the inlines list for a block by ID."""
        block = self.get_block(block_id)
        if block is None:
            return None
        return _get_inlines(block)

    # ------------------------------------------------------------------
    # Block 서식
    # ------------------------------------------------------------------

    def get_block_format(self, block_id: str) -> BlockFormat | None:
        """Get the format object of a block.

        Parameters
        ----------
        block_id : str
            The target block ID.

        Returns
        -------
        BlockFormat or None
            The block's format, or None if the block was not found
            or has no format attribute.
        """
        block = self.get_block(block_id)
        if block is not None:
            return getattr(block, "format", None)
        return None

    def set_block_format(self, block_id: str, **fmt: Any) -> None:
        """Update or create the format of a block.

        Parameters
        ----------
        block_id : str
            Target block ID.
        **fmt
            Format attributes to set (e.g. ``alignment="center"``).
        """
        block = self.get_block(block_id)
        if block is None:
            return
        self._content_modified = True
        current = getattr(block, "format", None)
        if current is not None:
            block.format = current.model_copy(update=fmt)  # type: ignore[attr-defined]
        else:
            block.format = BlockFormat(**fmt)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # 테이블 구조 조작
    # ------------------------------------------------------------------

    def get_cell(
        self, table_id: str, row: int, col: int,
    ) -> Any | None:
        """Get a table cell by table ID and row/column indices.

        Parameters
        ----------
        table_id : str
            ID of the target TableBlock.
        row : int
            Zero-based row index.
        col : int
            Zero-based column index.

        Returns
        -------
        TableCell or None
            The cell at the given position, or None if not found.
        """
        block = self.get_block(table_id)
        if not isinstance(block, TableBlock):
            return None
        if 0 <= row < len(block.rows):
            cells = block.rows[row].cells
            if 0 <= col < len(cells):
                return cells[col]
        return None

    def add_table_row(
        self, table_id: str, *, at: int | None = None,
    ) -> Any | None:
        """Add a new row to a table, matching the column count of the first row.

        Parameters
        ----------
        table_id : str
            ID of the target TableBlock.
        at : int or None
            Row index to insert at. None appends to the end.

        Returns
        -------
        TableRow or None
            The newly created row, or None if the table was not found.
        """
        from udf.schema.blocks import TableRow, TableCell
        block = self.get_block(table_id)
        if not isinstance(block, TableBlock) or not block.rows:
            return None
        ncols = len(block.rows[0].cells)
        new_row = TableRow(cells=[
            TableCell(id=_next_auto_id("cell"), content=[])
            for _ in range(ncols)
        ])
        if at is None:
            block.rows.append(new_row)
        else:
            block.rows.insert(at, new_row)
        return new_row

    def remove_table_row(
        self, table_id: str, row_idx: int,
    ) -> Any | None:
        """Remove a row from a table by index.

        Parameters
        ----------
        table_id : str
            ID of the target TableBlock.
        row_idx : int
            Zero-based row index to remove.

        Returns
        -------
        TableRow or None
            The removed row, or None if the table or index was invalid.
        """
        block = self.get_block(table_id)
        if not isinstance(block, TableBlock):
            return None
        if 0 <= row_idx < len(block.rows):
            return block.rows.pop(row_idx)
        return None

    def add_table_column(
        self, table_id: str, *, at: int | None = None,
    ) -> None:
        """Add a new column to every row in a table.

        Parameters
        ----------
        table_id : str
            ID of the target TableBlock.
        at : int or None
            Column index to insert at. None appends to the end.
        """
        from udf.schema.blocks import TableCell
        block = self.get_block(table_id)
        if not isinstance(block, TableBlock):
            return
        for row in block.rows:
            cell = TableCell(
                id=_next_auto_id("cell"),
                content=[],
            )
            if at is None:
                row.cells.append(cell)
            else:
                row.cells.insert(at, cell)

    def remove_table_column(
        self, table_id: str, col_idx: int,
    ) -> None:
        """Remove a column from every row in a table by index.

        Parameters
        ----------
        table_id : str
            ID of the target TableBlock.
        col_idx : int
            Zero-based column index to remove from each row.
        """
        block = self.get_block(table_id)
        if not isinstance(block, TableBlock):
            return
        for row in block.rows:
            if 0 <= col_idx < len(row.cells):
                row.cells.pop(col_idx)

    def merge_cells(
        self, table_id: str, r1: int, c1: int, r2: int, c2: int,
    ) -> None:
        """Merge a rectangular range of cells in a table.

        Parameters
        ----------
        table_id : str
            ID of the target TableBlock.
        r1, c1 : int
            Top-left corner (row, column) of the merge range.
        r2, c2 : int
            Bottom-right corner (row, column) of the merge range.
        """
        block = self.get_block(table_id)
        if not isinstance(block, TableBlock):
            return
        if not (0 <= r1 <= r2 < len(block.rows)):
            return
        if not (0 <= c1 <= c2 < len(block.rows[r1].cells)):
            return
        top_left = self.get_cell(table_id, r1, c1)
        if top_left is None:
            return
        top_left.col_span = c2 - c1 + 1
        top_left.row_span = r2 - r1 + 1
        for ri in range(r1, r2 + 1):
            if ri >= len(block.rows):
                break
            for ci in range(c1, c2 + 1):
                if ri == r1 and ci == c1:
                    continue
                if ci < len(block.rows[ri].cells):
                    block.rows[ri].cells[ci].content = []
                    block.rows[ri].cells[ci].col_span = 1
                    block.rows[ri].cells[ci].row_span = 1

    def split_cell(
        self, table_id: str, row: int, col: int,
    ) -> None:
        """Unmerge a cell by resetting its spans to 1.

        Spanned cells retain their empty content; only the span attributes
        of the target cell are reset.
        """
        block = self.get_block(table_id)
        if not isinstance(block, TableBlock):
            return
        cell = self.get_cell(table_id, row, col)
        if cell is None:
            return
        cell.col_span = 1
        cell.row_span = 1

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def set_metadata(self, **kwargs: Any) -> None:
        """Update document metadata fields.

        Only attributes that already exist on the metadata object are set;
        unknown keys are silently ignored.
        """
        for k, v in kwargs.items():
            if hasattr(self.metadata, k):
                setattr(self.metadata, k, v)

    # ------------------------------------------------------------------
    # 편의 프로퍼티
    # ------------------------------------------------------------------

    @property
    def tables(self) -> list[TableBlock]:
        """All TableBlock instances in the document (deep search)."""
        return self.find_blocks("table")  # type: ignore[return-value]

    @property
    def images(self) -> list[ImageBlock]:
        """All ImageBlock instances in the document (deep search)."""
        return self.find_blocks("image")  # type: ignore[return-value]

    @property
    def headings(self) -> list[HeadingBlock]:
        """All HeadingBlock instances in the document (deep search)."""
        return self.find_blocks("heading")  # type: ignore[return-value]

    @property
    def paragraphs(self) -> list[ParagraphBlock]:
        """All ParagraphBlock instances in the document (deep search)."""
        return self.find_blocks("paragraph")  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # 이미지 캐시
    # ------------------------------------------------------------------

    def _cache_image_if_needed(self, block: Block) -> None:
        if not isinstance(block, ImageBlock):
            return
        src = block.src
        if not src or src in self._image_cache:
            return
        data = self._read_image_bytes(src)
        if data is not None:
            self._image_cache[src] = data

    @staticmethod
    def _read_image_bytes(src: str) -> bytes | None:
        if src.startswith("data:"):
            try:
                _, encoded = src.split(",", 1)
                return base64.b64decode(encoded)
            except Exception:
                return None
        if src.startswith("bindata:"):
            return None
        if os.path.isfile(src):
            with open(src, "rb") as f:
                return f.read()
        return None

    def resolve_image(self, src: str) -> bytes | None:
        """Resolve image bytes from cache, verbatim layer, or filesystem.

        Parameters
        ----------
        src : str
            Image source string (file path, data: URI, or bindata: reference).

        Returns
        -------
        bytes or None
            Image binary data, or None if unresolvable.
        """
        if src in self._image_cache:
            return self._image_cache[src]
        if src.startswith("bindata:") and self.verbatim:
            key = src[len("bindata:"):]
            streams = getattr(self.verbatim, "bindata_streams", {}) or {}
            if key in streams:
                data = streams[key]
                if isinstance(data, str):
                    return base64.b64decode(data)
                return data
            for skey in streams:
                bare = skey.rsplit(".", 1)[0]
                if bare == key:
                    data = streams[skey]
                    if isinstance(data, str):
                        return base64.b64decode(data)
                    return data
        return self._read_image_bytes(src)

    # ------------------------------------------------------------------
    # 렌더링 편의 메서드
    # ------------------------------------------------------------------

    def to(self, fmt: str, output_path: str | None = None, **kwargs: Any) -> str | None:
        """Render the document to a target format.

        Parameters
        ----------
        fmt : str
            Target format (e.g. "hwp", "docx", "md", "html").
        output_path : str or None
            File path to write the output. If None, returns the rendered string
            (for text formats) or writes to a temp path.
        **kwargs
            Additional options forwarded to the renderer.

        Returns
        -------
        str or None
            The output file path, or rendered text for string-based formats.
        """
        from udf.renderers import render
        return render(self, fmt, output_path=output_path, **kwargs)

    def to_html(self, **kwargs: Any) -> str:
        """Render the document to a complete HTML5 string.

        Parameters
        ----------
        **kwargs
            Forwarded to the HTML renderer (e.g. embed_images, embed_ids).

        Returns
        -------
        str
            Complete HTML document string.
        """
        result = self.to("html", **kwargs)
        return result if isinstance(result, str) else ""

    def to_json(self, **kwargs: Any) -> str:
        """Serialize the document to a JSON string.

        Returns
        -------
        str
            Pretty-printed JSON representation.
        """
        try:
            return self.model_dump_json(indent=2, **kwargs)
        except Exception:
            import json
            return json.dumps(self.model_dump(), indent=2, ensure_ascii=False, default=str)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the document to a dictionary.

        Returns
        -------
        dict[str, Any]
            Full dictionary representation of the document.
        """
        return self.model_dump()

    def save(self, path: str) -> None:
        """Save the document to a file.

        The output format is determined by the file extension:
        - ``.hwp``, ``.docx``, ``.hwpx`` → render to that binary format
        - ``.md``, ``.html`` → render to that text format
        - ``.json`` or other → save as UDF JSON

        Parameters
        ----------
        path : str
            Destination file path.
        """
        from pathlib import Path as _P

        ext = _P(path).suffix.lower()
        _RENDER_EXTS = {".hwp", ".docx", ".hwpx", ".md", ".html"}
        if ext in _RENDER_EXTS:
            self.to(ext.lstrip("."), output_path=path)
        else:
            _P(path).write_text(self.to_json(), encoding="utf-8")




# ------------------------------------------------------------------
# Private helpers (deep traversal)
# ------------------------------------------------------------------


def _iter_content_lists(block: Block) -> list[list]:
    """Return all nested content lists contained within a block."""
    result: list[list] = []
    if isinstance(block, TableBlock):
        for row in block.rows:
            for cell in row.cells:
                result.append(cell.content)
    elif isinstance(block, ListBlock):
        result.append(block.items)  # type: ignore[arg-type]
    elif isinstance(block, DrawingBlock):
        result.append(block.content)
        result.append(block.children)  # type: ignore[arg-type]
    elif isinstance(block, (
        TextBoxBlock, QuoteBlock, FootnoteBlock, EndnoteBlock,
        HeaderBlock, FooterBlock, CommentBlock,
    )):
        result.append(getattr(block, "content", []))
    return result


def _find_block_deep(
    blocks: list, block_id: str,
) -> tuple[Block | None, list | None, int | None]:
    """Recursively find a block by ID, returning (block, parent_list, index)."""
    for i, block in enumerate(blocks):
        if block.id == block_id:
            return block, blocks, i
        for content_list in _iter_content_lists(block):
            found, parent, idx = _find_block_deep(content_list, block_id)
            if found is not None:
                return found, parent, idx
        if isinstance(block, ListBlock):
            for item in block.items:
                found = _find_in_list_items(item, block_id)
                if found[0] is not None:
                    return found
    return None, None, None


def _find_in_list_items(
    item: ListItem, block_id: str,
) -> tuple[Block | None, list | None, int | None]:
    """Search within list item children for a block by ID."""
    for i, child in enumerate(item.children):
        if child.id == block_id:
            return child, item.children, i  # type: ignore[return-value]
        result = _find_in_list_items(child, block_id)
        if result[0] is not None:
            return result
    return None, None, None


def _collect_blocks(
    blocks: list,
    block_type: str | None,
    filters: dict,
    result: list,
) -> None:
    """Recursively collect blocks matching type and filter criteria."""
    for block in blocks:
        if block_type is None or getattr(block, "type", None) == block_type:
            if all(getattr(block, k, None) == v for k, v in filters.items()):
                result.append(block)
        for content_list in _iter_content_lists(block):
            _collect_blocks(content_list, block_type, filters, result)


def _get_content_list(block: Block) -> list | None:
    """Return the block's primary content list for insertion operations."""
    if isinstance(block, TableBlock):
        return None
    lists = _iter_content_lists(block)
    return lists[0] if lists else None


def _get_inlines(block: Block) -> list | None:
    """Return the block's inlines list, or None if it has no inlines."""
    if hasattr(block, "inlines"):
        return block.inlines  # type: ignore[return-value]
    return None


# ------------------------------------------------------------------
# Private helpers (text editing)
# ------------------------------------------------------------------


def _replace_text_in_block(block: Block, old: str, new: str) -> int:
    """Replace text within a block and its children, returning replacement count."""
    count = 0
    if isinstance(block, ParagraphBlock):
        for i, inline in enumerate(block.inlines):
            if hasattr(inline, "text") and old in inline.text:
                n = inline.text.count(old)
                count += n
                block.inlines[i] = inline.model_copy(
                    update={"text": inline.text.replace(old, new)}
                )
    elif isinstance(block, HeadingBlock):
        if old in block.text:
            count += block.text.count(old)
            block.text = block.text.replace(old, new)
    elif isinstance(block, TableBlock):
        for row in block.rows:
            for cell in row.cells:
                for cb in cell.content:
                    count += _replace_text_in_block(cb, old, new)
    elif isinstance(block, ListBlock):
        for item in block.items:
            for inline in item.inlines:
                if hasattr(inline, "text") and old in inline.text:
                    n = inline.text.count(old)
                    count += n
                    idx = item.inlines.index(inline)
                    item.inlines[idx] = inline.model_copy(
                        update={"text": inline.text.replace(old, new)}
                    )
            for child in item.children:
                for inline in child.inlines:
                    if hasattr(inline, "text") and old in inline.text:
                        n = inline.text.count(old)
                        count += n
                        idx = child.inlines.index(inline)
                        child.inlines[idx] = inline.model_copy(
                            update={"text": inline.text.replace(old, new)}
                        )
    elif isinstance(block, (TextBoxBlock, FootnoteBlock, EndnoteBlock)):
        content = getattr(block, "content", [])
        for cb in content:
            count += _replace_text_in_block(cb, old, new)
    return count


def _find_text_in_block(
    block: Block,
    pattern: "re.Pattern[str]",
    matches: list[dict[str, Any]],
) -> None:
    """Find regex matches within a block and append to the matches list."""

    if isinstance(block, ParagraphBlock):
        for inline in block.inlines:
            if hasattr(inline, "text"):
                for m in pattern.finditer(inline.text):
                    matches.append({
                        "block_id": block.id,
                        "text": m.group(),
                        "start": m.start(),
                        "end": m.end(),
                    })
    elif isinstance(block, HeadingBlock):
        for m in pattern.finditer(block.text):
            matches.append({
                "block_id": block.id,
                "text": m.group(),
                "start": m.start(),
                "end": m.end(),
            })
    elif isinstance(block, TableBlock):
        for row in block.rows:
            for cell in row.cells:
                for cb in cell.content:
                    _find_text_in_block(cb, pattern, matches)
    elif isinstance(block, (TextBoxBlock, FootnoteBlock, EndnoteBlock)):
        content = getattr(block, "content", [])
        for cb in content:
            _find_text_in_block(cb, pattern, matches)
