from typing import Dict, Type

from .base import ProductExtractor


_REGISTRY: Dict[str, Type[ProductExtractor]] = {}


def register_extractor(extractor_class: Type[ProductExtractor]):
    key = getattr(extractor_class, "key", "").strip()
    if not key:
        raise ValueError("Extractor classes must define a non-empty key.")
    _REGISTRY[key] = extractor_class
    return extractor_class


def get_extractor(key: str) -> ProductExtractor:
    # Ensure built-ins have had a chance to register even when registry.py was
    # imported directly before catalog_imports.extractors.__init__.
    if key not in _REGISTRY:
        from . import generic as _generic  # noqa: F401
        from . import paykobo as _paykobo  # noqa: F401
    try:
        return _REGISTRY[key]()
    except KeyError as exc:
        raise LookupError(f"No product extractor registered for key '{key}'.") from exc


def registered_extractors():
    from . import generic as _generic  # noqa: F401
    from . import paykobo as _paykobo  # noqa: F401
    return dict(_REGISTRY)
