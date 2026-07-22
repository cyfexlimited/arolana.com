from .permissions import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_GUEST, ROLE_PROVIDER, ROLE_VENDOR


FEATURE_SMART_SHOPPING = "smart_shopping"


TOOL_CATALOG_SEARCH_PRODUCTS = "catalog.search_products"
TOOL_CATALOG_GET_PRODUCT_FACTS = "catalog.get_product_facts"
TOOL_CATALOG_COMPARE_PRODUCTS = "catalog.compare_products"
TOOL_SERVICES_MATCH_PROVIDERS = "services.match_providers"
TOOL_QUOTES_CREATE_QUOTE_REQUEST = "quotes.create_quote_request"


SHOPPING_ROLES = [ROLE_CUSTOMER, ROLE_GUEST, ROLE_VENDOR, ROLE_PROVIDER, ROLE_ADMIN]
QUOTE_ROLES = [ROLE_CUSTOMER, ROLE_GUEST, ROLE_ADMIN]

SOURCE_REFERENCE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "label": {"type": "string", "minLength": 1, "maxLength": 240},
        "type": {"type": "string", "minLength": 1, "maxLength": 80},
        "ref": {"type": "string", "minLength": 1, "maxLength": 240},
        "url": {"type": "string", "maxLength": 500},
    },
    "required": ["label", "type", "ref", "url"],
}
SOURCE_REFERENCES_SCHEMA = {"type": "array", "maxItems": 100, "items": SOURCE_REFERENCE_SCHEMA}
WARNINGS_SCHEMA = {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 500}}
PRODUCT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "public_ref": {"type": "string", "minLength": 1}, "name": {"type": "string"},
        "slug": {"type": "string"}, "public_url": {"type": "string"},
        "category": {"type": "string"}, "brand": {"type": "string"},
        "approval_state": {"type": "string", "enum": ["approved"]},
        "condition": {"type": "string"}, "description_summary": {"type": "string"},
        "normalised_specifications": {"type": "string"}, "displayed_price": {"type": "string"},
        "compare_price": {"type": "string"}, "stock_status": {"type": "string", "enum": ["in_stock", "out_of_stock"]},
        "base_amount": {"type": "string"}, "base_currency": {"type": "string"},
        "display_amount": {"type": ["string", "null"]}, "display_currency": {"type": ["string", "null"]},
        "warranty": {"type": "object"}, "shipping": {"type": "object"},
        "approved_public_offers": {"type": "array", "items": {"type": "object"}},
        "public_media": {"type": "object"},
        "source_references": SOURCE_REFERENCES_SCHEMA,
    },
    "required": ["public_ref", "name", "slug", "public_url", "base_amount", "base_currency", "source_references"],
}


TOOL_CONTRACTS = {
    TOOL_CATALOG_SEARCH_PRODUCTS: {
        "name": TOOL_CATALOG_SEARCH_PRODUCTS,
        "version": "1.0",
        "feature": FEATURE_SMART_SHOPPING,
        "description": "Search active approved public catalog products.",
        "allowed_roles": SHOPPING_ROLES,
        "read_only": True,
        "timeout_seconds": 4,
        "required": [],
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "maxLength": 500},
                "category": {"type": "string", "maxLength": 160},
                "brand": {"type": "string", "maxLength": 160},
                "minimum_price": {"type": "number", "minimum": 0},
                "maximum_price": {"type": "number", "minimum": 0},
                "condition": {"type": "string", "enum": ["brand_new", "open_box", "uk_used", "foreign_used", "locally_used", "refurbished", "fairly_used", "certified_pre_owned"]},
                "location": {"type": "string", "maxLength": 240},
                "required_features": {"type": "array", "maxItems": 20, "items": {"type": "string", "minLength": 1, "maxLength": 160}},
                "installation_required": {"type": "boolean"},
                "result_limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "products": {"type": "array", "maxItems": 10, "items": PRODUCT_SCHEMA},
                "source_references": SOURCE_REFERENCES_SCHEMA,
                "warnings": WARNINGS_SCHEMA,
            },
            "required": ["products", "source_references", "warnings"],
        },
    },
    TOOL_CATALOG_GET_PRODUCT_FACTS: {
        "name": TOOL_CATALOG_GET_PRODUCT_FACTS,
        "version": "1.0",
        "feature": FEATURE_SMART_SHOPPING,
        "description": "Return canonical AI-safe public facts for one approved product.",
        "allowed_roles": SHOPPING_ROLES,
        "read_only": True,
        "timeout_seconds": 4,
        "required": ["product_ref"],
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"product_ref": {"type": ["string", "integer"], "minLength": 1, "maxLength": 180}},
            "required": ["product_ref"],
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"product": PRODUCT_SCHEMA, "source_references": SOURCE_REFERENCES_SCHEMA},
            "required": ["product", "source_references"],
        },
    },
    TOOL_CATALOG_COMPARE_PRODUCTS: {
        "name": TOOL_CATALOG_COMPARE_PRODUCTS,
        "version": "1.0",
        "feature": FEATURE_SMART_SHOPPING,
        "description": "Compare approved products using only canonical product facts.",
        "allowed_roles": SHOPPING_ROLES,
        "read_only": True,
        "timeout_seconds": 5,
        "required": ["product_refs"],
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "product_refs": {"type": "array", "minItems": 2, "maxItems": 10, "items": {"type": ["string", "integer"], "minLength": 1, "maxLength": 180}},
                "requirements": {"type": "object", "additionalProperties": False, "properties": {"use_case": {"type": "string", "maxLength": 500}, "budget": {"type": "number", "minimum": 0}, "currency": {"type": "string", "enum": ["NGN", "USD", "GBP", "EUR", "GHS", "ZAR"]}}},
            },
            "required": ["product_refs"],
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "comparison_points": {"type": "array", "maxItems": 100, "items": {"type": "object", "additionalProperties": False, "properties": {"label": {"type": "string"}, "product": {"type": "string"}, "confirmed_value": {"type": "string"}, "status": {"type": "string", "enum": ["confirmed", "unavailable"]}, "source_references": SOURCE_REFERENCES_SCHEMA}, "required": ["label", "product", "confirmed_value", "status", "source_references"]}},
                "source_references": SOURCE_REFERENCES_SCHEMA,
                "warnings": WARNINGS_SCHEMA,
            },
            "required": ["comparison_points", "source_references", "warnings"],
        },
    },
    TOOL_SERVICES_MATCH_PROVIDERS: {
        "name": TOOL_SERVICES_MATCH_PROVIDERS,
        "version": "1.0",
        "feature": FEATURE_SMART_SHOPPING,
        "description": "Match approved public installers/service providers.",
        "allowed_roles": SHOPPING_ROLES,
        "read_only": True,
        "timeout_seconds": 4,
        "required": [],
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "maxLength": 500},
                "category": {"type": "string", "maxLength": 160},
                "product_ref": {"type": ["string", "integer"]},
                "country": {"type": "string", "maxLength": 100},
                "state": {"type": "string", "maxLength": 100},
                "city": {"type": "string", "maxLength": 100},
                "provider_type": {"type": "string", "maxLength": 60},
                "result_limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"providers": {"type": "array", "maxItems": 10, "items": {"type": "object"}}, "source_references": SOURCE_REFERENCES_SCHEMA, "warnings": WARNINGS_SCHEMA},
            "required": ["providers", "source_references", "warnings"],
        },
    },
    TOOL_QUOTES_CREATE_QUOTE_REQUEST: {
        "name": TOOL_QUOTES_CREATE_QUOTE_REQUEST,
        "version": "1.0",
        "feature": FEATURE_SMART_SHOPPING,
        "description": "Create an idempotent draft service quote request for human/provider review.",
        "allowed_roles": QUOTE_ROLES,
        "read_only": False,
        "timeout_seconds": 6,
        "required": ["customer_consent", "requirements", "conversation_id", "request_id", "idempotency_key"],
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "customer_consent": {"type": "boolean"},
                "approved_guest_contact": {"type": "boolean"},
                "requirements": {"type": "object", "additionalProperties": False, "properties": {
                    "summary": {"type": "string", "minLength": 20, "maxLength": 1200},
                    "assumptions": {"type": "string", "maxLength": 500},
                    "missing_information": {"type": "string", "maxLength": 500},
                    "phone": {"type": "string", "maxLength": 30}, "state": {"type": "string", "maxLength": 100},
                    "city": {"type": "string", "maxLength": 100}, "location": {"type": "string", "maxLength": 160},
                    "address": {"type": "string", "maxLength": 500}, "service_needed": {"type": "string", "maxLength": 220},
                    "contact_preference": {"type": "string", "maxLength": 80}, "urgency": {"type": "string", "enum": ["normal", "urgent", "emergency"]},
                    "currency": {"type": "string", "enum": ["NGN", "USD", "GBP", "EUR", "GHS", "ZAR"]},
                    "amount": {"type": "number", "minimum": 0}, "base_amount": {"type": ["number", "null"], "minimum": 0},
                    "base_currency": {"type": ["string", "null"], "enum": ["NGN", "USD", "GBP", "EUR", "GHS", "ZAR", None]},
                    "conversion_rate": {"type": ["number", "null"], "minimum": 0}
                }, "required": ["summary"]},
                "conversation_id": {"type": ["string", "integer"]},
                "request_id": {"type": "string"},
                "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 160},
                "product_refs": {"type": "array", "maxItems": 10, "items": {"type": ["string", "integer"]}},
                "provider_ref": {"type": ["string", "integer"]},
                "source_references": {"type": "array", "maxItems": 20, "items": SOURCE_REFERENCE_SCHEMA},
                "guest_contact": {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string", "maxLength": 150}, "phone": {"type": "string", "maxLength": 30}, "whatsapp": {"type": "string", "maxLength": 30}, "email": {"type": "string", "maxLength": 254}}}
            },
            "required": ["customer_consent", "requirements", "conversation_id", "request_id", "idempotency_key"],
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "quote_request": {"type": "object"},
                "created": {"type": "boolean"},
                "source_references": SOURCE_REFERENCES_SCHEMA,
                "warnings": WARNINGS_SCHEMA,
            },
            "required": ["quote_request", "created", "source_references", "warnings"],
        },
    },
}


def tool_contract(name):
    return TOOL_CONTRACTS[name]
