import json
from decimal import Decimal

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from products.models import Product

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
