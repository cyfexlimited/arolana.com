import logging
import uuid

from django.conf import settings

from ai_core.feature_flags import external_provider_enabled, smart_shopping_enabled
from ai_core.intent import (
    UNSUPPORTED_INTENT,
    normalize_primary_intent,
    unsupported_marketplace_response,
)
from ai_core.permissions import role_for_user
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
    state = dict(context.get("smart_shopping") or {})
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


def _apply_shopping_session_update(state, message):
    before = _state_debug_snapshot(state)
    facts = extract_facts(message)
    slot_updates = slot_updates_from_facts(facts)
    previous_category = shopping_category_label(state)
    new_category = facts.get("category") or facts.get("product_type") or facts.get("subject") or ""
    reason = _category_change_reason(message, state, facts)
    reset_flow = reason == "flow_reset"

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
    missing = _missing_shopping_slots(state)
    if missing:
        return f"Got it. I’ll keep looking for {subject}. What is your {missing[0]}?"
    return f"Got it. I’ll use those details to find matching {subject} options on Arolana."


def _empty_result_reply(state, products, query=""):
    subject = (
        shopping_category_label(state)
        if state.get("catalog_category_id")
        else (query or state.get("active_subject") or "your request")
    )
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
    requirements = dict(state.get("requirements") or {})
    text = message.lower()
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


def _classify(message, state):
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
    text = message.lower()
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

    lines = ["Matching approved Arolana products:"]
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


def _providers_reply(providers):
    if not providers:
        return "I could not find an approved eligible service provider for that request yet. I can help you contact Arolana support."
    lines = ["Approved service providers that may match:"]
    for provider in providers[:5]:
        lines.append(
            f"• {provider.get('business_name')} — {provider.get('location') or 'location not listed'}; rating {provider.get('average_rating')}"
        )
    lines.append("I’m not promising schedule, availability or price until a provider confirms.")
    return "\n".join(lines)


def _comparison_reply(points):
    if not points:
        return "I could not compare those products because approved product references were not available."
    lines = ["Here is a grounded comparison from public product facts:"]
    for point in points[:10]:
        value = point.get("confirmed_value") or "Unavailable"
        lines.append(f"• {point.get('label')} — {point.get('product')}: {value}")
    lines.append("I won’t choose an overall winner unless your requirements make that clear.")
    return "\n".join(lines)


def smart_shopping_reply(conversation, user_message, *, actor_user=None, application_source="smartchat"):
    if not smart_shopping_enabled():
        return None

    ensure_default_tool_definitions()
    context, state = _conversation_state(conversation)
    context_state = dict((context.get("state") or {}))
    state = {**normalized_state(conversation), **context_state, **state}
    if context_state.get("requirements") or state.get("requirements"):
        state["requirements"] = {
            **(context_state.get("requirements") or {}),
            **(state.get("requirements") or {}),
        }
    previous_subject = state.get("active_subject") or (context.get("state") or {}).get("active_subject", "")
    request_id = str(uuid.uuid4())
    role = role_for_user(actor_user)
    facts, slot_updates, session_debug = _apply_shopping_session_update(state, user_message)
    category_change_reason = session_debug["reason_for_change"]
    has_shopping_session = has_locked_shopping_category(state)
    classified_intent = normalize_primary_intent(_classify(user_message, state))
    if (
        slot_updates
        and has_shopping_session
        and classified_intent in {CLARIFICATION_INTENT, REQUIREMENTS_INTENT, TOOL_CATALOG_SEARCH_PRODUCTS}
    ):
        intent = TOOL_CATALOG_SEARCH_PRODUCTS
    else:
        intent = classified_intent
    search_query = clean_product_search_query(user_message)
    topic_changed = False
    if intent == TOOL_CATALOG_SEARCH_PRODUCTS:
        previous_query = state.get("last_search_query", "")
        context_requirements = context_state.get("requirements") or {}
        has_previous_requirements = any(
            value not in (None, "") for value in {
                **(state.get("requirements") or {}),
                **context_requirements,
            }.values()
        )
        topic_changed = bool(
            category_change_reason in {"explicit_category_change", "flow_reset"}
            or (
                not has_shopping_session
                and (
                    (previous_query and previous_query.lower() != search_query.lower())
                    or has_previous_requirements
                )
            )
        )
        if not has_locked_shopping_category(state):
            state["active_subject"] = search_query
            state["last_search_query"] = search_query
        elif category_change_reason == "explicit_category_change" and not state.get("category"):
            state["active_subject"] = search_query
            state["locked_category"] = search_query
            state["search_query"] = search_query
            state["last_search_query"] = search_query
        state["flow"] = "catalog_search"
        if topic_changed:
            state["requirements"] = {}
        requirements = dict(state.get("requirements") or {})
    elif intent == REQUIREMENTS_INTENT:
        state["flow"] = "shopping_requirements"
        requirements = _merge_requirements(state, user_message)
        state["active_subject"] = requirements.get("summary", "")[:160]
    elif intent == TOOL_QUOTES_CREATE_QUOTE_REQUEST:
        state["flow"] = "quote_request"
        requirements = _merge_requirements(state, user_message)
    else:
        requirements = dict(state.get("requirements") or {})
    source = {
        "source_type": "ai_core_smart_shopping",
        "source_label": "Smart Shopping V1",
        "intent": intent,
        "confidence": 0.84,
        "request_id": request_id,
        "resolved_intent": intent,
        "selected_route": intent,
        "previous_subject": previous_subject,
        "active_subject": state.get("active_subject", ""),
        "topic_changed": topic_changed,
        "shopping_session": session_debug,
        "marketplace_session": {
            "intent_family": state.get("intent_family", ""),
            "transaction_type": state.get("transaction_type", ""),
            "entity_type": state.get("entity_type", ""),
            "active_subject": state.get("active_subject", ""),
            "active_category": state.get("active_category", ""),
            "active_subcategory": state.get("active_subcategory", ""),
            "active_service": state.get("active_service", ""),
            "search_query": state.get("search_query", ""),
            "requirements": requirements,
            "constraints": state.get("constraints", {}),
            "preferences": state.get("preferences", {}),
            "location": state.get("location", {}),
            "budget": state.get("budget", {}),
            "conversation_stage": state.get("conversation_stage", ""),
            "missing_slots": state.get("missing_slots", []),
            "completed_slots": state.get("completed_slots", []),
            "explicit_subject_change": state.get("explicit_subject_change", False),
            "last_user_message_type": state.get("last_user_message_type", ""),
            "source_confidence": state.get("source_confidence", {}),
        },
        "tool_calls": [],
        "structured_response": {
            "answer": "",
            "primary_intent": intent,
            "structured_requirements": requirements,
            "clarifying_question": "",
            "products": [],
            "comparison_points": [],
            "missing_information": [],
            "assumptions": [],
            "warnings": [],
            "provider_suggestions": [],
            "next_actions": [],
            "source_references": [],
            "confidence": 0.84,
            "handoff_required": False,
            "quote_request_ready": False,
            "quote_request": {},
        },
    }

    if intent in {
        CONVERSATIONAL_GREETING,
        CONVERSATIONAL_GRATITUDE,
        CONVERSATIONAL_IDENTITY,
        CONVERSATIONAL_GOODBYE,
    }:
        reply = conversational_reply(intent)
        source.update({
            "source_type": "deterministic_conversation",
            "source_label": "Arolana conversation",
            "confidence": 1.0,
            "route": intent,
        })
        source["structured_response"].update({"answer": reply, "confidence": 1.0})
        context["smart_shopping"] = state
        conversation.context = context
        conversation.current_intent = intent
        conversation.save(update_fields=["context", "current_intent", "updated_at"])
        return reply, source

    if intent == REQUIREMENTS_INTENT:
        source.update({
            "source_type": "clarification",
            "source_label": "Shopping requirements",
            "confidence": 0.86,
            "route": REQUIREMENTS_INTENT,
        })
        source["structured_response"].update({
            "answer": REQUIREMENTS_REPLY,
            "clarifying_question": REQUIREMENTS_REPLY,
            "next_actions": ["provide_missing_information"],
        })
        context["smart_shopping"] = state
        conversation.context = context
        conversation.current_intent = REQUIREMENTS_INTENT
        conversation.save(update_fields=["context", "current_intent", "updated_at"])
        return REQUIREMENTS_REPLY, source

    if intent == CLARIFICATION_INTENT:
        source.update({
            "source_type": "clarification",
            "source_label": "Arolana clarification",
            "confidence": 0.72,
            "route": CLARIFICATION_INTENT,
        })
        source["structured_response"].update({
            "answer": CLARIFICATION_REPLY,
            "clarifying_question": CLARIFICATION_REPLY,
            "next_actions": ["provide_missing_information"],
        })
        context["smart_shopping"] = state
        conversation.context = context
        conversation.current_intent = CLARIFICATION_INTENT
        conversation.save(update_fields=["context", "current_intent", "updated_at"])
        return CLARIFICATION_REPLY, source

    if intent in {ORDER_INTENT, SUPPORT_INTENT}:
        return None

    try:
        prompt = active_prompt(PROMPT_KEY, role=role)
        source["prompt"] = {
            "key": prompt.key,
            "version": prompt.version,
            "feature": prompt.feature,
        }
    except Exception as exc:
        source["fallback_reason"] = (
            f"active_prompt_error_{exc.__class__.__name__}"
        )
        logger.info("Smart Shopping prompt unavailable: %s", exc.__class__.__name__)

    if intent == UNSUPPORTED_INTENT:
        response = unsupported_marketplace_response()
        source["structured_response"].update({
            "answer": response["message"],
            "handoff_required": True,
            "warnings": ["Unsupported Smart Shopping V1 marketplace category."],
        })
        context["smart_shopping"] = state
        conversation.context = context
        conversation.current_intent = intent
        conversation.save(update_fields=["context", "current_intent", "updated_at"])
        return response["message"], source

    tool_context = _tool_context(conversation, actor_user, role, request_id, application_source)
    try:
        if intent == TOOL_CATALOG_GET_PRODUCT_FACTS:
            refs = _extract_product_refs(conversation, state, user_message)
            result = execute_ai_tool(TOOL_CATALOG_GET_PRODUCT_FACTS, {"product_ref": refs[0]}, context=tool_context)
            product = result.payload["product"]
            answer = _products_reply([product])
            state["current_product_ref"] = product["public_ref"]
            source["structured_response"].update({"answer": answer, "products": [product], "source_references": product["source_references"]})
        elif intent == TOOL_CATALOG_COMPARE_PRODUCTS:
            refs = _extract_product_refs(conversation, state, user_message)
            if len(refs) < 2:
                source["structured_response"]["clarifying_question"] = "Which two approved products should I compare?"
                answer = source["structured_response"]["clarifying_question"]
            else:
                result = execute_ai_tool(TOOL_CATALOG_COMPARE_PRODUCTS, {"product_refs": refs[:4], "requirements": requirements}, context=tool_context)
                answer = _comparison_reply(result.payload["comparison_points"])
                source["structured_response"].update(result.payload)
        elif intent == TOOL_SERVICES_MATCH_PROVIDERS:
            payload = {
                "query": user_message,
                "category": state.get("active_subject") or state.get("category") or "",
                "product_ref": (state.get("current_product_ref") or (str(conversation.product_id) if conversation.product_id else "")),
                "city": requirements.get("city", "") or requirements.get("service_location", "") or requirements.get("delivery_location", ""),
                "state": requirements.get("state", ""),
                "result_limit": 5,
            }
            result = execute_ai_tool(TOOL_SERVICES_MATCH_PROVIDERS, payload, context=tool_context)
            answer = _providers_reply(result.payload["providers"])
            source["structured_response"].update({"answer": answer, "provider_suggestions": result.payload["providers"], "source_references": result.payload["source_references"], "warnings": result.payload["warnings"]})
        elif intent == TOOL_QUOTES_CREATE_QUOTE_REQUEST:
            ready, missing = quote_request_readiness(
                conversation, requirements, intent, actor_user=actor_user, state=state,
            )
            answer = (
                "Your requirements are ready for review. Confirm if you want me to submit a draft quotation request."
                if ready else
                "I can prepare a draft quotation request after the missing details are provided."
            )
            source["structured_response"].update({
                "answer": answer,
                "quote_request_ready": ready,
                "missing_information": missing,
                "next_actions": ["confirm_quote_request"] if ready else ["provide_missing_information"],
            })
        else:
            payload = (
                _catalog_payload_for_state(state, search_query)
                if has_locked_shopping_category(state)
                else {"query": search_query, "result_limit": 5}
            )
            result = execute_ai_tool(TOOL_CATALOG_SEARCH_PRODUCTS, payload, context=tool_context)
            products = result.payload["products"]
            if products and has_locked_shopping_category(state):
                answer = _products_reply(products, shopping_category_label(state))
            elif has_locked_shopping_category(state):
                answer = _empty_result_reply(state, products, payload.get("query", search_query))
            else:
                answer = _products_reply(products, search_query)
            if products:
                state["current_product_ref"] = products[0]["public_ref"]
                state["current_product_name"] = products[0].get("name", "")
                source["product_cards"] = [
                    {
                        "id": item["public_ref"],
                        "name": item["name"],
                        "slug": item["slug"],
                        "price": item["displayed_price"],
                        "url": item["public_url"],
                    }
                    for item in products
                ]
            result_count = len(products)
            source.update({
                "result_count": result_count,
                "search_query": payload.get("query", search_query),
                "tool_name": TOOL_CATALOG_SEARCH_PRODUCTS,
            })
            if not products and not (has_locked_shopping_category(state) and slot_updates):
                source.update({
                    "source_type": "catalog_empty_result",
                    "source_label": "Arolana catalog",
                    "confidence": 1.0,
                })
            source["structured_response"].update({
                "answer": answer,
                "products": products,
                "source_references": result.payload["source_references"],
                "warnings": result.payload["warnings"],
                "missing_information": _missing_shopping_slots(state) if has_locked_shopping_category(state) else [],
                "structured_requirements": requirements,
            })
        if intent != TOOL_QUOTES_CREATE_QUOTE_REQUEST:
            source["tool_calls"].append(intent if intent in {
                TOOL_CATALOG_GET_PRODUCT_FACTS, TOOL_CATALOG_COMPARE_PRODUCTS, TOOL_SERVICES_MATCH_PROVIDERS
            } else TOOL_CATALOG_SEARCH_PRODUCTS)
        source["structured_response"]["answer"] = source["structured_response"].get("answer") or answer
    except Exception as exc:
        source["fallback_reason"] = f"tool_failed_{exc.__class__.__name__}"
        logger.info("Smart Shopping tool failed safely: %s", exc.__class__.__name__)
        return _public_error_reply(), {**source, "confidence": 0.2, "source_type": "ai_core_safe_fallback"}

    context["smart_shopping"] = state
    context["state"] = {**(context.get("state") or {}), **state}
    conversation.context = context
    conversation.current_intent = intent
    conversation.save(update_fields=["context", "current_intent", "updated_at"])
    return source["structured_response"]["answer"], source
