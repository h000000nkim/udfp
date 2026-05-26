"""Abstract base class for format parsers."""

from abc import ABC, abstractmethod
from typing import ClassVar

from udf.core.schema import UdfDocument


class FormatParser(ABC):
    """Abstract base for all format-specific parsers.

    Subclasses must define ``source_format`` and implement :meth:`parse`.
    """

    source_format: ClassVar[str]

    @abstractmethod
    def parse(self, path: str) -> UdfDocument:
        """Parse a file into a UdfDocument.

        Parameters
        ----------
        path : str
            Filesystem path to the source document.

        Returns
        -------
        UdfDocument
            The parsed document model.
        """
        ...
