"""UDF Document Builder — 코드로 문서를 작성하는 fluent API.

Usage:
    from udf.builder import DocumentBuilder

    doc = (
        DocumentBuilder()
        .heading(1, "제목")
        .paragraph("본문입니다.", bold=True)
        .table([["이름", "나이"], ["홍길동", "30"]])
        .page_break()
        .image("photo.png", alt="사진")
        .build()
    )

    doc.to("md")
    doc.save("output.udf.json")
"""

from __future__ import annotations

import itertools

from udf.schema.blocks import (
    Block,
    CodeBlock,
    EquationBlock,
    HeadingBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    PageBreakBlock,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TableCell,
    TableRow,
)
from udf.schema.formats import BlockFormat
from udf.schema.inlines import TextInline
from udf.schema.metadata import DocumentMetadata
from udf.pipeline.document import UdfDocument


class DocumentBuilder:
    """Fluent API for constructing UdfDocument instances programmatically.

    Provides chainable methods for appending blocks (headings, paragraphs,
    tables, images, etc.) and finalizing into a ``UdfDocument``. Each method
    returns ``self`` so calls can be chained in a single expression.

    Parameters
    ----------
    source_format : str, default "udf"
        Format identifier stored in the resulting document's metadata.

    Examples
    --------
    >>> doc = (
    ...     DocumentBuilder()
    ...     .heading(1, "Title")
    ...     .paragraph("Body text.", bold=True)
    ...     .build()
    ... )
    """

    def __init__(self, source_format: str = "udf") -> None:
        """Initialize builder with an empty block list and sequential ID counter."""
        self._source_format = source_format
        self._blocks: list[Block] = []
        self._counter = itertools.count(1)
        self._metadata = DocumentMetadata()

    def _next_id(self) -> str:
        """Generate a sequential block ID."""
        return f"b_{next(self._counter):04d}"

    # ------------------------------------------------------------------
    # 메타데이터
    # ------------------------------------------------------------------

    def title(self, title: str) -> "DocumentBuilder":
        """Set the document title in metadata.

        Parameters
        ----------
        title : str
            Document title string.
        """
        self._metadata.title = title
        return self

    def author(self, author: str) -> "DocumentBuilder":
        """Set the document author in metadata.

        Parameters
        ----------
        author : str
            Author name.
        """
        self._metadata.author = author
        return self

    # ------------------------------------------------------------------
    # 블록 추가
    # ------------------------------------------------------------------

    def heading(
        self,
        level: int,
        text: str,
        *,
        bold: bool | None = None,
        font_size: float | None = None,
    ) -> "DocumentBuilder":
        """Append a heading block.

        Parameters
        ----------
        level : int
            Heading level, clamped to 1--6.
        text : str
            Heading text content.
        bold : bool or None, optional
            Override bold styling on the heading text.
        font_size : float or None, optional
            Font size in points.
        """
        inlines = [TextInline(text=text, bold=bold, font_size=font_size)]
        self._blocks.append(HeadingBlock(
            type="heading",
            id=self._next_id(),
            level=max(1, min(6, level)),
            text=text,
            inlines=inlines,
        ))
        return self

    def paragraph(
        self,
        text: str = "",
        *,
        bold: bool | None = None,
        italic: bool | None = None,
        font_size: float | None = None,
        font_name: str | None = None,
        alignment: str | None = None,
    ) -> "DocumentBuilder":
        """Append a paragraph block.

        Parameters
        ----------
        text : str, default ""
            Paragraph text. If empty, an empty paragraph is created.
        bold, italic : bool or None, optional
            Inline styling overrides.
        font_size : float or None, optional
            Font size in points.
        font_name : str or None, optional
            Font family name.
        alignment : str or None, optional
            Paragraph alignment (e.g. "center", "right").
        """
        inlines = [TextInline(
            text=text,
            bold=bold,
            italic=italic,
            font_size=font_size,
            font_name=font_name,
        )] if text else []
        fmt = BlockFormat(alignment=alignment) if alignment else None
        self._blocks.append(ParagraphBlock(
            type="paragraph",
            id=self._next_id(),
            inlines=inlines,
            format=fmt,
        ))
        return self

    def table(
        self,
        data: list[list[str]],
        *,
        header: bool = True,
    ) -> "DocumentBuilder":
        """Append a table block from a 2D string grid.

        Parameters
        ----------
        data : list of list of str
            Row-major cell text. First row is treated as header if *header* is True.
        header : bool, default True
            Whether the first row should repeat as a header row.
        """
        rows: list[TableRow] = []
        for row_data in data:
            cells: list[TableCell] = []
            for cell_text in row_data:
                cells.append(TableCell(
                    id=self._next_id(),
                    content=[ParagraphBlock(
                        type="paragraph",
                        id=self._next_id(),
                        inlines=[TextInline(text=cell_text)],
                    )],
                ))
            rows.append(TableRow(cells=cells))
        self._blocks.append(TableBlock(
            type="table",
            id=self._next_id(),
            rows=rows,
            repeat_header=header,
        ))
        return self

    def image(
        self,
        src: str,
        *,
        alt: str = "",
        width: float | None = None,
        height: float | None = None,
    ) -> "DocumentBuilder":
        """Append an image block.

        Parameters
        ----------
        src : str
            Image source path or URL.
        alt : str, default ""
            Alternative text for accessibility.
        width, height : float or None, optional
            Dimensions in points.
        """
        self._blocks.append(ImageBlock(
            type="image",
            id=self._next_id(),
            src=src,
            alt=alt,
            width=width,
            height=height,
        ))
        return self

    def list(
        self,
        items: list[str],
        *,
        ordered: bool = False,
    ) -> "DocumentBuilder":
        """Append a list block.

        Parameters
        ----------
        items : list of str
            Text content of each list item.
        ordered : bool, default False
            If True, create a numbered (ordered) list.
        """
        list_items: list[ListItem] = []
        for item_text in items:
            list_items.append(ListItem(
                id=self._next_id(),
                inlines=[TextInline(text=item_text)],
            ))
        self._blocks.append(ListBlock(
            type="list",
            id=self._next_id(),
            ordered=ordered,
            items=list_items,
        ))
        return self

    def code(
        self,
        code: str,
        *,
        language: str | None = None,
    ) -> "DocumentBuilder":
        """Append a fenced code block.

        Parameters
        ----------
        code : str
            Source code content.
        language : str or None, optional
            Language identifier for syntax highlighting.
        """
        self._blocks.append(CodeBlock(
            type="code",
            id=self._next_id(),
            code=code,
            language=language,
        ))
        return self

    def quote(self, text: str) -> "DocumentBuilder":
        """Append a blockquote containing a single paragraph.

        Parameters
        ----------
        text : str
            Quoted text content.
        """
        self._blocks.append(QuoteBlock(
            type="quote",
            id=self._next_id(),
            content=[ParagraphBlock(
                type="paragraph",
                id=self._next_id(),
                inlines=[TextInline(text=text)],
            )],
        ))
        return self

    def equation(
        self,
        latex: str,
    ) -> "DocumentBuilder":
        """Append a display math equation block.

        Parameters
        ----------
        latex : str
            LaTeX math expression.
        """
        self._blocks.append(EquationBlock(
            type="equation",
            id=self._next_id(),
            latex=latex,
        ))
        return self

    def horizontal_rule(self) -> "DocumentBuilder":
        """Append a horizontal rule (thematic break) block."""
        self._blocks.append(HorizontalRuleBlock(
            type="horizontal_rule",
            id=self._next_id(),
        ))
        return self

    def page_break(self) -> "DocumentBuilder":
        """Append a page break block."""
        self._blocks.append(PageBreakBlock(
            type="page_break",
            id=self._next_id(),
        ))
        return self

    def block(self, block: Block) -> "DocumentBuilder":
        """Append an arbitrary pre-constructed Block instance.

        Parameters
        ----------
        block : Block
            Any block conforming to the Document Model schema.
        """
        self._blocks.append(block)
        return self

    # ------------------------------------------------------------------
    # 빌드
    # ------------------------------------------------------------------

    def build(self) -> UdfDocument:
        """Finalize and return a new UdfDocument from accumulated blocks.

        Returns
        -------
        UdfDocument
            The constructed document instance.
        """
        return UdfDocument(
            source_format=self._source_format,
            metadata=self._metadata,
            blocks=list(self._blocks),
        )
