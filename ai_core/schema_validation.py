"""Small deterministic JSON-schema subset used by first-party AI tools.

This intentionally uses an internal validator rather than ``jsonschema`` so
production behaviour does not depend on an optional package.  Supported
keywords are the ones used by Arolana tool contracts: type (including unions),
required, properties, additionalProperties, items, enum, numeric bounds and
string/array length bounds.
"""
from decimal import Decimal
from urllib.parse import urlparse


class SchemaValidationError(ValueError):
    """A public-safe contract failure (never includes the rejected value)."""


def _matches_type(value, expected):
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def validate_schema(value, schema, *, path="value"):
    schema = schema or {}
    expected = schema.get("type")
    if expected:
        choices = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, item) for item in choices):
            raise SchemaValidationError(f"{path} has an invalid type.")

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{path} is not an allowed value.")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise SchemaValidationError(f"{path} is too short.")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SchemaValidationError(f"{path} is too long.")
        if schema.get("format") == "public-reference":
            validate_public_reference(value, path=path)

    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaValidationError(f"{path} is below the allowed minimum.")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaValidationError(f"{path} exceeds the allowed maximum.")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise SchemaValidationError(f"{path} has too few items.")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaValidationError(f"{path} has too many items.")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_schema(item, item_schema, path=f"{path}[{index}]")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                raise SchemaValidationError(f"{path}.{name} is required.")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise SchemaValidationError(f"{path} contains unsupported properties.")
        for name, child in value.items():
            if name in properties:
                validate_schema(child, properties[name], path=f"{path}.{name}")
    return True


def validate_public_reference(value, *, path="source reference"):
    """Accept an Arolana public path/URL or an opaque ``arolana:kind:ref``."""
    text = str(value or "").strip()
    if text.startswith("arolana:"):
        parts = text.split(":")
        if len(parts) == 3 and all(parts) and all("/" not in part for part in parts):
            return True
    parsed = urlparse(text)
    if parsed.scheme in ("", "https") and (not parsed.netloc or parsed.netloc in {"arolana.com", "www.arolana.com"}):
        path_value = parsed.path or ""
        blocked = ("/admin/", "/media/private/", "/private/", "/static/admin/")
        if path_value.startswith("/") and not any(item in path_value.lower() for item in blocked):
            return True
    raise SchemaValidationError(f"{path} is not a public Arolana reference.")


def validate_source_references(value, *, path="output"):
    """Recursively enforce the canonical source-reference object contract."""
    if isinstance(value, dict):
        if "source_references" in value:
            refs = value["source_references"]
            if not isinstance(refs, list):
                raise SchemaValidationError(f"{path}.source_references has an invalid type.")
            for index, ref in enumerate(refs):
                ref_path = f"{path}.source_references[{index}]"
                if not isinstance(ref, dict) or set(ref) != {"label", "type", "ref", "url"}:
                    raise SchemaValidationError(f"{ref_path} has an invalid shape.")
                for key in ("label", "type", "ref"):
                    if not isinstance(ref[key], str) or not ref[key].strip():
                        raise SchemaValidationError(f"{ref_path}.{key} is required.")
                public_value = ref["url"] or f"arolana:{ref['type']}:{ref['ref']}"
                validate_public_reference(public_value, path=ref_path)
        for key, child in value.items():
            if key != "source_references":
                validate_source_references(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_source_references(child, path=f"{path}[{index}]")
    return True
