import re
from copy import deepcopy

from django.urls import reverse

from products.models import Category

from .context_state import normalized_state, persist_state


CONTINUE = "continue"
REFINE = "refine"
FOLLOW_UP = "follow_up"
SWITCH_TOPIC = "switch_topic"
RETURN_TO_PREVIOUS_TOPIC = "return_to_previous_topic"
TRANSACTIONAL_OVERRIDE = "transactional_override"
SUPPORT_OVERRIDE = "support_override"
UNCLEAR = "unclear"

MAX_TOPIC_STACK = 5

EXPLICIT_INTENTS = (
    (
        "vendor_registration",
        SWITCH_TOPIC,
        (
            r"\bhow (?:do|can) i sell (?:on|with) arolana\b",
            r"\b(?:become|register as|sign up as) (?:a )?(?:seller|vendor|manufacturer)\b",
            r"\bopen (?:a |my )?(?:shop|store) on arolana\b",
        ),
    ),
    (
        "vendor_subscription_overview",
        SWITCH_TOPIC,
        (
            r"\bvendor (?:plan|plans|package|packages|subscription|subscriptions)\b",
            r"\bwhich (?:seller|vendor) plan\b",
            r"\bhow much (?:is|are) (?:the )?(?:seller|vendor) plan",
        ),
    ),
    (
        "platform_information",
        SWITCH_TOPIC,
        (
            r"\bwhat is arolana\b",
            r"\bwhat(?:'s| is) arolana all about\b",
            r"\btell me about arolana\b",
            r"\bhow does arolana work\b",
        ),
    ),
    (
        "marketplace_catalog_overview",
        SWITCH_TOPIC,
        (
            r"\bwhat (?:do you|does arolana) sell\b",
            r"\bwhat can i (?:buy|find) on arolana\b",
            r"\bwhat categories (?:do you have|are available)\b",
        ),
    ),
    (
        "order_tracking",
        TRANSACTIONAL_OVERRIDE,
        (r"\btrack (?:my |an? )?order\b", r"\bwhere is my order\b"),
    ),
    (
        "human_handover",
        SUPPORT_OVERRIDE,
        (
            r"\b(?:talk|speak|connect) (?:me )?(?:to|with) (?:a )?(?:human|agent|admin|support)\b",
            r"\byou (?:are|re) not helping\b",
        ),
    ),
    (
        "service_provider_search",
        SWITCH_TOPIC,
        (
            r"\bfind (?:an? )?(?:installer|engineer|service provider)\b",
            r"\bi need (?:an? )?(?:installer|engineer|technician)\b",
        ),
    ),
)

RETURN_PATTERNS = (
    r"\b(?:go|switch) back to (?:the )?(?:projector|product|item)\b",
    r"\bcontinue (?:with|talking about) (?:the )?(?:projector|product|item)\b",
    r"\bwhat about (?:that|the previous) (?:projector|product|item)\b",
)


def _text(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _matches(text, patterns):
    return any(re.search(pattern, text) for pattern in patterns)


def resolve_topic(conversation, message):
    text = _text(message)
    for intent, relation, patterns in EXPLICIT_INTENTS:
        if _matches(text, patterns):
            return {
                "relation": relation,
                "intent": intent,
                "topic": intent,
                "confidence": 0.99,
                "reason": "explicit_intent",
            }
    state = normalized_state(conversation)
    if (
        (
            state.get("last_topic") in {"vendor_registration", "vendor_subscription_overview"}
            or conversation.current_intent in {
                "vendor_registration", "vendor_subscription_overview",
            }
            or (conversation.context or {}).get("last_topic_resolution", {}).get("intent")
            in {"vendor_registration", "vendor_subscription_overview"}
        )
        and re.search(r"\b(?:which|what|choose|compare|best).*(?:plan|package)\b", text)
    ):
        return {
            "relation": REFINE,
            "intent": "vendor_subscription_overview",
            "topic": "vendor_subscription_overview",
            "confidence": 0.96,
            "reason": "vendor_plan_follow_up",
        }
    if _matches(text, RETURN_PATTERNS):
        return {
            "relation": RETURN_TO_PREVIOUS_TOPIC,
            "intent": "product_follow_up",
            "topic": "previous_product",
            "confidence": 0.96,
            "reason": "explicit_topic_return",
        }
    return {
        "relation": FOLLOW_UP if conversation.product_id else UNCLEAR,
        "intent": "",
        "topic": "",
        "confidence": 0.45,
        "reason": "defer_to_marketplace_router",
    }


def _snapshot(state):
    return {
        "intent": state.get("intent", ""),
        "last_topic": state.get("last_topic", ""),
        "active_subject": state.get("active_subject", ""),
        "brand": state.get("brand", ""),
        "category": state.get("category", ""),
        "subcategory": state.get("subcategory", ""),
        "product_type": state.get("product_type", ""),
        "current_product_id": state.get("current_product_id"),
        "current_product_name": state.get("current_product_name", ""),
        "current_vendor_id": state.get("current_vendor_id"),
        "recommendation": deepcopy(state.get("recommendation") or {}),
    }


def _clear_product_context(conversation, state):
    for key in (
        "brand", "category", "subcategory", "product_type", "active_subject",
        "current_product_name",
    ):
        state[key] = ""
    for key in ("current_product_id", "current_vendor_id"):
        state[key] = None
    state["recommendation"] = {
        "candidate_product_ids": [],
        "current_recommendation_id": None,
        "previous_recommendation_ids": [],
    }
    context = dict(conversation.context or {})
    for key in (
        "current_product_id", "current_product_name", "current_brand",
        "current_category", "current_category_locked", "locked_category_label",
        "locked_catalog_category_id", "locked_catalog_category_name",
    ):
        context.pop(key, None)
    conversation.context = context
    conversation.product = None


def apply_topic_resolution(conversation, resolution):
    state = normalized_state(conversation)
    relation = resolution["relation"]
    stack = list(state.get("topic_stack") or [])

    if relation in {SWITCH_TOPIC, TRANSACTIONAL_OVERRIDE, SUPPORT_OVERRIDE}:
        if state.get("current_product_id") or state.get("active_subject"):
            stack.append(_snapshot(state))
            stack = stack[-MAX_TOPIC_STACK:]
        _clear_product_context(conversation, state)
        state["topic_stack"] = stack
        state["previous_intent"] = state.get("intent", "")
        state["intent"] = resolution["intent"]
        state["last_topic"] = resolution["topic"]
        conversation.save(update_fields=["context", "product", "updated_at"])
        persist_state(conversation, state)
    elif relation == REFINE and resolution.get("intent"):
        state["previous_intent"] = state.get("intent", "")
        state["intent"] = resolution["intent"]
        state["last_topic"] = resolution["topic"]
        persist_state(conversation, state)
    elif relation == RETURN_TO_PREVIOUS_TOPIC and stack:
        previous = stack.pop()
        for key, value in previous.items():
            state[key] = value
        state["topic_stack"] = stack
        product_id = state.get("current_product_id")
        if product_id:
            from products.models import Product

            conversation.product = Product.objects.filter(
                pk=product_id,
                is_active=True,
                approval_status="approved",
            ).first()
        persist_state(conversation, state)
        conversation.save(update_fields=["product", "updated_at"])

    context = dict(conversation.context or {})
    context["last_topic_resolution"] = resolution
    conversation.context = context
    conversation.save(update_fields=["context", "updated_at"])
    return state


def explicit_route_reply(resolution, conversation=None):
    intent = resolution.get("intent")
    actions = []
    if resolution.get("relation") == RETURN_TO_PREVIOUS_TOPIC and getattr(
        conversation, "product_id", None,
    ):
        return (
            f"We’re back to {conversation.product.name}. I can explain its details, price, "
            "delivery, compatibility, or help you compare it."
        ), {
            "source_type": "conversation_context",
            "source_label": "Restored product topic",
            "confidence": 0.96,
            "intent": "product_follow_up",
            "route": "product_follow_up",
            "topic_relation": RETURN_TO_PREVIOUS_TOPIC,
            "cards": [],
            "actions": [],
            "marketplace_category": getattr(conversation.product.category, "name", ""),
        }
    if intent == "platform_information":
        categories = list(
            Category.objects.filter(parent__isnull=True, is_active=True)
            .order_by("order", "name")
            .values_list("name", flat=True)[:8]
        )
        catalog = ", ".join(categories)
        reply = (
            "Arolana is a multi-category marketplace where customers can shop from vendors, "
            "compare listings, request quotes, arrange delivery, and find verified installers "
            "and service providers."
        )
        if catalog:
            reply += f" Current departments include {catalog}."
        actions = [
            {"label": "Shop products", "url": reverse("products:list")},
            {"label": "Find installers", "url": reverse("installers:directory")},
        ]
    elif intent == "marketplace_catalog_overview":
        categories = list(
            Category.objects.filter(parent__isnull=True, is_active=True)
            .order_by("order", "name")
            .values_list("name", flat=True)
        )
        reply = (
            f"You can shop across {', '.join(categories[:12])}."
            if categories
            else "Arolana supports products, properties, vehicles, services, and more."
        )
        actions = [{"label": "Browse products", "url": reverse("products:list")}]
    elif intent == "vendor_registration":
        reply = (
            "To sell on Arolana, sign in with your existing Arolana account, open the vendor "
            "registration, complete your business profile and KYC, then choose the plan that "
            "fits your catalogue. Your vendor profile stays linked to the same account."
        )
        actions = [
            {"label": "Become a vendor", "url": "/vendors/register/"},
            {"label": "View vendor plans", "url": reverse("subscriptions:plans")},
        ]
    elif intent == "vendor_subscription_overview":
        reply = (
            "Arolana vendor plans control catalogue capacity and premium selling tools. "
            "You can compare the current plans, product limits, visibility benefits, and "
            "included features before choosing one."
        )
        actions = [{"label": "Compare vendor plans", "url": reverse("subscriptions:plans")}]
    elif intent == "order_tracking":
        reply = (
            "Send your order number or tracking code. If you are signed in, I can help check "
            "your own order without exposing another customer’s information."
        )
    elif intent == "service_provider_search":
        reply = (
            "Arolana can help you find verified installers, engineers, and service providers. "
            "Tell me the service and location, or browse the approved providers."
        )
        actions = [{"label": "Find installers", "url": reverse("installers:directory")}]
    elif intent == "human_handover":
        reply = "I’ll connect you with Arolana support and keep this conversation context for the team."
    else:
        return None
    return reply, {
        "source_type": "platform_database",
        "source_label": intent.replace("_", " ").title(),
        "confidence": resolution.get("confidence", 0.95),
        "intent": intent,
        "route": intent,
        "topic_relation": resolution.get("relation"),
        "cards": [],
        "actions": actions,
        "marketplace_category": "general_marketplace",
    }
