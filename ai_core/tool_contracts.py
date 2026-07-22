from .permissions import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_GUEST, ROLE_PROVIDER, ROLE_VENDOR


FEATURE_SMART_SHOPPING = "smart_shopping"


TOOL_CATALOG_SEARCH_PRODUCTS = "catalog.search_products"
TOOL_CATALOG_GET_PRODUCT_FACTS = "catalog.get_product_facts"
TOOL_CATALOG_COMPARE_PRODUCTS = "catalog.compare_products"
TOOL_SERVICES_MATCH_PROVIDERS = "services.match_providers"
TOOL_QUOTES_CREATE_QUOTE_REQUEST = "quotes.create_quote_request"


SHOPPING_ROLES = [ROLE_CUSTOMER, ROLE_GUEST, ROLE_VENDOR, ROLE_PROVIDER, ROLE_ADMIN]
QUOTE_ROLES = [ROLE_CUSTOMER, ROLE_GUEST, ROLE_ADMIN]


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
                "query": {"type": "string"},
                "category": {"type": "string"},
                "brand": {"type": "string"},
                "minimum_price": {"type": "number"},
                "maximum_price": {"type": "number"},
                "condition": {"type": "string"},
                "location": {"type": "string"},
                "required_features": {"type": "array", "items": {"type": "string"}},
                "installation_required": {"type": "boolean"},
                "result_limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "products": {"type": "array"},
                "source_references": {"type": "array"},
                "warnings": {"type": "array"},
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
            "properties": {"product_ref": {"type": ["string", "integer"]}},
            "required": ["product_ref"],
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"product": {"type": "object"}, "source_references": {"type": "array"}},
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
                "product_refs": {"type": "array", "minItems": 2, "items": {"type": ["string", "integer"]}},
                "requirements": {"type": "object"},
            },
            "required": ["product_refs"],
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "comparison_points": {"type": "array"},
                "source_references": {"type": "array"},
                "warnings": {"type": "array"},
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
                "query": {"type": "string"},
                "category": {"type": "string"},
                "product_ref": {"type": ["string", "integer"]},
                "country": {"type": "string"},
                "state": {"type": "string"},
                "city": {"type": "string"},
                "provider_type": {"type": "string"},
                "result_limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"providers": {"type": "array"}, "source_references": {"type": "array"}, "warnings": {"type": "array"}},
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
            "additionalProperties": True,
            "properties": {
                "customer_consent": {"type": "boolean"},
                "approved_guest_contact": {"type": "boolean"},
                "requirements": {"type": "object"},
                "conversation_id": {"type": ["string", "integer"]},
                "request_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "product_refs": {"type": "array"},
                "provider_ref": {"type": ["string", "integer"]},
                "source_references": {"type": "array"},
            },
            "required": ["customer_consent", "requirements", "conversation_id", "request_id", "idempotency_key"],
        },
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "quote_request": {"type": "object"},
                "created": {"type": "boolean"},
                "source_references": {"type": "array"},
                "warnings": {"type": "array"},
            },
            "required": ["quote_request", "created", "source_references", "warnings"],
        },
    },
}


def tool_contract(name):
    return TOOL_CONTRACTS[name]

