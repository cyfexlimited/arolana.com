import json
import logging
import re
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings

from ai_core.feature_flags import external_provider_enabled, smart_shopping_enabled
from ai_core.intent import (
    UNSUPPORTED_INTENT,
    normalize_primary_intent,
    unsupported_marketplace_response,
)
from ai_core.models import AIModelConfig
from ai_core.permissions import role_for_user
from ai_core.providers import provider_for_config
from ai_core.registry import active_prompt
from ai_core.tool_contracts import (
    FEATURE_SMART_SHOPPING,
    TOOL_CATALOG_COMPARE_PRODUCTS,
    TOOL_CATALOG_GET_PRODUCT_FACTS,
    TOOL_CATALOG_SEARCH_PRODUCTS,
    TOOL_QUOTES_CREATE_QUOTE_REQUEST,
    TOOL_SERVICES_MATCH_PROVIDERS,
)
from ai_core.tools import ensure_default_tool_definitions, execute_ai_tool
from installers.models import ServiceQuoteRequest
from .context_state import (
    _apply_universal_state_fields,
    extract_facts,
    has_locked_shopping_category,
    is_explicit_category_change,
    is_flow_reset,
    normalized_state,
    shopping_category_label,
    slot_updates_from_facts,
)
from .intent_guards import (
    CLARIFICATION_INTENT,
    CLARIFICATION_REPLY,
    CONVERSATIONAL_GOODBYE,
    CONVERSATIONAL_GRATITUDE,
    CONVERSATIONAL_GREETING,
    CONVERSATIONAL_IDENTITY,
    ORDER_INTENT,
    REQUIREMENTS_INTENT,
    REQUIREMENTS_REPLY,
    SUPPORT_INTENT,
    clean_product_search_query,
    conversational_reply,
    resolve_customer_intent,
)


PROMPT_KEY = "smart_shopping_assistant"
PROMPT_FEATURE = FEATURE_SMART_SHOPPING
logger = logging.getLogger(__name__)


def _text(value):
    return str(value or "").strip()


def _conversation_state(conversation):
    context = dict(conversation.context or {})
    legacy_state = normalized_state(conversation)
    smart_state = dict(context.get("smart_shopping") or {})

    if smart_state:
        state = {
            **legacy_state,
            **smart_state,
            "requirements": {
                **dict(legacy_state.get("requirements") or {}),
                **dict(smart_state.get("requirements") or {}),
            },
        }
    else:
        state = legacy_state

    return context, state


def _state_debug_snapshot(state):
    requirements = dict((state or {}).get("requirements") or {})
    return {
        "active_subject": (state or {}).get("active_subject", ""),
        "category": (state or {}).get("category", ""),
        "product_type": (state or {}).get("product_type", ""),
        "locked_category": (state or {}).get("locked_category", ""),
        "shopping_category_locked": bool((state or {}).get("shopping_category_locked")),
        "flow": (state or {}).get("flow", ""),
        "intent_family": (state or {}).get("intent_family", ""),
        "transaction_type": (state or {}).get("transaction_type", ""),
        "entity_type": (state or {}).get("entity_type", ""),
        "missing_slots": list((state or {}).get("missing_slots") or []),
        "completed_slots": list((state or {}).get("completed_slots") or []),
        "requirements": {
            key: value
            for key, value in requirements.items()
            if value not in (None, "")
        },
    }


def _category_change_reason(message, state, facts):
    previous_category = shopping_category_label(state)
    new_category = facts.get("category") or facts.get("product_type") or facts.get("subject") or ""
    if is_flow_reset(message):
        return "flow_reset"
    if not new_category:
        return "no_new_category"
    if not previous_category:
        return "initial_category"
    if str(previous_category).lower() == str(new_category).lower():
        return "same_category"
    if is_explicit_category_change(message):
        return "explicit_category_change"
    return "category_frozen"


def _contextual_budget_values(message):
    comparable = re.sub(
        r"\s+",
        " ",
        str(message or "").strip().lower(),
    ).strip(" .,!?:;")
    if not re.fullmatch(
        r"(?:₦|ngn|naira|n|\$|usd)?\s*[\d,.]+\s*[km]?"
        r"(?:\s*-\s*(?:₦|ngn|naira|n|\$|usd)?\s*[\d,.]+\s*[km]?)?",
        comparable,
    ):
        return []

    values = []
    for match in re.finditer(
        r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<suffix>[km])?",
        comparable,
    ):
        try:
            value = Decimal(match.group("number").replace(",", ""))
        except InvalidOperation:
            continue
        suffix = (match.group("suffix") or "").lower()
        if suffix == "k":
            value *= 1000
        elif suffix == "m":
            value *= 1000000
        if value >= 1000:
            values.append(int(value))
    return values


def _apply_shopping_session_update(state, message):
    before = _state_debug_snapshot(state)
    facts = extract_facts(message)
    if _active_service_flow(state) and not _explicit_product_request(message):
        facts["entity_type"] = "service_provider"
        facts["intent_family"] = "service"
        facts["transaction_type"] = (
            "install"
            if re.search(r"\binstall(?:er|ation|ing)?|setup|set up\b", str(message or "").lower())
            else facts.get("transaction_type") or state.get("transaction_type") or "find_provider"
        )
        facts.pop("category", None)
        facts.pop("subcategory", None)
        facts.pop("product_type", None)
        facts.pop("catalog_category_id", None)
        fact_requirements = facts.setdefault("requirements", {})
        if fact_requirements.get("delivery_location") and not fact_requirements.get("service_location"):
            fact_requirements["service_location"] = fact_requirements["delivery_location"]
    contextual_budget_values = (
        _contextual_budget_values(message)
        if has_locked_shopping_category(state)
        else []
    )
    if (
        contextual_budget_values
        and not (facts.get("requirements") or {}).get("budget_max")
    ):
        requirements = facts.setdefault("requirements", {})
        if len(contextual_budget_values) > 1:
            requirements["budget_min"] = min(contextual_budget_values)
            requirements["minimum_budget"] = min(contextual_budget_values)
        requirements["budget_max"] = max(contextual_budget_values)
        requirements["maximum_budget"] = max(contextual_budget_values)
        requirements["budget_amount"] = max(contextual_budget_values)
    slot_updates = slot_updates_from_facts(facts)
    previous_category = shopping_category_label(state)
    previous_entity_type = str(state.get("entity_type") or "").strip().lower()
    incoming_entity_type = str(facts.get("entity_type") or "").strip().lower()
    entity_type_changed = bool(
        previous_entity_type
        and incoming_entity_type
        and previous_entity_type != incoming_entity_type
    )

    if entity_type_changed:
        state["shopping_category_locked"] = False
        state["locked_category"] = ""
        state["category"] = ""
        state["subcategory"] = ""
        state["product_type"] = ""
        state["catalog_category_id"] = None
        state["requirements"] = {}
        state["brand"] = ""

    incoming_catalog_category_id = facts.get("catalog_category_id")
    previous_catalog_category_id = state.get("catalog_category_id")
    incoming_named_category = (
        facts.get("category")
        or facts.get("product_type")
        or ""
    )
    previous_named_category = (
        state.get("category")
        or state.get("product_type")
        or ""
    )
    catalog_category_changed = bool(
        incoming_catalog_category_id
        and (
            not previous_catalog_category_id
            or str(incoming_catalog_category_id)
            != str(previous_catalog_category_id)
        )
        and incoming_named_category
        and str(incoming_named_category).strip().lower()
        != str(previous_named_category).strip().lower()
    )

    new_category = facts.get("category") or facts.get("product_type") or facts.get("subject") or ""
    reason = _category_change_reason(message, state, facts)
    reset_flow = reason == "flow_reset"
    state["_clear_legacy_requirements"] = bool(
        entity_type_changed
        or catalog_category_changed
        or reason in {
            "explicit_category_change",
            "flow_reset",
        }
    )

    if catalog_category_changed:
        state["requirements"] = {}
        state["brand"] = ""
        state["shopping_category_locked"] = False
        state["locked_category"] = ""

    if reset_flow:
        state["shopping_category_locked"] = False
        state["locked_category"] = ""
        state["category"] = ""
        state["product_type"] = ""
        state["catalog_category_id"] = None
        state["requirements"] = {}

    if new_category and reason in {"initial_category", "same_category", "explicit_category_change"}:
        if reason == "explicit_category_change" and facts.get("subject") and not facts.get("category"):
            state["category"] = ""
            state["product_type"] = ""
            state["catalog_category_id"] = None
        for key in ("category", "subcategory", "product_type", "catalog_category_id"):
            value = facts.get(key)
            if value not in (None, ""):
                state[key] = value
        state["shopping_category_locked"] = True
        state["locked_category"] = state.get("product_type") or state.get("category") or new_category
        if reason == "explicit_category_change":
            state["requirements"] = {}

    requirements = dict(state.get("requirements") or {})
    for key, value in slot_updates.items():
        if key == "brand":
            state["brand"] = value
            requirements["brand"] = value
        else:
            requirements[key] = value
    state["requirements"] = requirements
    _apply_universal_state_fields(
        state,
        facts,
        explicit_change=reason == "explicit_category_change",
        reset_flow=reset_flow,
    )

    locked_category = shopping_category_label(state)
    if (
        previous_category
        and locked_category
        and str(previous_category).strip().lower()
        != str(locked_category).strip().lower()
    ):
        state["_clear_legacy_requirements"] = True

    if locked_category:
        state["active_subject"] = locked_category
        state["last_search_query"] = locked_category
    state["flow"] = "shopping_requirements" if slot_updates else state.get("flow") or "catalog_search"
    after = _state_debug_snapshot(state)
    debug = {
        "previous_category": previous_category,
        "new_category": shopping_category_label(state),
        "reason_for_change": reason,
        "slot_updates": slot_updates,
        "shopping_state_before": before,
        "shopping_state_after": after,
        "previous_intent_family": before.get("intent_family", ""),
        "resolved_intent_family": state.get("intent_family", ""),
        "previous_transaction_type": before.get("transaction_type", ""),
        "resolved_transaction_type": state.get("transaction_type", ""),
        "subject_change_detected": reason in {"initial_category", "explicit_category_change", "flow_reset"},
        "subject_change_reason": reason,
    }
    logger.info("smart_shopping_session_state %s", debug)
    return facts, slot_updates, debug


def _missing_shopping_slots(state):
    return list(state.get("missing_slots") or [])


def _shopping_followup_reply(state):
    subject = shopping_category_label(state) or "that product"
    subject_text = str(subject or "").strip().lower()

    # Video-conferencing requests must first establish the room/use case.
    # Asking only for budget is too early and loses the grounded qualifier
    # expected by the existing SmartChat workflow.
    if any(
        marker in subject_text
        for marker in (
            "video conferencing",
            "video conference",
            "conferencing device",
            "conferencing system",
            "conference room",
        )
    ):
        return (
            "Is this for a small meeting room, boardroom, classroom, church "
            "or another space? Also tell me the number of participants and "
            "your budget so I can recommend the right conferencing system."
        )

    missing = _missing_shopping_slots(state)
    if missing:
        return f"Got it. I’ll keep looking for {subject}. What is your {missing[0]}?"
    return f"Got it. I’ll use that information to find suitable {subject} options on Arolana."


def _empty_result_reply(state, products, query=""):
    subject = (
        shopping_category_label(state)
        if state.get("catalog_category_id")
        else (query or state.get("active_subject") or "your request")
    )
    if (
        isinstance(subject, str)
        and subject
        and subject == subject.lower()
        and not any(char.isdigit() for char in subject)
    ):
        subject = subject.title()
    requirements = state.get("requirements") or {}
    details = []
    if requirements.get("brightness_requirement"):
        details.append(f"{requirements['brightness_requirement']} lumens")
    if requirements.get("budget_max"):
        currency = requirements.get("currency") or "NGN"
        symbol = "₦" if currency == "NGN" else f"{currency} "
        details.append(f"at or below {symbol}{requirements['budget_max']:,}")
    if requirements.get("delivery_location"):
        details.append(f"in {requirements['delivery_location']}")
    qualifier = " ".join(details)
    if products:
        return _products_reply(products, subject)
    return (
        f"I couldn’t find an active approved {subject} match"
        f"{(' for ' + qualifier) if qualifier else ''} in the live Arolana catalogue. "
        "I can try a wider search, look for a verified supplier, or connect you with support."
    )


def _catalog_payload_for_state(state, fallback_query):
    requirements = state.get("requirements") or {}
    # Only send a category filter when the parser matched an actual catalog
    # category. Free-form subjects such as "Logitech Group" or "Toyota Camry"
    # must remain search text; treating them as categories can zero out valid
    # catalogue matches and make follow-up state drift into unrelated domains.
    real_category = state.get("category") if state.get("catalog_category_id") else ""
    query = real_category or fallback_query
    payload = {
        "query": query,
        "category": real_category,
        "brand": state.get("brand") or requirements.get("brand") or "",
        "condition": requirements.get("condition") or "",
        "maximum_price": requirements.get("budget_max"),
        "location": requirements.get("delivery_location") or requirements.get("location") or "",
        "result_limit": 5,
        "required_features": [],
    }
    if requirements.get("resolution"):
        payload["required_features"].append(str(requirements["resolution"]).replace("_", " "))
    if requirements.get("brightness_requirement"):
        payload["required_features"].append(str(requirements["brightness_requirement"]))
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [])
    }


def _merge_requirements(state, message):
    requirements = (
        {}
        if state.get("_clear_legacy_requirements")
        else dict(state.get("requirements") or {})
    )
    text = message.lower()
    if not state.get("_clear_legacy_requirements"):
        requirements["summary"] = _text(
            f"{requirements.get('summary', '')} {message}"
        )[:1200]
    if "install" in text or "installation" in text or "installer" in text:
        requirements["installation_required"] = True
        requirements["service_needed"] = requirements.get("service_needed") or "Installation/service support"
    for marker in ("lagos", "abuja", "ibadan", "port harcourt"):
        if marker in text and not requirements.get("location"):
            requirements["location"] = marker.title()
    quote_words = ("quote", "quotation", "proposal", "professional estimate")
    if any(word in text for word in quote_words):
        declined = any(phrase in text for phrase in (
            "no quote", "don't create", "do not create", "not now", "decline",
        ))
        state["quote_creation_declined"] = declined
    state["requirements"] = requirements
    return requirements


def _active_service_flow(state):
    return (
        state.get("entity_type") == "service_provider"
        or state.get("intent_family") == "service"
        or state.get("transaction_type") in {
            "install",
            "repair",
            "maintain",
            "inspect",
            "consult",
            "book_service",
            "find_provider",
        }
    )


def _explicit_product_request(message):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    return bool(
        re.search(
            r"\b(?:show me|find|search for|compare|price of|how much|"
            r"buy|purchase|do you have|what equipment|which equipment|"
            r"products?|devices?|catalogue|catalog)\b",
            text,
        )
        and not re.search(
            r"\b(?:installer|install it|installing|installation|technician|"
            r"provider|engineer|repair|setup|set up|service)\b",
            text,
        )
    )


def _service_requirement_update(message):
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    return bool(
        re.search(
            r"\b(?:conference room|conferencing|boardroom|setup|set up|"
            r"install(?:er|ation|ing)?|repair|technician|provider|engineer|"
            r"location|in\s+[a-z][a-z\s-]+|urgent|urgently|asap|"
            r"as soon as possible|immediately|today|tomorrow|this week|"
            r"next week|sitters?|seaters?|people|participants|supply and installation|"
            r"installation only)\b",
            text,
        )
    )


def _classify(message, state):
    text = message.lower().strip()

    active_service_flow = _active_service_flow(state)
    generic_help_followup = any(
        phrase in text
        for phrase in (
            "help me",
            "please help",
            "do help",
            "can you help",
            "assist me",
            "please assist",
        )
    )

    if (
        active_service_flow
        and not _explicit_product_request(message)
        and (
            generic_help_followup
            or _service_requirement_update(message)
            or slot_updates_from_facts(extract_facts(message))
        )
    ):
        return TOOL_SERVICES_MATCH_PROVIDERS

    routed = resolve_customer_intent(message)
    if routed in {
        CONVERSATIONAL_GREETING,
        CONVERSATIONAL_GRATITUDE,
        CONVERSATIONAL_IDENTITY,
        CONVERSATIONAL_GOODBYE,
        REQUIREMENTS_INTENT,
        SUPPORT_INTENT,
    }:
        return routed
    if routed and routed != CLARIFICATION_INTENT:
        return routed
    if any(term in text for term in ("compare", "versus", " vs ")):
        return "catalog.compare_products"
    if any(term in text for term in ("quote", "quotation", "proposal", "professional estimate", "send request")):
        return "quotes.create_quote_request"
    if any(term in text for term in ("install", "installer", "installation", "service provider", "technician")):
        return "services.match_providers"
    if state.get("current_product_ref") and any(term in text for term in ("spec", "facts", "warranty", "manual", "video", "details")):
        return "catalog.get_product_facts"
    return CLARIFICATION_INTENT


def _extract_product_refs(conversation, state, message):
    refs = []
    if conversation.product_id:
        refs.append(str(conversation.product_id))
    if state.get("current_product_ref"):
        refs.append(state["current_product_ref"])
    for token in message.replace(",", " ").split():
        cleaned = token.strip().strip(".,;:()[]")
        if cleaned.isdigit() or "-" in cleaned:
            refs.append(cleaned)
    return list(dict.fromkeys(refs))


def _tool_context(conversation, actor_user, role, request_id, application_source):
    return {
        "user": actor_user,
        "role": role,
        "conversation_id": conversation.id,
        "request_id": request_id,
        "application_source": application_source,
        "session_key": conversation.session_key,
    }


def _public_error_reply():
    return (
        "I could not complete that Smart Shopping lookup safely, so I’ll keep using the regular "
        "Arolana chat flow. You can also ask for human support."
    )


def quote_request_readiness(conversation, requirements, intent, *, actor_user=None, state=None):
    """Pure readiness calculation. It never creates or mutates a quote."""
    state = state or {}
    missing = []
    if intent != TOOL_QUOTES_CREATE_QUOTE_REQUEST:
        missing.append("Ask for a professional quotation or proposal.")
    summary = _text(requirements.get("summary"))
    if len(summary) < 20:
        missing.append("Describe the required product, service or technical solution.")
    has_solution = bool(
        conversation.product_id
        or state.get("current_product_ref")
        or requirements.get("service_needed")
        or requirements.get("service_category")
        or requirements.get("technical_solution")
        or requirements.get("installation_required")
    )
    if not has_solution:
        missing.append("Select a product, service category or technical solution.")
    if not requirements.get("quantity"):
        missing.append("Provide the required quantity.")
    phone = _text(
        requirements.get("phone")
        or conversation.customer_phone
        or getattr(actor_user, "phone_number", "")
    )
    if not phone:
        missing.append("Provide a contact phone number for human review.")
    if not _text(requirements.get("location") or requirements.get("state") or requirements.get("city")):
        missing.append("Provide the service or delivery location.")
    if state.get("quote_creation_declined"):
        missing.append("Quote creation was declined in this conversation.")
    existing = ServiceQuoteRequest.objects.filter(
        admin_note__icontains=f"conversation_id={conversation.pk};",
    ).exists()
    if existing or state.get("quote_request_submitted"):
        missing.append("A quotation request has already been submitted for this conversation.")
    return not missing, missing


def _products_reply(products, query=""):
    if not products:
        cleaned_query = str(query or "").strip()

        if cleaned_query:
            return (
                f"I couldn’t find an active approved product matching "
                f"“{cleaned_query}” on Arolana yet. "
                "Try another product name or ask me to connect you "
                "with Arolana support."
            )

        return (
            "I couldn’t find an active approved product matching "
            "your request on Arolana yet. Try another product name "
            "or ask me to connect you with Arolana support."
        )

    lines = ["Approved Arolana products found:"]
    for product in products[:5]:
        price = product.get("displayed_price") or ""
        stock = product.get("stock_status") or "stock status unavailable"
        lines.append(
            f"• {product.get('name')} — {price} ({stock})"
        )

    lines.append(
        "These results come from active approved Arolana "
        "catalog records."
    )
    return "\n".join(lines)


def _requirement_acknowledgement(requirements):
    details = []
    if requirements.get("participant_count"):
        details.append(f"{requirements['participant_count']} people")
    if requirements.get("brightness_requirement"):
        details.append(f"{requirements['brightness_requirement']} lumens")
    if requirements.get("budget_max"):
        currency = requirements.get("currency") or "NGN"
        symbol = "₦" if currency == "NGN" else f"{currency} "
        details.append(f"budget up to {symbol}{requirements['budget_max']:,}")
    if requirements.get("delivery_location"):
        details.append(f"delivery in {requirements['delivery_location']}")
    if requirements.get("condition"):
        details.append(str(requirements["condition"]).replace("_", " "))
    if not details:
        return ""
    return "I used your requirement for " + ", ".join(details[:4]) + "."


def _providers_reply(providers, *, query="", state=None, requirements=None):
    if not providers:
        requirements = requirements or {}
        state = state or {}
        subject = shopping_category_label(state) or state.get("active_subject") or str(query or "").strip()
        location = (
            requirements.get("service_location")
            or requirements.get("delivery_location")
            or requirements.get("location")
            or ""
        )
        needs_asset = not subject or subject.lower() in {"an installer", "a installer", "installer", "service provider"}
        needs_location = not location
        if needs_asset or needs_location:
            missing = []
            if needs_asset:
                missing.append("what you need installed, repaired, maintained or inspected")
            if needs_location:
                missing.append("the job location")
            return (
                "Yes — I can help you find an approved Arolana service provider. "
                f"Tell me {' and '.join(missing)} so I can match the request properly."
            )
        return (
            f"I could not find an approved eligible service provider for {subject}"
            f"{(' in ' + location) if location else ''} yet. "
            "I can refine the service details or connect you with Arolana support."
        )
    lines = ["Approved service providers that may match:"]
    for provider in providers[:5]:
        lines.append(
            f"• {provider.get('business_name')} — {provider.get('location') or 'location not listed'}; rating {provider.get('average_rating')}"
        )
    lines.append("I’m not promising schedule, availability or price until a provider confirms.")
    return "\n".join(lines)


def _provider_search_query(state, requirements, user_message):
    """Build a provider query without letting generic service labels replace the asset."""
    requirements = requirements or {}
    state = state or {}

    generic_service_labels = {
        "installation/service support",
        "service provider",
        "installer",
        "installation",
        "install",
    }
    service_needed = _text(requirements.get("service_needed"))
    service_type = _text(requirements.get("service_type"))
    active_subject = _text(state.get("active_subject"))
    search_query = _text(state.get("search_query"))

    if service_type and service_type.lower() not in generic_service_labels:
        return service_needed or service_type
    if service_needed and service_needed.lower() not in generic_service_labels:
        return service_needed
    if active_subject and active_subject.lower() not in generic_service_labels:
        return active_subject
    if search_query and search_query.lower() not in generic_service_labels:
        return search_query
    return service_needed or service_type or active_subject or search_query or user_message


def _catalog_search_allowed_for_state(state):
    transaction = state.get("transaction_type") or ""
    entity_type = state.get("entity_type") or ""

    if transaction in {
        "rent",
        "lease",
        "short_let",
        "hire",
        "repair",
        "install",
        "maintain",
        "inspect",
        "consult",
        "book_service",
        "find_provider",
        "find_property",
        "find_vehicle",
    }:
        return False

    if entity_type in {
        "property",
        "vehicle",
        "service_provider",
        "software",
    }:
        return False

    return True


def _domain_preserving_marketplace_reply(state, requirements):
    subject = shopping_category_label(state) or state.get("active_subject") or "your request"
    transaction = (state.get("transaction_type") or "").replace("_", " ")
    entity_type = state.get("entity_type") or "marketplace"
    location = (
        requirements.get("service_location")
        or requirements.get("delivery_location")
        or requirements.get("location")
        or (state.get("location") or {}).get("delivery_location")
        or (state.get("location") or {}).get("service_location")
        or ""
    )
    location_phrase = f" in {location}" if location else ""
    if entity_type == "property":
        return (
            f"I’ll keep this as a {subject} property request{location_phrase}. "
            "Are you looking to rent or buy? "
            "Please also confirm the property type, exact location and budget. "
            "I could not confirm a matching live property listing in this response yet."
        )
    if (
        entity_type == "vehicle"
        and state.get("transaction_type") in {
            "rent",
            "lease",
            "short_let",
            "hire",
        }
    ):
        return (
            f"I’ll keep this as a {subject} rental request{location_phrase}. "
            "What rental date, passenger capacity, pickup location and budget should I use? "
            "I could not confirm matching live rental inventory in this response yet."
        )

    if entity_type == "vehicle":
        return (
            f"I’ll keep this as a {subject} vehicle request{location_phrase}. "
            "What year range, budget, condition and preferred location should I use? "
            "I could not confirm a matching live vehicle listing in this response yet."
        )

    if entity_type == "service_provider" or state.get("intent_family") == "service":
        return (
            f"I’ll keep this as a {subject} service-provider request{location_phrase}. "
            "I could not confirm an approved provider match in this response yet, "
            "but I can refine the service details or connect you with Arolana support."
        )
    if state.get("transaction_type") in {"rent", "lease", "short_let", "hire"}:
        return (
            f"I’ll keep this as a {subject} rental request{location_phrase}. "
            "I could not confirm matching rental inventory in this response yet. "
            "I can refine the date, location, capacity or budget."
        )
    if entity_type == "software":
        return (
            f"I’ll keep this as a {subject} software request. "
            "I could not confirm a matching live software listing in this response yet, "
            "but I can refine users, platform, licence model or budget."
        )
    return (
        f"I’ll keep this as a {subject} marketplace request{location_phrase}. "
        "I could not confirm a matching live listing in this response yet, "
        "but I will keep the subject and requirements together."
    )


def _comparison_reply(points):
    if not points:
        return "I could not compare those products because approved product references were not available."
    lines = ["Here is a grounded comparison from public product facts:"]
    for point in points[:10]:
        value = point.get("confirmed_value") or "Unavailable"
        lines.append(f"• {point.get('label')} — {point.get('product')}: {value}")
    lines.append("I won’t choose an overall winner unless your requirements make that clear.")
    return "\n".join(lines)

ALLOWED_SMART_SHOPPING_TOOLS = {
    TOOL_CATALOG_SEARCH_PRODUCTS,
    TOOL_CATALOG_GET_PRODUCT_FACTS,
    TOOL_CATALOG_COMPARE_PRODUCTS,
    TOOL_SERVICES_MATCH_PROVIDERS,
    TOOL_QUOTES_CREATE_QUOTE_REQUEST,
}


def _active_smart_shopping_model():
    """
    Return the active default model used for Smart Shopping.

    The query deliberately requires an active provider and default model.
    It returns None instead of raising when AI has not been configured.
    """
    return (
        AIModelConfig.objects
        .select_related("provider")
        .filter(
            feature=FEATURE_SMART_SHOPPING,
            provider__is_active=True,
            is_default=True,
        )
        .order_by("id")
        .first()
    )


def _parse_ai_response(value):
    """
    OpenAIProvider currently returns response.output_text.

    Structured-output responses therefore arrive as JSON text. This helper
    safely converts them into a dictionary without trusting arbitrary types.
    """
    if isinstance(value, dict):
        return value

    if not isinstance(value, str):
        raise ValueError("The AI provider did not return JSON text.")

    parsed = json.loads(value)

    if not isinstance(parsed, dict):
        raise ValueError("The AI provider response must be a JSON object.")

    return parsed


def _safe_ai_intent(value):
    """
    Only registered marketplace tools are allowed.

    A model-generated tool name is never executed unless it appears in this
    allow-list.
    """
    intent = normalize_primary_intent(_text(value))

    if intent in ALLOWED_SMART_SHOPPING_TOOLS:
        return intent

    return UNSUPPORTED_INTENT


def _merge_ai_requirements(state, ai_response, user_message):
    """
    Merge interpreted requirements into conversation state.

    Values explicitly returned as False or zero are preserved. Null and empty
    strings do not erase reliable values gathered earlier in the conversation.
    """
    existing = dict(state.get("requirements") or {})
    interpreted = ai_response.get("structured_requirements") or {}

    if not isinstance(interpreted, dict):
        interpreted = {}

    for key, value in interpreted.items():
        if value not in (None, ""):
            existing[key] = value

    previous_summary = _text(existing.get("summary"))
    interpreted_summary = _text(interpreted.get("summary"))

    if interpreted_summary:
        existing["summary"] = interpreted_summary[:1200]
    elif user_message:
        existing["summary"] = _text(
            f"{previous_summary} {user_message}"
        )[:1200]

    state["requirements"] = existing

    missing_information = ai_response.get("missing_information") or []
    if isinstance(missing_information, list):
        state["missing_slots"] = [
            _text(item)
            for item in missing_information
            if _text(item)
        ][:12]

    state["last_ai_assumptions"] = (
        ai_response.get("assumptions")
        if isinstance(ai_response.get("assumptions"), list)
        else []
    )
    state["last_ai_warnings"] = (
        ai_response.get("warnings")
        if isinstance(ai_response.get("warnings"), list)
        else []
    )
    state["last_ai_confidence"] = ai_response.get("confidence")

    return existing


def _ai_search_query(state, user_message):
    """
    Build a stable catalogue query without allowing a follow-up sentence to
    replace the active shopping subject.
    """
    locked_category = _text(
        state.get("current_category_locked")
        or state.get("locked_category")
    ).lower()

    locked_search_queries = {
        "video_conferencing": "video conferencing",
    }

    if locked_category in locked_search_queries:
        query = locked_search_queries[locked_category]
        state["active_subject"] = query
        state["last_search_query"] = query
        return query

    active_subject = _text(
        state.get("active_subject")
        or state.get("product_type")
        or state.get("category")
    )

    if active_subject:
        return active_subject

    cleaned = _text(clean_product_search_query(user_message))

    if cleaned:
        state["active_subject"] = cleaned
        state["last_search_query"] = cleaned
        return cleaned

    return _text(user_message)

def _run_interpretation_model(
    *,
    model_config,
    prompt,
    user_message,
    state,
    role,
    request_id,
):
    """
    First OpenAI call:

    Understand the latest message in the context of the current shopping
    conversation and select one approved marketplace intent.
    """
    provider = provider_for_config(model_config.provider)

    raw_response = provider.structured_response(
        model_config=model_config,
        prompt=prompt,
        input_payload={
            "stage": "interpretation_and_tool_selection",
            "latest_user_message": user_message,
            "previous_state": state,
            "allowed_primary_intents": sorted(
                ALLOWED_SMART_SHOPPING_TOOLS
            ),
            "instructions": [
                "Interpret the latest message using the previous conversation state.",
                "Do not treat a follow-up requirement as a new product subject.",
                "Select exactly one allowed primary intent.",
                "Do not invent products, prices, stock, providers or quotations.",
                "The marketplace database will execute the selected tool.",
            ],
        },
        role=role,
        feature=FEATURE_SMART_SHOPPING,
        request_id=request_id,
    )

    return _parse_ai_response(raw_response)


def _run_grounded_answer_model(
    *,
    model_config,
    prompt,
    user_message,
    state,
    interpretation,
    selected_intent,
    tool_payload,
    tool_result,
    role,
    request_id,
):
    """
    Second OpenAI call:

    Compose a natural response using only the marketplace tool result as the
    factual source for products, prices, stock and providers.
    """
    provider = provider_for_config(model_config.provider)

    raw_response = provider.structured_response(
        model_config=model_config,
        prompt=prompt,
        input_payload={
            "stage": "grounded_final_answer",
            "latest_user_message": user_message,
            "conversation_state": state,
            "interpreted_request": interpretation,
            "executed_tool": selected_intent,
            "tool_arguments": tool_payload,
            "marketplace_tool_result": tool_result,
            "instructions": [
                "Write the final customer-facing answer.",
                "Use the marketplace tool result as the only factual source.",
                "Never invent a product, price, stock status, provider or reference.",
                "Clearly say when no matching database record was returned.",
                "Do not claim that a quote request was created unless the tool result confirms it.",
                "Keep useful missing-information questions concise.",
            ],
        },
        role=role,
        feature=FEATURE_SMART_SHOPPING,
        request_id=request_id,
    )

    return _parse_ai_response(raw_response)


def _fallback_answer_for_tool(intent, tool_payload, tool_result, state):
    """
    Safe deterministic final-answer fallback when the second model call fails.
    """
    if intent == TOOL_CATALOG_GET_PRODUCT_FACTS:
        product = tool_result.get("product")
        return _products_reply([product] if product else [])

    if intent == TOOL_CATALOG_COMPARE_PRODUCTS:
        return _comparison_reply(
            tool_result.get("comparison_points") or []
        )

    if intent == TOOL_SERVICES_MATCH_PROVIDERS:
        return _providers_reply(
            tool_result.get("providers") or []
        )

    if intent == TOOL_CATALOG_SEARCH_PRODUCTS:
        return _empty_result_reply(
            state,
            tool_result.get("products") or [],
            tool_payload.get("query", ""),
        )

    return _public_error_reply()


def _product_cards(products):
    """
    Preserve both the legacy SmartChat card contract and the newer public
    marketplace fields. Resolve the real Product database ID even when an
    older tool payload contains only a name, slug or public reference.
    """
    cards = []

    try:
        from django.urls import reverse
        from django.db.models import Q
        from products.models import Product
    except Exception:
        Product = None
        Q = None
        reverse = None

    for item in products or []:
        if not isinstance(item, dict):
            continue

        public_ref = _text(item.get("public_ref"))
        slug = _text(item.get("slug") or public_ref)
        title_from_payload = _text(item.get("name") or item.get("title"))

        database_id = item.get("id")
        if database_id in (None, ""):
            database_id = item.get("product_id")

        if isinstance(database_id, str) and database_id.strip().isdigit():
            database_id = int(database_id.strip())

        product_obj = None

        if Product is not None:
            if isinstance(database_id, int):
                product_obj = Product.objects.filter(pk=database_id).first()

            if product_obj is None and slug:
                product_obj = Product.objects.filter(slug=slug).first()

            if product_obj is None and public_ref:
                # Legacy public_ref values may contain a numeric database ID.
                if public_ref.isdigit():
                    product_obj = Product.objects.filter(
                        pk=int(public_ref)
                    ).first()

                if product_obj is None:
                    product_obj = Product.objects.filter(
                        slug=public_ref
                    ).first()

            if product_obj is None and title_from_payload:
                product_obj = Product.objects.filter(
                    name__iexact=title_from_payload
                ).first()

            if product_obj is None and title_from_payload and Q is not None:
                # Final conservative fallback for differences in spacing/case.
                product_obj = Product.objects.filter(
                    Q(name__icontains=title_from_payload)
                    | Q(slug__icontains=slug)
                ).first()

        if product_obj is not None:
            database_id = product_obj.pk
            slug = slug or _text(getattr(product_obj, "slug", ""))
            public_ref = public_ref or slug

        title = title_from_payload or (
            getattr(product_obj, "name", "") if product_obj else ""
        )

        # A valid catalogue payload may have only a product name. Do not drop it.
        if not title and not slug and database_id in (None, ""):
            continue

        price = item.get("displayed_price", "")

        image_url = (
            (item.get("public_media") or {}).get("primary_image")
            or item.get("image")
            or ""
        )

        if not image_url and product_obj is not None:
            try:
                image_url = (
                    product_obj.main_image.url
                    if product_obj.main_image
                    else ""
                )
            except Exception:
                image_url = ""

        product_url = item.get("public_url", "")
        if not product_url and product_obj is not None:
            try:
                product_url = product_obj.get_absolute_url()
            except Exception:
                product_url = ""

        add_to_cart_url = ""
        if reverse is not None and slug:
            try:
                add_to_cart_url = reverse(
                    "products:add_to_cart",
                    args=[slug],
                )
            except Exception:
                add_to_cart_url = ""

        rating = (
            float(getattr(product_obj, "rating_avg", 0) or 0)
            if product_obj
            else 0.0
        )
        rating_count = (
            int(getattr(product_obj, "rating_count", 0) or 0)
            if product_obj
            else 0
        )
        available_stock = (
            int(getattr(product_obj, "available_stock", 0) or 0)
            if product_obj
            else 0
        )
        allow_backorder = (
            bool(getattr(product_obj, "allow_backorder", False))
            if product_obj
            else False
        )

        popular_qa = []
        if product_obj is not None:
            try:
                popular_qa = [
                    {
                        "question": question.question,
                        "answer": question.answer,
                    }
                    for question in product_obj.questions.filter(
                        is_public=True,
                    ).exclude(answer="")[:3]
                ]
            except Exception:
                popular_qa = []

        cards.append(
            {
                "id": (
                    database_id
                    if database_id not in (None, "")
                    else public_ref
                ),
                "title": title,
                "name": title,
                "slug": slug,
                "price": price,
                "price_display": price,
                "displayed_price": price,
                "url": product_url,
                "product_url": product_url,
                "public_ref": public_ref,
                "image": image_url,
                "image_url": image_url,
                "add_to_cart_url": add_to_cart_url,
                "rating": rating,
                "rating_count": rating_count,
                "review_count": rating_count,
                "in_stock": available_stock > 0 or allow_backorder,
                "stock_status": item.get("stock_status", ""),
                "popular_qa": popular_qa,
            }
        )

    return cards

def _legacy_source_type(
    intent,
    tool_result,
    *,
    clarification=False,
    non_catalog=False,
):
    """Map AI Core results to the existing SmartChat source-type contract."""
    tool_result = dict(tool_result or {})

    if clarification or non_catalog:
        return "clarification"

    if intent == TOOL_CATALOG_SEARCH_PRODUCTS:
        return (
            "product_database"
            if tool_result.get("products")
            else "catalog_empty_result"
        )

    if intent in {
        TOOL_CATALOG_GET_PRODUCT_FACTS,
        TOOL_CATALOG_COMPARE_PRODUCTS,
    }:
        return "product_database"

    if intent == TOOL_SERVICES_MATCH_PROVIDERS:
        return (
            "service_provider_database"
            if tool_result.get("providers")
            else "service_provider_empty_result"
        )

    if intent == TOOL_QUOTES_CREATE_QUOTE_REQUEST:
        return "quotation_request"

    return "clarification"


def _legacy_current_intent(intent, state):
    """
    Return the established SmartChat conversation intent.

    Message metadata can keep the exact AI tool intent while the conversation
    keeps the older workflow intent expected by existing views and tests.
    """
    state = dict(state or {})
    entity_type = str(state.get("entity_type") or "").strip().lower()

    if entity_type == "property":
        return "property_inquiry"

    if entity_type == "vehicle":
        return "vehicle_inquiry"

    if entity_type == "software":
        return "software_inquiry"

    if intent in {
        TOOL_CATALOG_SEARCH_PRODUCTS,
        TOOL_CATALOG_GET_PRODUCT_FACTS,
        TOOL_CATALOG_COMPARE_PRODUCTS,
    }:
        return "product_recommendation"

    if intent == TOOL_SERVICES_MATCH_PROVIDERS:
        return "service_provider_search"

    if intent == TOOL_QUOTES_CREATE_QUOTE_REQUEST:
        return "quote_request"

    return state.get("intent_family") or "clarification"


def _attach_compatibility_metadata(
    source,
    *,
    state_debug=None,
    tool_name=None,
):
    """Attach compatibility metadata consumed by existing SmartChat code."""
    if state_debug is not None:
        source["shopping_session"] = state_debug

    if tool_name is not None:
        source["tool_name"] = tool_name
    else:
        source.setdefault("tool_name", "none")

    return source


def _persist_smart_shopping_state(
    conversation,
    context,
    state,
    *,
    public_intent,
):
    """Persist Smart Shopping state in both current and legacy locations."""
    context = dict(context or {})
    state = dict(state or {})

    context["smart_shopping"] = state

    legacy_state = {
        **dict(context.get("state") or {}),
        **state,
    }
    if state.get("_clear_legacy_requirements"):
        legacy_state["requirements"] = {}
    context["state"] = legacy_state

    locked_category = shopping_category_label(state)
    canonical_locked_category = (
        state.get("category")
        or state.get("product_type")
        or locked_category
    )

    context["current_category_locked"] = (
        canonical_locked_category
        if state.get("shopping_category_locked") or canonical_locked_category
        else ""
    )

    context["current_category"] = (
        canonical_locked_category
        or state.get("category")
        or state.get("product_type")
        or ""
    )

    entity_type = str(state.get("entity_type") or "").strip().lower()
    if entity_type == "property":
        marketplace_category = "property"
    elif entity_type == "service_provider":
        marketplace_category = "service"
    elif entity_type in {"vehicle", "software"}:
        marketplace_category = entity_type
    else:
        marketplace_category = (
            state.get("category")
            or state.get("product_type")
            or canonical_locked_category
            or state.get("active_subject")
            or ""
        )

    previous_marketplace_category = str(
        context.get("marketplace_category") or ""
    ).strip().lower()
    current_marketplace_category = str(
        marketplace_category or ""
    ).strip().lower()

    if (
        previous_marketplace_category
        and current_marketplace_category
        and previous_marketplace_category != current_marketplace_category
    ):
        context["state"]["requirements"] = {}

    context["marketplace_category"] = marketplace_category

    context["catalog_category_id"] = state.get("catalog_category_id")

    conversation.context = context
    conversation.current_intent = public_intent
    conversation.save(
        update_fields=[
            "context",
            "current_intent",
            "updated_at",
        ]
    )

def smart_shopping_reply(
    conversation,
    user_message,
    *,
    actor_user=None,
    application_source="smartchat",
):
    """
    AI-first Smart Shopping pipeline.

    Flow:
        1. GPT interprets the message and selects an approved tool.
        2. Interpreted requirements are merged into conversation state.
        3. Arolana executes the selected database tool.
        4. GPT writes a final answer grounded in the tool result.
        5. State, tool provenance and structured output are persisted.

    The previous deterministic routing remains available as a safe fallback
    whenever the external provider is unavailable or fails.
    """
    if not smart_shopping_enabled():
        return None

    ensure_default_tool_definitions()

    context, state = _conversation_state(conversation)
    request_id = str(uuid.uuid4())
    role = role_for_user(actor_user)

    source = {
        "source_type": "ai_core_smart_shopping",
        "source_label": "Smart Shopping AI",
        "intent": "",
        "confidence": 0.0,
        "request_id": request_id,
        "tool_calls": [],
        "ai_pipeline": {
            "interpretation": False,
            "tool_execution": False,
            "grounded_answer": False,
            "fallback_used": False,
        },
        "structured_response": {
            "answer": "",
            "primary_intent": "",
            "structured_requirements": {},
            "clarifying_question": "",
            "products": [],
            "comparison_points": [],
            "missing_information": [],
            "assumptions": [],
            "warnings": [],
            "provider_suggestions": [],
            "next_actions": [],
            "source_references": [],
            "confidence": 0.0,
            "handoff_required": False,
            "quote_request_ready": False,
            "quote_request": {
                "created": False,
                "reference": None,
                "status": None,
                "next_step": None,
            },
        },
    }

    # Preserve lightweight conversational and support routes outside the
    # marketplace tool pipeline.
    guarded_intent = _classify(user_message, state)

    if guarded_intent in {
        CONVERSATIONAL_GREETING,
        CONVERSATIONAL_GRATITUDE,
        CONVERSATIONAL_IDENTITY,
        CONVERSATIONAL_GOODBYE,
    }:
        reply = conversational_reply(guarded_intent)
        source.update(
            {
                "intent": guarded_intent,
                "confidence": 1.0,
                "source_type": "deterministic_conversation",
            }
        )
        source["structured_response"].update(
            {
                "answer": reply,
                "primary_intent": guarded_intent,
                "confidence": 1.0,
            }
        )
        return reply, source


    if guarded_intent == SUPPORT_INTENT:
        return None

    facts, slot_updates, state_debug = _apply_shopping_session_update(
        state,
        user_message,
    )
    requirements = _merge_requirements(state, user_message)
    if _active_service_flow(state):
        previous_service_requirements = {
            **dict(((context.get("state") or {}).get("requirements")) or {}),
            **dict(((context.get("smart_shopping") or {}).get("requirements")) or {}),
        }
        requirements = {
            **{
                key: value
                for key, value in previous_service_requirements.items()
                if value not in (None, "")
            },
            **{
                key: value
                for key, value in (requirements or {}).items()
                if value not in (None, "")
            },
        }
        state["requirements"] = requirements
    deterministic_requirements = dict(requirements or {})

    if guarded_intent == "property_inquiry":
        state["entity_type"] = "property"
        state["intent_family"] = "marketplace"
        state["category"] = state.get("category") or "property"
        state["product_type"] = state.get("product_type") or "property"

        message_text = user_message.lower()
        if any(term in message_text for term in ("rent", "rental", "lease", "yearly", "short let")):
            state["transaction_type"] = "rent"
        elif any(term in message_text for term in ("buy", "purchase", "sale", "for sale")):
            state["transaction_type"] = "buy"

    elif guarded_intent == "car_inquiry":
        state["entity_type"] = "vehicle"
        state["intent_family"] = "marketplace"
        state["category"] = state.get("category") or "vehicle"
        state["product_type"] = state.get("product_type") or "vehicle"

        message_text = user_message.lower()
        if any(term in message_text for term in ("rent", "rental", "hire")):
            state["transaction_type"] = "rent"
        elif any(term in message_text for term in ("buy", "purchase", "for sale")):
            state["transaction_type"] = "buy"

    elif guarded_intent == "software_inquiry":
        state["entity_type"] = "software"
        state["intent_family"] = "marketplace"
        state["category"] = state.get("category") or "software"
        state["product_type"] = state.get("product_type") or "software"

    elif guarded_intent == TOOL_SERVICES_MATCH_PROVIDERS:
        state["entity_type"] = "service_provider"
        state["intent_family"] = "service"

        if not state.get("transaction_type"):
            state["transaction_type"] = "find_provider"

        state["catalog_category_id"] = None
        state["category"] = ""
        state["product_type"] = ""
        state["shopping_category_locked"] = False
        state["locked_category"] = ""
        state["active_subject"] = (
            (state.get("requirements") or {}).get("service_type")
            or state.get("active_subject")
            or facts.get("subject")
            or "service provider"
        )

    context["state"] = state
    conversation.context = context

    message_lower = user_message.lower()
    vehicle_markers = (
        " car ",
        " vehicle ",
        " suv ",
        " sedan ",
        " truck ",
        " pickup ",
        " van ",
        " bus ",
        "toyota",
        "honda",
        "lexus",
        "mercedes",
        "bmw",
        "nissan",
        "hyundai",
        "kia",
        "camry",
        "corolla",
    )
    padded_message = f" {message_lower} "
    if any(marker in padded_message for marker in vehicle_markers):
        state["entity_type"] = "vehicle"
        state["intent_family"] = "marketplace"
        state["shopping_category_locked"] = False
        state["catalog_category_id"] = None
        state["category"] = ""
        state["product_type"] = ""
        state["locked_category"] = ""
        state["active_subject"] = (
            facts.get("subject")
            or state.get("active_subject")
            or user_message
        )
        if any(term in message_lower for term in ("rent", "hire", "lease")):
            state["transaction_type"] = "rent"
        else:
            state["transaction_type"] = state.get("transaction_type") or "buy"
        state["_clear_legacy_requirements"] = True

    _attach_compatibility_metadata(source, state_debug=state_debug)
    source["state_debug"] = state_debug
    source["facts"] = facts
    source["slot_updates"] = slot_updates

    model_config = _active_smart_shopping_model()
    prompt = None

    if model_config is None or not external_provider_enabled():
        source["ai_pipeline"]["fallback_used"] = True
        source["fallback_reason"] = "active_external_model_missing"

        intent = normalize_primary_intent(
            _classify(user_message, state)
        )

        source.update(
            {
                "intent": intent,
                "confidence": 0.72,
                "state_debug": state_debug,
                "facts": facts,
                "slot_updates": slot_updates,
            }
        )
    else:
        try:
            prompt = active_prompt(PROMPT_KEY, role=role)
            source["prompt"] = {
                "key": prompt.key,
                "version": prompt.version,
                "feature": prompt.feature,
            }

            interpretation = _run_interpretation_model(
                model_config=model_config,
                prompt=prompt,
                user_message=user_message,
                state=state,
                role=role,
                request_id=request_id,
            )

            source["ai_pipeline"]["interpretation"] = True
            source["interpretation"] = interpretation

            intent = _safe_ai_intent(
                interpretation.get("primary_intent")
            )
            requirements = _merge_ai_requirements(
                state,
                interpretation,
                user_message,
            )
            if deterministic_requirements:
                requirements = {
                    **deterministic_requirements,
                    **{
                        key: value
                        for key, value in (requirements or {}).items()
                        if value not in (None, "")
                    },
                }
                state["requirements"] = requirements

            source.update(
                {
                    "intent": intent,
                    "confidence": float(
                        interpretation.get("confidence") or 0
                    ),
                }
            )
            source["structured_response"].update(
                interpretation
            )

        except Exception as exc:
            logger.exception(
                "Smart Shopping interpretation failed: %s",
                exc,
            )

            source["ai_pipeline"]["fallback_used"] = True
            source["fallback_reason"] = (
                f"interpretation_failed_{exc.__class__.__name__}"
            )

            intent = normalize_primary_intent(
                _classify(user_message, state)
            )

            source.update(
                {
                    "intent": intent,
                    "confidence": 0.65,
                    "state_debug": state_debug,
                    "facts": facts,
                    "slot_updates": slot_updates,
                }
            )

    # Domain and context-aware deterministic routes take precedence over an
    # external-model interpretation. This prevents specialist marketplace
    # requests from being rewritten as generic catalogue searches.
    if guarded_intent in {
        REQUIREMENTS_INTENT,
        TOOL_SERVICES_MATCH_PROVIDERS,
        "property_inquiry",
        "car_inquiry",
        "software_inquiry",
    }:
        intent = guarded_intent
        source["intent"] = intent

    # -------------------------------------------------------------------------
    # VIDEO-CONFERENCING QUALIFICATION
    # -------------------------------------------------------------------------
    message_text = str(user_message or "").strip().lower()

    conferencing_markers = (
        "video conferencing",
        "video conference",
        "conferencing device",
        "conferencing system",
        "conference room system",
    )

    conferencing_detail_markers = (
        "boardroom",
        "meeting room",
        "conference room",
        "classroom",
        "church",
        "participants",
        "participant",
        "people",
        "person",
        "seater",
        "seaters",
        "users",
        "attendees",
    )

    message_mentions_conferencing = any(
        marker in message_text
        for marker in conferencing_markers
    )
    supplied_conferencing_details = any(
        marker in message_text
        for marker in conferencing_detail_markers
    )
    supplied_numeric_requirement = any(
        character.isdigit()
        for character in message_text
    )

    existing_locked_category = str(
        state.get("current_category_locked")
        or context.get("current_category_locked")
        or state.get("locked_category")
        or ""
    ).strip().lower()

    existing_subject = str(
        shopping_category_label(state)
        or state.get("active_subject")
        or ""
    ).strip().lower()

    active_conferencing_subject = (
        existing_locked_category == "video_conferencing"
        or any(
            marker in existing_subject
            for marker in conferencing_markers
        )
        or message_mentions_conferencing
    )

    broad_initial_conferencing_request = (
        message_mentions_conferencing
        and not supplied_conferencing_details
        and not supplied_numeric_requirement
    )

    if broad_initial_conferencing_request:
        state["shopping_category_locked"] = True
        state["current_category_locked"] = "video_conferencing"
        state["locked_category"] = "video_conferencing"
        state["category"] = "video_conferencing"
        state["product_type"] = "video_conferencing"
        state["active_subject"] = "video conferencing"
        state["last_search_query"] = "video conferencing"
        state["flow"] = "shopping_requirements"
        state["intent"] = CLARIFICATION_INTENT

        answer = (
            "Is this for a small meeting room, boardroom, classroom, church "
            "or another space? Also tell me the number of participants and "
            "your budget so I can recommend the right conferencing system."
        )

        source["source_type"] = "clarification"
        source["intent"] = CLARIFICATION_INTENT
        source["conversation_intent"] = "product_recommendation"
        source["marketplace_category"] = "video_conferencing"
        source["catalog_category_id"] = state.get("catalog_category_id")
        source["category_route_source"] = "video_conferencing_qualifier"
        source["confidence"] = max(
            float(source.get("confidence") or 0),
            0.95,
        )

        _attach_compatibility_metadata(
            source,
            state_debug=state_debug,
            tool_name="none",
        )

        source["structured_response"].update(
            {
                "answer": answer,
                "primary_intent": CLARIFICATION_INTENT,
                "structured_requirements": requirements,
                "clarifying_question": answer,
                "missing_information": [
                    "Room or use case",
                    "Number of participants",
                    "Budget",
                ],
                "confidence": 0.95,
            }
        )

        _persist_smart_shopping_state(
            conversation,
            context,
            state,
            public_intent="product_recommendation",
        )

        return answer, source

    if (
        active_conferencing_subject
        and (
            supplied_conferencing_details
            or supplied_numeric_requirement
        )
        and not message_mentions_conferencing
    ):
        state["shopping_category_locked"] = True
        state["current_category_locked"] = "video_conferencing"
        state["locked_category"] = "video_conferencing"
        state["category"] = "video_conferencing"
        state["product_type"] = "video_conferencing"
        state["active_subject"] = "video conferencing"
        state["last_search_query"] = "video conferencing"
        state["flow"] = "catalog_search"
        state["intent"] = TOOL_CATALOG_SEARCH_PRODUCTS

        intent = TOOL_CATALOG_SEARCH_PRODUCTS
        source["intent"] = intent
        source["conversation_intent"] = "product_recommendation"

    active_marketplace_subject = str(
        shopping_category_label(state)
        or state.get("active_subject")
        or ""
    ).strip().lower()
    active_requirements = dict(state.get("requirements") or {})
    under_specified_projector_use_case = (
        intent == TOOL_CATALOG_SEARCH_PRODUCTS
        and "projector" in active_marketplace_subject
        and not active_requirements.get("budget_max")
        and not active_requirements.get("brightness_requirement")
        and not active_requirements.get("resolution")
        and re.search(
            r"\b(?:church|hall|classroom|boardroom|meeting room|conference room)\b",
            message_text,
        )
    )
    if under_specified_projector_use_case:
        answer = _shopping_followup_reply(state)
        source["source_type"] = "clarification"
        source["intent"] = CLARIFICATION_INTENT
        source["conversation_intent"] = "product_recommendation"
        source["marketplace_category"] = (
            state.get("category")
            or state.get("product_type")
            or shopping_category_label(state)
            or state.get("active_subject")
            or ""
        )
        source["catalog_category_id"] = state.get("catalog_category_id")
        source["category_route_source"] = "projector_use_case_qualifier"
        source["confidence"] = max(float(source.get("confidence") or 0), 0.86)

        _attach_compatibility_metadata(
            source,
            state_debug=state_debug,
            tool_name="none",
        )

        source["structured_response"].update(
            {
                "answer": answer,
                "primary_intent": CLARIFICATION_INTENT,
                "structured_requirements": requirements,
                "clarifying_question": answer,
                "missing_information": list(state.get("missing_slots") or []),
            }
        )

        state["intent"] = CLARIFICATION_INTENT
        state["requirements"] = requirements
        _persist_smart_shopping_state(
            conversation,
            context,
            state,
            public_intent="product_recommendation",
        )

        return answer, source

    # Keep non-catalogue marketplace domains out of Product search.
    if (
        intent in {
            CLARIFICATION_INTENT,
            TOOL_CATALOG_SEARCH_PRODUCTS,
            "property_inquiry",
            "car_inquiry",
            "software_inquiry",
        }
        and not _catalog_search_allowed_for_state(state)
    ):
        answer = _domain_preserving_marketplace_reply(state, requirements)
        source["source_type"] = "clarification"

        # Preserve the specialist routing intent in message metadata and
        # AIIntentLog, while keeping the established public conversation intent.
        if guarded_intent == "car_inquiry":
            persisted_intent = "car_inquiry"
        elif guarded_intent == "property_inquiry":
            persisted_intent = "property_inquiry"
        elif guarded_intent == "software_inquiry":
            persisted_intent = "software_inquiry"
        else:
            persisted_intent = CLARIFICATION_INTENT

        public_intent = _legacy_current_intent(
            persisted_intent,
            state,
        )

        source["intent"] = persisted_intent
        source["conversation_intent"] = public_intent

        # The category-router log is created from response metadata. Specialist
        # early-return branches must therefore expose the canonical marketplace
        # category before returning.
        entity_type = str(state.get("entity_type") or "").strip().lower()
        if entity_type == "property":
            source["marketplace_category"] = "property"
        elif entity_type == "vehicle":
            source["marketplace_category"] = "vehicle"
        elif entity_type == "software":
            source["marketplace_category"] = "software"
        elif entity_type == "service_provider":
            source["marketplace_category"] = "service"
        else:
            source["marketplace_category"] = (
                state.get("category")
                or state.get("product_type")
                or shopping_category_label(state)
                or state.get("active_subject")
                or "general_marketplace"
            )

        source["catalog_category_id"] = state.get("catalog_category_id")
        source["category_route_source"] = "deterministic_domain_router"
        source["fallback_reason"] = "catalog_search_not_allowed_for_active_workflow"
        source["confidence"] = max(float(source.get("confidence") or 0), 0.8)
        _attach_compatibility_metadata(
            source,
            state_debug=state_debug,
            tool_name="none",
        )
        source["structured_response"].update(
            {
                "answer": answer,
                "primary_intent": persisted_intent,
                "structured_requirements": requirements,
                "clarifying_question": answer,
            }
        )
        state["intent"] = persisted_intent
        state["requirements"] = requirements
        _persist_smart_shopping_state(
            conversation,
            context,
            state,
            public_intent=public_intent,
        )
        return answer, source

    if guarded_intent == REQUIREMENTS_INTENT:
        # Requirement follow-ups continue searching when a shopping category
        # is already locked. Otherwise ask for the next missing detail.
        if has_locked_shopping_category(state):
            active_marketplace_subject = str(
                shopping_category_label(state)
                or state.get("active_subject")
                or ""
            ).strip().lower()
            active_requirements = dict(state.get("requirements") or {})
            needs_projector_clarification = (
                "projector" in active_marketplace_subject
                and not active_requirements.get("budget_max")
                and not active_requirements.get("brightness_requirement")
                and not active_requirements.get("resolution")
                and (
                    active_requirements.get("use_case")
                    or active_requirements.get("room_type")
                    or re.search(
                        r"\b(?:church|hall|classroom|boardroom|meeting room|conference room)\b",
                        str(user_message or "").lower(),
                    )
                )
            )

            if needs_projector_clarification:
                answer = _shopping_followup_reply(state)
                source["source_type"] = "clarification"
                source["intent"] = CLARIFICATION_INTENT
                source["conversation_intent"] = "product_recommendation"
                source["marketplace_category"] = (
                    state.get("category")
                    or state.get("product_type")
                    or shopping_category_label(state)
                    or state.get("active_subject")
                    or ""
                )
                source["catalog_category_id"] = state.get("catalog_category_id")
                source["category_route_source"] = "requirements_projector_qualifier"

                _attach_compatibility_metadata(
                    source,
                    state_debug=state_debug,
                    tool_name="none",
                )

                source["structured_response"].update(
                    {
                        "answer": answer,
                        "primary_intent": CLARIFICATION_INTENT,
                        "structured_requirements": requirements,
                        "clarifying_question": answer,
                        "missing_information": list(
                            state.get("missing_slots") or []
                        ),
                    }
                )

                state["intent"] = CLARIFICATION_INTENT
                state["requirements"] = requirements

                _persist_smart_shopping_state(
                    conversation,
                    context,
                    state,
                    public_intent="product_recommendation",
                )

                return answer, source
            else:
                intent = TOOL_CATALOG_SEARCH_PRODUCTS
                source["intent"] = intent
                source["conversation_intent"] = "product_recommendation"
        else:
            answer = _shopping_followup_reply(state)
            source["source_type"] = "clarification"
            source["intent"] = CLARIFICATION_INTENT
            source["conversation_intent"] = "product_recommendation"
            source["marketplace_category"] = (
                state.get("category")
                or state.get("product_type")
                or shopping_category_label(state)
                or state.get("active_subject")
                or "general_marketplace"
            )
            source["catalog_category_id"] = state.get(
                "catalog_category_id"
            )
            source["category_route_source"] = "requirements_qualifier"

            _attach_compatibility_metadata(
                source,
                state_debug=state_debug,
                tool_name="none",
            )

            source["structured_response"].update(
                {
                    "answer": answer,
                    "primary_intent": CLARIFICATION_INTENT,
                    "structured_requirements": requirements,
                    "clarifying_question": answer,
                    "missing_information": list(
                        state.get("missing_slots") or []
                    ),
                }
            )

            state["intent"] = CLARIFICATION_INTENT
            state["requirements"] = requirements

            _persist_smart_shopping_state(
                conversation,
                context,
                state,
                public_intent="product_recommendation",
            )

            return answer, source

    if intent == UNSUPPORTED_INTENT:
        response = unsupported_marketplace_response()
        answer = response["message"]

        source["structured_response"].update(
            {
                "answer": answer,
                "primary_intent": intent,
                "handoff_required": True,
                "warnings": [
                    "The requested marketplace action is not supported."
                ],
            }
        )

        state["intent"] = intent
        context["smart_shopping"] = state
        conversation.context = context
        conversation.current_intent = intent
        conversation.save(
            update_fields=[
                "context",
                "current_intent",
                "updated_at",
            ]
        )

        return answer, source

    tool_context = _tool_context(
        conversation,
        actor_user,
        role,
        request_id,
        application_source,
    )

    tool_payload = {}
    tool_result = {}
    result = None

    try:
        if intent == TOOL_CATALOG_GET_PRODUCT_FACTS:
            refs = _extract_product_refs(
                conversation,
                state,
                user_message,
            )

            if not refs:
                answer = (
                    "Which approved Arolana product would you like "
                    "me to check?"
                )
                source["structured_response"].update(
                    {
                        "answer": answer,
                        "clarifying_question": answer,
                        "missing_information": [
                            "The product to inspect."
                        ],
                    }
                )
                return answer, source

            tool_payload = {
                "product_ref": refs[0],
            }
            result = execute_ai_tool(
                TOOL_CATALOG_GET_PRODUCT_FACTS,
                tool_payload,
                context=tool_context,
            )
            tool_result = dict(result.payload or {})

            product = tool_result.get("product")
            if product and product.get("public_ref"):
                state["current_product_ref"] = product["public_ref"]

        elif intent == TOOL_CATALOG_COMPARE_PRODUCTS:
            refs = _extract_product_refs(
                conversation,
                state,
                user_message,
            )

            if len(refs) < 2:
                answer = (
                    "Which two approved Arolana products should "
                    "I compare?"
                )
                source["structured_response"].update(
                    {
                        "answer": answer,
                        "clarifying_question": answer,
                        "missing_information": [
                            "Two approved product references."
                        ],
                    }
                )
                return answer, source

            tool_payload = {
                "product_refs": refs[:4],
                "requirements": requirements,
            }
            result = execute_ai_tool(
                TOOL_CATALOG_COMPARE_PRODUCTS,
                tool_payload,
                context=tool_context,
            )
            tool_result = dict(result.payload or {})

        elif intent == TOOL_SERVICES_MATCH_PROVIDERS:
            provider_location = (
                requirements.get("service_location")
                or requirements.get("delivery_location")
                or requirements.get("location")
                or ""
            )
            provider_query = _provider_search_query(state, requirements, user_message)
            tool_payload = {
                "query": provider_query,
                "product_ref": (
                    state.get("current_product_ref")
                    or (
                        str(conversation.product_id)
                        if conversation.product_id
                        else ""
                    )
                ),
                "city": requirements.get("city") or provider_location,
                "state": requirements.get("state") or provider_location,
                "result_limit": 5,
            }
            tool_payload = {
                key: value
                for key, value in tool_payload.items()
                if value not in (None, "")
            }

            result = execute_ai_tool(
                TOOL_SERVICES_MATCH_PROVIDERS,
                tool_payload,
                context=tool_context,
            )
            tool_result = dict(result.payload or {})

        elif intent == TOOL_QUOTES_CREATE_QUOTE_REQUEST:
            ready, missing = quote_request_readiness(
                conversation,
                requirements,
                intent,
                actor_user=actor_user,
                state=state,
            )

            quantity_note = (
                f"I have preserved the requested quantity of {requirements.get('quantity')}. "
                if requirements.get("quantity")
                else "I still need the required quantity. "
            )
            answer = (
                quantity_note
                + (
                    "Your requirements are ready for review. "
                    "Confirm that you want me to submit the draft quotation request."
                    if ready
                    else (
                        "I can prepare the quotation request after these "
                        "remaining details are provided: "
                        + "; ".join(missing)
                    )
                )
            )

            source["structured_response"].update(
                {
                    "answer": answer,
                    "primary_intent": intent,
                    "structured_requirements": requirements,
                    "quote_request_ready": ready,
                    "handoff_required": True,
                    "missing_information": missing,
                    "next_actions": (
                        ["confirm_quote_request"]
                        if ready
                        else ["provide_missing_information"]
                    ),
                    "quote_request": {
                        "created": False,
                        "reference": None,
                        "status": "awaiting_confirmation",
                        "next_step": (
                            "Confirm quote request submission."
                            if ready
                            else "Provide missing information."
                        ),
                    },
                }
            )

            source["source_type"] = "quote_request"
            source["conversation_intent"] = "quotation_request"
            conversation.status = conversation.STATUS_ADMIN_REQUESTED
            conversation.save(update_fields=["status", "updated_at"])
            _attach_compatibility_metadata(
                source,
                state_debug=state_debug,
                tool_name="none",
            )
            state["intent"] = intent
            state["requirements"] = requirements
            _persist_smart_shopping_state(
                conversation,
                context,
                state,
                public_intent="quotation_request",
            )

            return answer, source

        else:
            intent = TOOL_CATALOG_SEARCH_PRODUCTS
            search_query = _ai_search_query(
                state,
                user_message,
            )
            tool_payload = _catalog_payload_for_state(
                state,
                search_query,
            )

            result = execute_ai_tool(
                TOOL_CATALOG_SEARCH_PRODUCTS,
                tool_payload,
                context=tool_context,
            )
            tool_result = dict(result.payload or {})

            products = tool_result.get("products") or []
            if products:
                first_ref = products[0].get("public_ref")
                if first_ref:
                    state["current_product_ref"] = first_ref

        source["ai_pipeline"]["tool_execution"] = True
        source["tool_calls"].append(intent)
        source["tool_arguments"] = tool_payload

    except Exception as exc:
        logger.exception(
            "Smart Shopping tool execution failed: %s",
            exc,
        )

        source["fallback_reason"] = (
            f"tool_failed_{exc.__class__.__name__}"
        )
        source["confidence"] = 0.2
        source["source_type"] = "ai_core_safe_fallback"

        return _public_error_reply(), source

    products = tool_result.get("products") or []
    product = tool_result.get("product")

    if product and not products:
        products = [product]

    deterministic_answer = _fallback_answer_for_tool(
        intent,
        tool_payload,
        tool_result,
        state,
    )
    if (
        intent == TOOL_CATALOG_SEARCH_PRODUCTS
        and not (tool_result.get("products") or [])
        and slot_updates
        and has_locked_shopping_category(state)
    ):
        deterministic_answer = _shopping_followup_reply(state)

    requirement_acknowledgement = _requirement_acknowledgement(requirements)
    if requirement_acknowledgement and intent == TOOL_CATALOG_SEARCH_PRODUCTS:
        deterministic_answer = requirement_acknowledgement + "\n" + deterministic_answer

    final_response = None

    if (
        model_config is not None
        and prompt is not None
        and external_provider_enabled()
    ):
        try:
            final_response = _run_grounded_answer_model(
                model_config=model_config,
                prompt=prompt,
                user_message=user_message,
                state=state,
                interpretation=source.get("interpretation") or {},
                selected_intent=intent,
                tool_payload=tool_payload,
                tool_result=tool_result,
                role=role,
                request_id=request_id,
            )
            source["ai_pipeline"]["grounded_answer"] = True

        except Exception as exc:
            logger.exception(
                "Smart Shopping grounded answer failed: %s",
                exc,
            )
            source["ai_pipeline"]["fallback_used"] = True
            source["fallback_reason"] = (
                f"grounded_answer_failed_{exc.__class__.__name__}"
            )

    if final_response:
        answer = (
            _text(final_response.get("answer"))
            or deterministic_answer
        )

        source["structured_response"].update(
            final_response
        )
    else:
        answer = deterministic_answer

    source["structured_response"].update(
        {
            "answer": answer,
            "primary_intent": intent,
            "structured_requirements": requirements,
            "products": products,
            "comparison_points": (
                tool_result.get("comparison_points") or []
            ),
            "provider_suggestions": (
                tool_result.get("providers") or []
            ),
            "source_references": (
                tool_result.get("source_references") or []
            ),
            "warnings": list(
                dict.fromkeys(
                    (
                        source["structured_response"].get("warnings")
                        or []
                    )
                    + (tool_result.get("warnings") or [])
                )
            ),
        }
    )

    source["tool_intent"] = intent
    source["intent"] = intent
    source["conversation_intent"] = _legacy_current_intent(intent, state)
    raw_search_query = (
        tool_payload.get("query", "")
        if isinstance(tool_payload, dict)
        else ""
    )
    source["search_query"] = (
        raw_search_query.title()
        if (
            isinstance(raw_search_query, str)
            and raw_search_query
            and raw_search_query == raw_search_query.lower()
            and not any(char.isdigit() for char in raw_search_query)
        )
        else raw_search_query
    )
    if intent == TOOL_SERVICES_MATCH_PROVIDERS:
        source["active_subject"] = state.get("active_subject") or source["search_query"]
    source["source_type"] = _legacy_source_type(intent, tool_result)
    if (
        intent == TOOL_CATALOG_SEARCH_PRODUCTS
        and not (tool_result.get("products") or [])
        and slot_updates
        and has_locked_shopping_category(state)
    ):
        source["source_type"] = "clarification"
        source["tool_name"] = "none"

    source["catalog_category_id"] = state.get("catalog_category_id")
    entity_type = str(state.get("entity_type") or "").strip().lower()
    if entity_type == "property":
        source["marketplace_category"] = "property"
    elif entity_type == "service_provider":
        source["marketplace_category"] = "service"
    elif entity_type in {"vehicle", "software"}:
        source["marketplace_category"] = entity_type
    else:
        source["marketplace_category"] = (
            state.get("category")
            or state.get("product_type")
            or shopping_category_label(state)
            or state.get("active_subject")
            or ""
        )
    source["category_route_source"] = (
        "active_category_database"
        if state.get("catalog_category_id")
        else source["source_type"]
    )
    _attach_compatibility_metadata(
        source,
        state_debug=state_debug,
        tool_name=intent,
    )
    source["confidence"] = float(
        source["structured_response"].get("confidence")
        or source.get("confidence")
        or 0
    )

    product_cards = _product_cards(products)
    source["product_cards"] = product_cards

    if product_cards:
        first_product_id = product_cards[0].get("id")

        if (
            isinstance(first_product_id, str)
            and first_product_id.strip().isdigit()
        ):
            first_product_id = int(first_product_id.strip())
            product_cards[0]["id"] = first_product_id

        if isinstance(first_product_id, int):
            conversation.product_id = first_product_id
            conversation.save(update_fields=["product"])

    state["intent"] = intent
    state["requirements"] = requirements
    state["last_tool"] = intent
    state["last_tool_arguments"] = tool_payload
    state["last_request_id"] = request_id

    _persist_smart_shopping_state(
        conversation,
        context,
        state,
        public_intent=_legacy_current_intent(intent, state),
    )
    if conversation.product_id:
        conversation.save(update_fields=["product", "updated_at"])

    return answer, source
