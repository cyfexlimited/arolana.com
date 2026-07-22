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


PROMPT_KEY = "smart_shopping_assistant"
PROMPT_FEATURE = FEATURE_SMART_SHOPPING


def _text(value):
    return str(value or "").strip()


def _conversation_state(conversation):
    context = dict(conversation.context or {})
    state = dict(context.get("smart_shopping") or {})
    return context, state


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
    text = message.lower()
    unsupported_terms = {"vehicle", "vehicles", "car", "cars", "property", "real estate", "rental", "rentals", "land"}
    if any(term in text for term in unsupported_terms):
        return UNSUPPORTED_INTENT
    if any(term in text for term in ("compare", "versus", " vs ")):
        return "catalog.compare_products"
    if any(term in text for term in ("quote", "quotation", "proposal", "professional estimate", "send request")):
        return "quotes.create_quote_request"
    if any(term in text for term in ("install", "installer", "installation", "service provider", "technician")):
        return "services.match_providers"
    if state.get("current_product_ref") and any(term in text for term in ("spec", "facts", "warranty", "manual", "video", "details")):
        return "catalog.get_product_facts"
    return "catalog.search_products"


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


def _products_reply(products):
    if not products:
        return "I could not find an active approved Arolana product matching that request yet."
    lines = ["Here are active approved Arolana products I found:"]
    for product in products[:5]:
        price = product.get("displayed_price") or ""
        stock = product.get("stock_status") or "stock status unavailable"
        lines.append(f"• {product.get('name')} — {price} ({stock})")
    lines.append("These are grounded in public catalog records; marketplace descriptions are treated as untrusted source content.")
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
    requirements = _merge_requirements(state, user_message)
    request_id = str(uuid.uuid4())
    role = role_for_user(actor_user)
    intent = normalize_primary_intent(_classify(user_message, state))
    source = {
        "source_type": "ai_core_smart_shopping",
        "source_label": "Smart Shopping V1",
        "intent": intent,
        "confidence": 0.84,
        "request_id": request_id,
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

    try:
        prompt = active_prompt(PROMPT_KEY, role=role)
        source["prompt"] = {"key": prompt.key, "version": prompt.version, "feature": prompt.feature}
    except Exception:
        source["fallback_reason"] = "active_prompt_missing"

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
                "product_ref": (state.get("current_product_ref") or (str(conversation.product_id) if conversation.product_id else "")),
                "city": requirements.get("city", ""),
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
            result = execute_ai_tool(TOOL_CATALOG_SEARCH_PRODUCTS, {"query": user_message, "result_limit": 5}, context=tool_context)
            products = result.payload["products"]
            answer = _products_reply(products)
            if products:
                state["current_product_ref"] = products[0]["public_ref"]
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
            source["structured_response"].update({"answer": answer, "products": products, "source_references": result.payload["source_references"], "warnings": result.payload["warnings"]})
        if intent != TOOL_QUOTES_CREATE_QUOTE_REQUEST:
            source["tool_calls"].append(intent if intent in {
                TOOL_CATALOG_GET_PRODUCT_FACTS, TOOL_CATALOG_COMPARE_PRODUCTS, TOOL_SERVICES_MATCH_PROVIDERS
            } else TOOL_CATALOG_SEARCH_PRODUCTS)
        source["structured_response"]["answer"] = source["structured_response"].get("answer") or answer
    except Exception as exc:
        if external_provider_enabled():
            source["fallback_reason"] = f"tool_failed_{exc.__class__.__name__}"
        return _public_error_reply(), {**source, "confidence": 0.2, "source_type": "ai_core_safe_fallback"}

    context["smart_shopping"] = state
    conversation.context = context
    conversation.current_intent = intent
    conversation.save(update_fields=["context", "current_intent", "updated_at"])
    return source["structured_response"]["answer"], source
