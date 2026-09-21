import re
from html import escape
from typing import Any, Dict, Iterable, List, Tuple

from django.utils.html import strip_tags


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", strip_tags(str(value or ""))).strip()


def _unique(values: Iterable[Any], limit: int = 12) -> List[str]:
    result = []
    seen = set()
    for value in values:
        text = _clean_text(value)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _identity_label(draft) -> str:
    brand = _clean_text(getattr(draft, "brand", "") or getattr(draft, "manufacturer", ""))
    name = _clean_text(getattr(draft, "name", ""))
    model = _clean_text(getattr(draft, "model", ""))
    if name:
        return name
    values = [value for value in (brand, model) if value]
    return " ".join(values) or "Product"


def _flatten_specs(value: Any, prefix: str = "") -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            label = _clean_text(key).replace("_", " ").title()
            full = f"{prefix} — {label}" if prefix else label
            if isinstance(child, (dict, list, tuple)):
                rows.extend(_flatten_specs(child, full))
            else:
                text = _clean_text(child)
                if text:
                    rows.append((full, text))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value, 1):
            if isinstance(child, (dict, list, tuple)):
                rows.extend(_flatten_specs(child, prefix))
            else:
                text = _clean_text(child)
                if text:
                    rows.append((prefix or f"Detail {index}", text))
    return rows


def build_specifications_html(draft) -> str:
    rows = _flatten_specs(getattr(draft, "specifications", {}) or {})
    if rows:
        body = "".join(
            f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>"
            for label, value in rows[:100]
        )
        return (
            '<div class="arolana-specifications">'
            "<table><tbody>" + body + "</tbody></table></div>"
        )

    fallback = _clean_text(getattr(draft, "specifications_html", ""))
    if fallback:
        return f"<p>{escape(fallback)}</p>"
    return ""


def _physical_summary(draft):
    parts = []
    weight = getattr(draft, "weight", None)
    weight_unit = _clean_text(getattr(draft, "weight_unit", ""))
    if weight is not None and weight_unit:
        parts.append(f"Weight: {weight} {weight_unit}")

    values = (
        getattr(draft, "dimensions_length", None),
        getattr(draft, "dimensions_width", None),
        getattr(draft, "dimensions_height", None),
    )
    unit = _clean_text(getattr(draft, "dimension_unit", ""))
    if all(value is not None for value in values) and unit:
        parts.append(
            f"Dimensions: {values[0]} × {values[1]} × {values[2]} {unit}"
        )
    return parts


def build_description_html(draft) -> str:
    identity = _identity_label(draft)
    brand = _clean_text(
        getattr(draft, "brand", "") or getattr(draft, "manufacturer", "")
    )
    model = _clean_text(
        getattr(draft, "model", "") or getattr(draft, "manufacturer_sku", "")
    )
    category = _clean_text(
        getattr(draft, "subcategory", "") or getattr(draft, "category", "")
    )

    intro = identity
    if brand and brand.casefold() not in intro.casefold():
        intro = f"{brand} {intro}"

    first_sentence = f"{intro} is a {category.lower()}" if category else intro
    if model and model.casefold() not in intro.casefold():
        first_sentence += f" identified as model {model}"
    first_sentence = first_sentence.rstrip(".") + "."

    html = [f"<p>{escape(first_sentence)}</p>"]

    features = _unique(getattr(draft, "key_features", []) or [], limit=10)
    if features:
        html.append("<h3>Key features</h3><ul>")
        html.extend(f"<li>{escape(feature)}</li>" for feature in features)
        html.append("</ul>")

    physical = _physical_summary(draft)
    if physical:
        html.append("<h3>Physical details</h3><ul>")
        html.extend(f"<li>{escape(value)}</li>" for value in physical)
        html.append("</ul>")

    contents = _unique(getattr(draft, "package_contents", []) or [], limit=15)
    if contents:
        html.append("<h3>What's in the box</h3><ul>")
        html.extend(f"<li>{escape(value)}</li>" for value in contents)
        html.append("</ul>")

    warranty = dict(getattr(draft, "warranty", {}) or {})
    warranty_text = _clean_text(
        warranty.get("coverage_details") or warranty.get("coverage")
    )
    years = warranty.get("duration_years") or 0
    months = warranty.get("duration_months") or 0
    if warranty_text or years or months:
        bits = []
        if years:
            bits.append(f"{years} year{'s' if int(years) != 1 else ''}")
        if months:
            bits.append(f"{months} month{'s' if int(months) != 1 else ''}")
        duration = " ".join(bits)
        line = "Manufacturer warranty"
        if duration:
            line += f": {duration}"
        if warranty_text:
            line += f". {warranty_text}"
        html.append(f"<p><strong>{escape(line.rstrip('.'))}.</strong></p>")

    return "".join(html)


def build_seo(draft) -> Dict[str, str]:
    identity = _identity_label(draft)
    brand = _clean_text(
        getattr(draft, "brand", "") or getattr(draft, "manufacturer", "")
    )
    model = _clean_text(
        getattr(draft, "model", "") or getattr(draft, "manufacturer_sku", "")
    )
    category = _clean_text(
        getattr(draft, "subcategory", "") or getattr(draft, "category", "")
    )

    title_base = identity
    if brand and brand.casefold() not in title_base.casefold():
        title_base = f"{brand} {title_base}"

    if model and model.casefold() not in title_base.casefold():
        candidate = f"{title_base} {model}"
        if len(candidate) <= 50:
            title_base = candidate

    meta_title = f"{title_base} | Arolana"
    if len(meta_title) > 60:
        meta_title = title_base[:60].rstrip(" -|")

    desc = f"Shop {title_base} on Arolana."
    features = _unique(getattr(draft, "key_features", []) or [], limit=2)
    if features:
        desc += " " + "; ".join(features) + "."
    elif category:
        desc += f" View verified {category.lower()} specifications and product details."

    if len(desc) > 160:
        desc = desc[:157].rstrip(" ,;.-") + "..."

    keywords = _unique(
        [brand, identity, model, category] + list(getattr(draft, "tags", []) or []),
        limit=10,
    )
    return {
        "meta_title": meta_title,
        "meta_description": desc,
        "meta_keywords": ", ".join(keywords)[:200],
    }


def content_payload(draft) -> Dict[str, str]:
    payload = {
        "description": build_description_html(draft),
        "specifications": build_specifications_html(draft),
    }
    payload.update(build_seo(draft))
    return payload
