from abc import ABC, abstractmethod
from typing import Any, Dict

from catalog_imports.schema import UniversalProductDraft


class ProductExtractor(ABC):
    """Every source extractor must return the same source-neutral product draft."""

    key = "base"

    @abstractmethod
    def can_handle(self, url: str = "", source=None) -> bool:
        raise NotImplementedError

    @abstractmethod
    def extract(self, *, url: str = "", html: str = "", context: Dict[str, Any] | None = None) -> UniversalProductDraft:
        raise NotImplementedError
