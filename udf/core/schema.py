"""Backward compatibility — all types now in udf.schema and udf.pipeline."""

# ruff: noqa: F401

from udf.schema.blocks import (
    Block,
    BlockBase,
    BookmarkBlock,
    ChartBlock,
    CodeBlock,
    CommentBlock,
    DrawingBlock,
    EndnoteBlock,
    EquationBlock,
    FieldBlock,
    FooterBlock,
    FootnoteBlock,
    HeaderBlock,
    HeadingBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    OutlineItem,
    PageBreakBlock,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TableCell,
    TableColumnDef,
    TableRow,
    TextArtBlock,
    TextBoxBlock,
    UnknownBlock,
    UnsupportedFeature,
)
from udf.schema.formats import BlockFormat, CellFormat, PositionInfo, RevisionInfo, TabStop
from udf.schema.inlines import (
    CodeInline,
    EndnoteRefInline,
    EquationInline,
    FootnoteRefInline,
    ImageInline,
    Inline,
    LinkInline,
    RubyInline,
    TextInline,
)
from udf.schema.metadata import (
    ColumnDef,
    DocumentMetadata,
    PageBoundary,
    PageMargins,
    SectionDef,
)
from udf.pipeline.container import ConversionTrace, OriginalContainer
from udf.pipeline.document import UdfDocument
from udf.pipeline.loss import BlockLoss, LossCategory, LossReport
from udf.pipeline.verbatim import (
    BinDataDef,
    BorderFillDef,
    BulletDef,
    CharShapeDef,
    FontFallbacks,
    GlobalResources,
    NumberingDef,
    NumberingLevel,
    ParaShapeDef,
    StyleDef,
    TabDef,
    VerbatimBlock,
    VerbatimLayer,
)
