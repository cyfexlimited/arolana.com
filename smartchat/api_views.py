import json
from datetime import timedelta
from decimal import Decimal
import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from products.models import Product
from currency.models import Currency
from currency.utils.exchange_rates import CurrencyConverter

from ai_core.feature_flags import smart_shopping_enabled
from ai_core.permissions import ROLE_CUSTOMER, ROLE_GUEST, role_for_user
from ai_core.schema_validation import SchemaValidationError, validate_source_references
from ai_core.tool_contracts import TOOL_QUOTES_CREATE_QUOTE_REQUEST
from ai_core.tools import AIToolValidationError, execute_ai_tool
from installers.models import ServiceCategory, ServiceProviderProfile

from .ai_manager import (
    create_managed_ai_message,
    normalize_question,
    request_human_takeover,
)
from .models import (
    AIFeedback,
    AILearnedKnowledge,
    AIUnansweredQuestion,
    HumanTakeoverRequest,
    SmartChatConversation,
    SmartChatMessage,
)
from .conversation_lifecycle import reopen_closed_conversation
from .views import (
    _message_payload,
    _mobile_customer_from_payload,
    _notify_staff_new_conversation,
    _notify_staff_customer_message,
)


def _payload(request):
    if request.method == "GET":
        return request.GET
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        return {}


def _identity(request, data):
    if request.user.is_authenticated:
        return {
            "user": request.user,
            "mobile_customer": None,
            "device_id": "",
        }

    from mobile_customers.token_auth import extract_bearer_token

    phone = str(
        data.get("phone_number")
        or data.get("phone")
        or ""
    ).strip()

    raw_token = (
        extract_bearer_token(request)
        or str(
            data.get("api_token")
            or data.get("apiToken")
            or ""
        ).strip()
    )

    if phone and raw_token:
        customer = _mobile_customer_from_payload(
            data,
            request=request,
        )

        return {
            "user": customer.user,
            "mobile_customer": customer,
            "device_id": str(data.get("device_id") or "").strip()[:160],
        }

    if not request.session.session_key:
        request.session.create()

    return {
        "user": None,
        "mobile_customer": None,
        "device_id": str(data.get("device_id") or "").strip()[:160],
        "session_key": request.session.session_key,
    }

def _owned_conversations(identity):
    queryset = SmartChatConversation.objects.all()
    if identity.get("user"):
        return queryset.filter(user=identity["user"])
    device_id = identity.get("device_id")
    if device_id:
        return queryset.filter(user__isnull=True, device_id=device_id)
    return queryset.filter(
        user__isnull=True,
        device_id="",
        session_key=identity.get("session_key", ""),
    )


def _owned_conversation(identity, conversation_id):
    return _owned_conversations(identity).filter(pk=conversation_id).first()


def _conversation_payload(conversation, include_messages=True):
    payload = {
        "id": conversation.id,
        "conversation_id": conversation.id,
        "title": conversation.title,
        "status": conversation.status,
        "channel": conversation.channel,
        "human_requested": conversation.status in {
            SmartChatConversation.STATUS_ADMIN_REQUESTED,
            SmartChatConversation.STATUS_ADMIN_ACTIVE,
        },
        "assigned_admin": (
            conversation.assigned_admin.get_full_name()
            or conversation.assigned_admin.username
            if conversation.assigned_admin else ""
        ),
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
        "last_message_at": conversation.last_message_at.isoformat(),
        "current_intent": conversation.current_intent,
        "context": {"state": (conversation.context or {}).get("state", {})},
    }
    if include_messages:
        payload["messages"] = [
            _message_payload(message)
            for message in conversation.messages.filter(is_private_note=False).order_by("id")
        ]
    return payload


def _error(message, status=400):
    return JsonResponse({"success": False, "message": str(message)}, status=status)


def _quote_error(code, message, *, status=400, retry=False, handoff=False):
    return JsonResponse({
        "success": False,
        "error": {"code": code, "message": message, "retry": retry, "offer_handoff": handoff},
        "message": message,
    }, status=status)


def _quote_currency(requirements, budget):
    """Preserve customer money and add optional, non-authoritative provenance."""
    amount = budget.get("amount") if isinstance(budget, dict) else requirements.get("amount")
    code = str((budget.get("currency") if isinstance(budget, dict) else requirements.get("currency")) or "").upper()
    if amount in (None, "") and not code:
        return
    try:
        amount = Decimal(str(amount))
        if amount < 0:
            raise ValueError
    except (TypeError, ValueError, ArithmeticError):
        raise AIToolValidationError("Budget amount must be a non-negative number.")
    requirements["amount"] = amount
    requirements["currency"] = code
    base_code = str(getattr(settings, "AROLANA_BASE_CURRENCY", "NGN")).upper()
    source = Currency.objects.filter(code=code, is_active=True).first()
    base = Currency.objects.filter(code=base_code, is_active=True).first()
    if not source or not base or source.exchange_rate <= 0 or base.exchange_rate <= 0:
        requirements.update({
            "base_amount": None, "base_currency": base_code, "conversion_rate": None,
            "exchange_rate_timestamp": None,
            "conversion_warning": "Currency conversion is unavailable; the supplied amount requires human review.",
        })
        return
    max_age = int(getattr(settings, "CURRENCY_EXCHANGE_RATE_MAX_AGE_SECONDS", 604800))
    timestamp = min(source.updated_at, base.updated_at)
    if max_age > 0 and timestamp < timezone.now() - timedelta(seconds=max_age):
        requirements.update({
            "base_amount": None, "base_currency": base_code, "conversion_rate": None,
            "exchange_rate_timestamp": timestamp.isoformat(),
            "conversion_warning": "The available exchange rate is stale; the supplied amount requires human review.",
        })
        return
    converted = Decimal(str(CurrencyConverter.convert(amount, source, base)))
    requirements.update({
        "base_amount": converted, "base_currency": base.code,
        "conversion_rate": base.exchange_rate / source.exchange_rate,
        "exchange_rate_timestamp": timestamp.isoformat(), "conversion_warning": "",
    })


@csrf_exempt
@require_POST
def quote_request(request):
    """Submit a confirmed, ownership-checked draft via the canonical AI tool."""
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError
    except (TypeError, ValueError, UnicodeDecodeError):
        return _quote_error("malformed_request", "The quotation request is malformed.")

    if not smart_shopping_enabled():
        return _quote_error(
            "smart_shopping_disabled", "Quotation submission is temporarily unavailable.",
            status=503, retry=True, handoff=True,
        )
    conversation_id = data.get("conversation_id")
    request_id = str(data.get("request_id") or "").strip()
    idempotency_key = str(data.get("idempotency_key") or "").strip()
    if not conversation_id:
        return _quote_error("conversation_id_required", "Conversation reference is required.")
    if not request_id:
        return _quote_error("request_id_required", "Request reference is required.")
    if not idempotency_key:
        return _quote_error("idempotency_key_required", "Idempotency key is required.")
    if data.get("consent") is not True:
        return _quote_error("consent_required", "Please confirm before submitting the quotation request.")

    from mobile_customers.token_auth import extract_bearer_token
    bearer = extract_bearer_token(request)
    try:
        identity = _identity(request, data)
    except PermissionError:
        return _quote_error("authentication_failed", "Login expired or invalid.", status=403, retry=True)
    if bearer and not identity.get("mobile_customer") and not request.user.is_authenticated:
        return _quote_error("authentication_failed", "Login expired or invalid.", status=403, retry=True)
    conversation = _owned_conversation(identity, conversation_id)
    if not conversation:
        return _quote_error("conversation_not_found", "Conversation not found.", status=404)

    if not identity.get("user"):
        supplied_device = str(data.get("device_id") or "").strip()
        current_session = str(identity.get("session_key") or "")
        if conversation.device_id:
            guest_matches = bool(
                supplied_device and supplied_device == conversation.device_id
                and current_session and current_session == conversation.session_key
            )
        else:
            guest_matches = bool(current_session and current_session == conversation.session_key)
        if not guest_matches:
            return _quote_error("conversation_not_found", "Conversation not found.", status=404)

    role = role_for_user(identity.get("user"), mobile_customer=identity.get("mobile_customer"))
    if role not in {ROLE_CUSTOMER, ROLE_GUEST}:
        return _quote_error("role_not_allowed", "This account cannot submit customer quotation requests.", status=403)

    raw_requirements = data.get("requirements")
    if not isinstance(raw_requirements, dict):
        return _quote_error("requirements_invalid", "Structured requirements are required.")
    allowed = {
        "summary", "assumptions", "missing_information", "phone", "state", "city", "location",
        "address", "service_needed", "contact_preference", "urgency", "currency", "amount",
    }
    requirements = {key: value for key, value in raw_requirements.items() if key in allowed}
    if data.get("assumptions") is not None:
        value = data["assumptions"]
        requirements["assumptions"] = "; ".join(map(str, value)) if isinstance(value, list) else str(value)
    if data.get("missing_information") is not None:
        value = data["missing_information"]
        requirements["missing_information"] = "; ".join(map(str, value)) if isinstance(value, list) else str(value)
    location = data.get("location")
    if isinstance(location, dict):
        for key in ("state", "city", "address"):
            if location.get(key):
                requirements[key] = location[key]
        requirements["location"] = location.get("label") or location.get("city") or location.get("state") or ""
    elif location:
        requirements["location"] = str(location)

    contact = data.get("customer_contact") or data.get("guest_contact") or {}
    if not isinstance(contact, dict):
        return _quote_error("contact_invalid", "Customer contact details are malformed.")
    phone = str(
        contact.get("phone") or requirements.get("phone") or conversation.customer_phone
        or getattr(identity.get("mobile_customer"), "phone_number", "")
        or getattr(identity.get("user"), "phone_number", "") or ""
    ).strip()
    if not re.fullmatch(r"\+?[0-9][0-9\s().-]{6,24}", phone):
        return _quote_error("contact_invalid", "A valid contact phone number is required.")
    requirements["phone"] = phone
    guest_contact = {
        "name": str(contact.get("name") or conversation.customer_display or "Arolana customer")[:150],
        "phone": phone[:30],
        "whatsapp": str(contact.get("whatsapp") or "")[:30],
        "email": str(contact.get("email") or conversation.customer_email or "")[:254],
    }
    if guest_contact["email"]:
        try:
            validate_email(guest_contact["email"])
        except ValidationError:
            return _quote_error("contact_invalid", "Customer contact details are invalid.")

    product_refs = data.get("product_refs") or data.get("selected_product_references") or []
    service_refs = data.get("service_refs") or data.get("requested_service_references") or []
    if not isinstance(product_refs, list) or not isinstance(service_refs, list):
        return _quote_error("public_reference_invalid", "Public references are malformed.")
    if any(not isinstance(ref, str) or not ref.strip() or ref.strip().isdigit() for ref in product_refs):
        return _quote_error("public_reference_invalid", "A selected product reference is invalid.")
    product_refs = [ref.strip() for ref in product_refs]
    if Product.objects.filter(slug__in=product_refs, is_active=True, approval_status="approved").count() != len(set(product_refs)):
        return _quote_error("public_reference_invalid", "A selected product is unavailable.")
    if any(not isinstance(ref, str) or not ref.strip() or ref.strip().isdigit() for ref in service_refs):
        return _quote_error("public_reference_invalid", "A service reference is invalid.")
    service_refs = [ref.strip() for ref in service_refs]
    if ServiceCategory.objects.filter(slug__in=service_refs, is_active=True).count() != len(set(service_refs)):
        return _quote_error("public_reference_invalid", "A requested service is unavailable.")
    if not product_refs and not service_refs and not str(requirements.get("service_needed") or "").strip():
        return _quote_error(
            "requirements_invalid",
            "Select a product, service category or technical solution before submitting.",
        )

    source_references = data.get("source_references") or []
    try:
        validate_source_references({"source_references": source_references}, path="request")
        _quote_currency(requirements, data.get("budget") or {})
    except (SchemaValidationError, AIToolValidationError):
        return _quote_error("request_validation_failed", "Quotation details failed public validation.")

    payload = {
        "customer_consent": True,
        "approved_guest_contact": role == ROLE_GUEST,
        "requirements": requirements,
        "conversation_id": str(conversation.pk),
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "product_refs": product_refs,
        "service_refs": service_refs,
        "source_references": source_references,
        "guest_contact": guest_contact,
    }
    try:
        result = execute_ai_tool(
            TOOL_QUOTES_CREATE_QUOTE_REQUEST,
            payload,
            context={
                "user": identity.get("user"), "role": role,
                "request_id": request_id, "conversation_id": conversation.pk,
                "tool_call_id": str(uuid.uuid4()),
                "application_source": "customer_mobile" if identity.get("mobile_customer") or conversation.channel == "mobile" else "customer_web",
                "session_key": conversation.session_key,
            },
        )
    except (PermissionError, LookupError):
        return _quote_error(
            "tool_unavailable", "Quotation submission is temporarily unavailable.",
            status=503, retry=True, handoff=True,
        )
    except AIToolValidationError:
        return _quote_error("request_validation_failed", "Quotation details failed validation.")
    except Exception:
        return _quote_error(
            "submission_failed", "The quotation request could not be submitted safely.",
            status=500, retry=True, handoff=True,
        )

    public_quote = result.payload["quote_request"]
    context = dict(conversation.context or {})
    state = dict(context.get("smart_shopping") or {})
    state.update({"quote_request_submitted": True, "quote_request_public_ref": public_quote["public_ref"]})
    context["smart_shopping"] = state
    conversation.context = context
    conversation.save(update_fields=["context", "updated_at"])
    if result.created and not data.get("provider_ref"):
        _notify_staff_new_conversation(
            conversation, "Draft quotation request submitted",
            f"{conversation.customer_display} submitted a draft quotation request for human review.",
            metadata={"event": "smart_shopping_quote_request", "public_reference": public_quote["public_ref"]},
        )
    return JsonResponse({
        "success": True,
        "quote_request": {
            "created": result.created,
            "reference": public_quote["public_ref"],
            "status": public_quote["status"],
            "next_step": "Arolana or an approved provider will review the request.",
        },
        "quote_request_ready": False,
        "handoff_required": False,
        "message": "Your quotation request has been submitted for review." if result.created else "Your quotation request was already submitted for review.",
    })


@csrf_exempt
@require_POST
def start(request):
    data = _payload(request)
    try:
        identity = _identity(request, data)
    except PermissionError as exc:
        return _error(exc, 403)
    conversation_id = data.get("conversation_id")
    conversation = None
    if conversation_id:
        conversation = _owned_conversation(identity, conversation_id)
        if not conversation:
            return _error("Conversation not found.", 404)
    if not conversation:
        mobile_customer = identity.get("mobile_customer")
        product = Product.objects.filter(
            pk=data.get("product_id"),
            is_active=True,
            approval_status="approved",
        ).first() if data.get("product_id") else None
        conversation = SmartChatConversation.objects.create(
            user=identity.get("user"),
            session_key=identity.get("session_key", ""),
            device_id=identity.get("device_id", ""),
            channel="mobile" if mobile_customer else "web",
            audience=(
                SmartChatConversation.AUDIENCE_CUSTOMER
                if identity.get("user") else SmartChatConversation.AUDIENCE_GUEST
            ),
            customer_name=str(
                data.get("full_name")
                or getattr(mobile_customer, "full_name", "")
                or ""
            )[:200],
            customer_email=str(
                data.get("email") or getattr(mobile_customer, "email", "") or ""
            )[:254],
            customer_phone=str(
                data.get("phone_number")
                or getattr(mobile_customer, "phone_number", "")
                or ""
            )[:40],
            title=str(data.get("title") or "Arolana Smart Chat")[:220],
            page_url=str(data.get("page_url") or "")[:700],
            product=product,
            context={
                "preferred_language": str(data.get("preferred_language") or "en")[:20],
            },
            selected_variants={
                "mobile_customer_id": mobile_customer.id,
            } if mobile_customer else {},
        )
    response = _conversation_payload(conversation)
    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "conversation": response,
        "messages": response["messages"],
    })


@csrf_exempt
@require_GET
def conversations(request):
    try:
        identity = _identity(request, _payload(request))
    except PermissionError as exc:
        return _error(exc, 403)
    items = _owned_conversations(identity).select_related("assigned_admin")[:100]
    return JsonResponse({
        "success": True,
        "conversations": [_conversation_payload(item, include_messages=False) for item in items],
    })


@csrf_exempt
@require_GET
def conversation_detail(request, conversation_id):
    try:
        identity = _identity(request, _payload(request))
    except PermissionError as exc:
        return _error(exc, 403)
    conversation = _owned_conversation(identity, conversation_id)
    if not conversation:
        return _error("Conversation not found.", 404)
    conversation.messages.filter(
        sender_type__in=[SmartChatMessage.SENDER_ADMIN, SmartChatMessage.SENDER_AI],
        is_private_note=False,
    ).update(is_read_by_customer=True)
    payload = _conversation_payload(conversation)
    return JsonResponse({"success": True, "conversation": payload, "messages": payload["messages"]})


@csrf_exempt
@require_POST
def message(request):
    data = _payload(request)
    try:
        identity = _identity(request, data)
    except PermissionError as exc:
        return _error(exc, 403)
    text = str(data.get("message") or data.get("text") or "").strip()
    if not text:
        return _error("Message is required.")
    with transaction.atomic():
        conversation = _owned_conversations(identity).select_for_update().filter(
            pk=data.get("conversation_id"),
        ).first()
        if not conversation:
            return _error("Conversation not found.", 404)
        reopened = reopen_closed_conversation(conversation)
        if data.get("product_id"):
            product = Product.objects.filter(
                pk=data["product_id"],
                is_active=True,
                approval_status="approved",
            ).first()
            if product and product.pk != conversation.product_id:
                conversation.product = product
                conversation.save(update_fields=["product", "updated_at"])
        user_message = SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_USER,
            user=identity.get("user"),
            message=text,
            is_read_by_admin=False,
            metadata={"source": conversation.channel, "device_id": identity.get("device_id", "")},
        )
        messages = [user_message]
        if conversation.status in {
            SmartChatConversation.STATUS_ADMIN_REQUESTED,
            SmartChatConversation.STATUS_ADMIN_ACTIVE,
        }:
            _notify_staff_customer_message(conversation, user_message)
        else:
            messages.append(create_managed_ai_message(conversation, user_message, identity.get("user")))
    conversation.refresh_from_db()
    conversation_payload = _conversation_payload(conversation)
    latest_reply = _message_payload(messages[-1])
    metadata = latest_reply.get("metadata") or {}
    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "status": conversation.status,
        "conversation": conversation_payload,
        "messages": conversation_payload["messages"],
        "reply": latest_reply,
        "intent": metadata.get("intent") or conversation.current_intent,
        "topic": metadata.get("marketplace_category") or "",
        "route": metadata.get("route") or metadata.get("source_type") or "",
        "cards": metadata.get("product_cards") or metadata.get("cards") or [],
        "actions": metadata.get("actions") or [],
        "conversation_status": conversation.status,
        "reopened": reopened,
    })


@csrf_exempt
@require_POST
def feedback(request):
    data = _payload(request)
    try:
        identity = _identity(request, data)
    except PermissionError as exc:
        return _error(exc, 403)
    conversation = _owned_conversation(identity, data.get("conversation_id"))
    if not conversation:
        return _error("Conversation not found.", 404)
    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        return _error("Rating must be from 1 to 5.")
    if rating not in range(1, 6):
        return _error("Rating must be from 1 to 5.")
    target_message = conversation.messages.filter(pk=data.get("message_id")).first()
    item = AIFeedback.objects.create(
        conversation=conversation,
        message=target_message,
        user=identity.get("user"),
        session_key=identity.get("session_key", ""),
        device_id=identity.get("device_id", ""),
        rating=rating,
        helpful=data.get("helpful") if isinstance(data.get("helpful"), bool) else None,
        comment=str(data.get("comment") or "")[:2000],
    )
    if target_message and target_message.source_type == "learned_knowledge":
        learned = AILearnedKnowledge.objects.filter(
            pk=target_message.source_object_id,
        ).first()
        if learned:
            delta = 0.03 if rating >= 4 or item.helpful is True else -0.08
            learned.confidence = max(
                Decimal("0"),
                min(Decimal("1"), learned.confidence + Decimal(str(delta))),
            )
            learned.save(update_fields=["confidence", "updated_at"])
    if target_message and (rating <= 2 or item.helpful is False):
        question_message = conversation.messages.filter(
            sender_type=SmartChatMessage.SENDER_USER,
            id__lt=target_message.id,
        ).order_by("-id").first()
        if question_message:
            AIUnansweredQuestion.objects.get_or_create(
                conversation=conversation,
                message=question_message,
                normalized_question=normalize_question(question_message.message),
                is_resolved=False,
                defaults={
                    "question": question_message.message,
                    "detected_intent": conversation.current_intent,
                    "marketplace_category": (conversation.context or {}).get(
                        "marketplace_category", "",
                    ),
                    "confidence": target_message.confidence or 0,
                    "reason": "negative_customer_feedback",
                    "context_snapshot": conversation.context or {},
                },
            )
    return JsonResponse({"success": True, "feedback_id": item.id})


@csrf_exempt
@require_POST
def request_human(request):
    data = _payload(request)
    try:
        identity = _identity(request, data)
    except PermissionError as exc:
        return _error(exc, 403)
    conversation = _owned_conversation(identity, data.get("conversation_id"))
    if not conversation:
        return _error("Conversation not found.", 404)
    reason = str(data.get("reason") or data.get("message") or "Customer requested human support.").strip()
    takeover = request_human_takeover(conversation, identity.get("user"), reason)
    _notify_staff_new_conversation(
        conversation,
        "Human support requested",
        f"{conversation.customer_display}: {reason[:500]}",
        metadata={"event": "smartchat_human_takeover", "takeover_request_id": takeover.id},
    )
    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "request_id": takeover.id,
        "status": conversation.status,
        "message": "Let me connect you with Arolana support.",
    })


@csrf_exempt
@require_GET
def unread_count(request):
    try:
        identity = _identity(request, _payload(request))
    except PermissionError as exc:
        return _error(exc, 403)
    count = SmartChatMessage.objects.filter(
        conversation__in=_owned_conversations(identity),
        sender_type=SmartChatMessage.SENDER_ADMIN,
        is_private_note=False,
        is_read_by_customer=False,
    ).count()
    return JsonResponse({"success": True, "unread_count": count})


@csrf_exempt
@require_POST
def mark_read(request):
    data = _payload(request)
    try:
        identity = _identity(request, data)
    except PermissionError as exc:
        return _error(exc, 403)
    conversation = _owned_conversation(identity, data.get("conversation_id"))
    if not conversation:
        return _error("Conversation not found.", 404)
    updated = conversation.messages.filter(
        sender_type__in=[SmartChatMessage.SENDER_ADMIN, SmartChatMessage.SENDER_AI],
        is_private_note=False,
        is_read_by_customer=False,
    ).update(is_read_by_customer=True)
    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "marked_read": updated,
    })
