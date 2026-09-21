from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class UniversalProductDraft:
    """Source-neutral product representation used before touching Arolana Product."""

    # Source/evidence (internal only; never copied to storefront content)
    source_name: str = ""
    source_url: str = ""
    source_external_id: str = ""

    # Identity
    name: str = ""
    brand: str = ""
    manufacturer: str = ""
    model: str = ""
    manufacturer_sku: str = ""
    gtin: str = ""
    ean: str = ""
    upc: str = ""

    # Classification
    category: str = ""
    subcategory: str = ""
    condition: str = "brand_new"

    # Commerce
    source_price: Optional[Decimal] = None
    source_currency: str = "NGN"
    availability: str = ""

    # Content
    short_description: str = ""
    description: str = ""
    specifications_html: str = ""
    specifications: Dict[str, Any] = field(default_factory=dict)
    key_features: List[str] = field(default_factory=list)
    package_contents: List[str] = field(default_factory=list)

    # Manufacturer / physical
    country_of_origin: str = ""
    manufacturer_address: str = ""
    certifications: List[str] = field(default_factory=list)
    weight: Optional[Decimal] = None
    weight_unit: str = "kg"
    dimensions_length: Optional[Decimal] = None
    dimensions_width: Optional[Decimal] = None
    dimensions_height: Optional[Decimal] = None
    dimension_unit: str = "cm"

    # Warranty / shipping
    warranty: Dict[str, Any] = field(default_factory=dict)
    shipping: Dict[str, Any] = field(default_factory=dict)

    # Related data
    variants: List[Dict[str, Any]] = field(default_factory=list)
    accessories: List[Dict[str, Any]] = field(default_factory=list)
    images: List[Dict[str, Any]] = field(default_factory=list)
    videos: List[Dict[str, Any]] = field(default_factory=list)
    manuals: List[Dict[str, Any]] = field(default_factory=list)

    # Arolana-generated/enriched content
    meta_title: str = ""
    meta_description: str = ""
    meta_keywords: str = ""
    tags: List[str] = field(default_factory=list)

    # Confidence/evidence
    evidence: Dict[str, Any] = field(default_factory=dict)
    confidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for key in (
            "source_price",
            "weight",
            "dimensions_length",
            "dimensions_width",
            "dimensions_height",
        ):
            value = data.get(key)
            if isinstance(value, Decimal):
                data[key] = str(value)
        return data

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]):
        data = dict(payload or {})
        for key in (
            "source_price",
            "weight",
            "dimensions_length",
            "dimensions_width",
            "dimensions_height",
        ):
            value = data.get(key)
            if value not in (None, ""):
                data[key] = Decimal(str(value))
        allowed = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in data.items() if key in allowed})
