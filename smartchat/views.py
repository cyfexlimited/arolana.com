import json
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Q

from products.models import Product
from .models import SmartChatConversation, SmartChatMessage
from .services import openai_reply, should_handoff, make_conversation_title, create_system_message


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _customer_identity(request):
    if request.user.is_authenticated:
        return {
            "user": request.user,
            "customer_name": request.user.get_full_name() or request.user.username or "",
            "customer_email": request.user.email or "",
        }
    if not request.session.session_key:
        request.session.create()
    return {"user": None, "customer_name": "", "customer_email": ""}


def _message_payload(message):
    display_name = "Arolana AI"
    if message.sender_type == SmartChatMessage.SENDER_USER:
        display_name = "Customer"
    elif message.sender_type == SmartChatMessage.SENDER_ADMIN:
        display_name = message.user.get_full_name() or message.user.username if message.user else "Arolana Admin"
    elif message.sender_type == SmartChatMessage.SENDER_SYSTEM:
        display_name = "System"

    return {
        "id": message.id,
        "sender_type": message.sender_type,
        "sender_name": display_name,
        "message": message.message,
        "created_at": message.created_at.isoformat(),
    }


def _get_or_create_conversation(request, data, product=None):
    identity = _customer_identity(request)
    conversation_id = data.get("conversation_id")

    conversation = None
    if conversation_id:
        lookup = Q(id=conversation_id)
        if request.user.is_authenticated:
            lookup &= Q(user=request.user) | Q(session_key=request.session.session_key or "")
        else:
            lookup &= Q(session_key=request.session.session_key or "")
        conversation = SmartChatConversation.objects.filter(lookup).first()

    if conversation:
        return conversation

    conversation = SmartChatConversation.objects.create(
        user=identity["user"],
        session_key=request.session.session_key or "",
        product=product,
        title=make_conversation_title(product, data.get("message", "")),
        customer_name=identity["customer_name"],
        customer_email=identity["customer_email"],
        page_url=data.get("page_url", "")[:500],
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:1200],
        selected_variants=data.get("selected_variants") or {},
    )
    create_system_message(conversation, "Smart chat started.")
    return conversation


@require_POST
def api_message(request):
    data = _json_body(request)
    message = str(data.get("message", "")).strip()
    if not message:
        return JsonResponse({"success": False, "error": "Message is required."}, status=400)

    product = None
    product_id = data.get("product_id")
    if product_id:
        product = Product.objects.filter(id=product_id).select_related("category", "brand", "vendor").first()

    conversation = _get_or_create_conversation(request, data, product=product)
    selected_variants = data.get("selected_variants") or {}
    conversation.selected_variants = selected_variants
    conversation.save(update_fields=["selected_variants", "updated_at"])

    user_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_USER,
        user=request.user if request.user.is_authenticated else None,
        message=message,
        metadata={
            "selected_variants": selected_variants,
            "sku": data.get("sku", ""),
            "product_name": data.get("product_name", ""),
        },
    )

    handoff = should_handoff(message)
    if handoff:
        conversation.mark_admin_requested()
        create_system_message(conversation, "Customer requested admin support. Waiting for admin takeover.")
        reply = "I have alerted an Arolana admin. A real person can continue from this chat shortly."
        ai_message = SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_AI,
            message=reply,
            metadata={"handoff": True},
        )
        return JsonResponse({
            "success": True,
            "conversation_id": conversation.id,
            "status": conversation.status,
            "handoff_requested": True,
            "admin_inbox_url": reverse("smartchat:admin_inbox"),
            "reply": reply,
            "messages": [_message_payload(user_message), _message_payload(ai_message)],
        })

    if conversation.status in [SmartChatConversation.STATUS_ADMIN_REQUESTED, SmartChatConversation.STATUS_ADMIN_ACTIVE]:
        reply = "Your message has been added to the admin support chat. Please wait for an Arolana admin to reply."
        system_msg = SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_SYSTEM,
            message=reply,
        )
        return JsonResponse({
            "success": True,
            "conversation_id": conversation.id,
            "status": conversation.status,
            "handoff_requested": conversation.status == SmartChatConversation.STATUS_ADMIN_REQUESTED,
            "reply": reply,
            "messages": [_message_payload(user_message), _message_payload(system_msg)],
        })

    reply = openai_reply(conversation, message, product=conversation.product or product, selected_variants=selected_variants)
    ai_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_AI,
        message=reply,
        metadata={"model_mode": "openai_or_fallback"},
    )

    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "status": conversation.status,
        "handoff_requested": False,
        "reply": reply,
        "messages": [_message_payload(user_message), _message_payload(ai_message)],
    })


@require_POST
def api_request_admin(request):
    data = _json_body(request)
    conversation = _get_or_create_conversation(request, data)
    conversation.mark_admin_requested()
    message = str(data.get("message", "Customer requested admin support.")).strip()
    create_system_message(conversation, message)
    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "status": conversation.status,
        "reply": "Admin support has been requested. Please keep this chat open.",
        "admin_inbox_url": reverse("smartchat:admin_inbox"),
    })


@require_GET
def api_poll(request):
    conversation_id = request.GET.get("conversation_id")
    after_id = int(request.GET.get("after_id") or 0)
    if not conversation_id:
        return JsonResponse({"success": False, "error": "conversation_id is required."}, status=400)

    if request.user.is_authenticated:
        lookup = Q(id=conversation_id) & (Q(user=request.user) | Q(session_key=request.session.session_key or ""))
    else:
        lookup = Q(id=conversation_id, session_key=request.session.session_key or "")

    conversation = SmartChatConversation.objects.filter(lookup).first()
    if not conversation:
        return JsonResponse({"success": False, "error": "Conversation not found."}, status=404)

    messages = conversation.messages.filter(id__gt=after_id, is_private_note=False).order_by("id")
    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "status": conversation.status,
        "assigned_admin": conversation.assigned_admin.get_full_name() or conversation.assigned_admin.username if conversation.assigned_admin else "",
        "messages": [_message_payload(m) for m in messages],
    })


@staff_member_required
def admin_inbox(request):
    status = request.GET.get("status", "open")
    conversations = SmartChatConversation.objects.select_related("user", "product", "assigned_admin")
    if status == "open":
        conversations = conversations.exclude(status=SmartChatConversation.STATUS_CLOSED)
    elif status:
        conversations = conversations.filter(status=status)
    conversations = conversations.order_by("-last_message_at")[:100]
    return render(request, "smartchat/admin_inbox.html", {"conversations": conversations, "status": status})


@staff_member_required
def admin_conversation(request, conversation_id):
    conversation = get_object_or_404(
        SmartChatConversation.objects.select_related("user", "product", "assigned_admin"),
        id=conversation_id,
    )
    if not conversation.assigned_admin:
        conversation.assign_admin(request.user)
        create_system_message(conversation, f"{request.user.get_full_name() or request.user.username} joined the chat.")
    messages = conversation.messages.select_related("user").order_by("created_at")
    return render(request, "smartchat/admin_conversation.html", {"conversation": conversation, "messages": messages})


@staff_member_required
@require_POST
def admin_reply(request, conversation_id):
    conversation = get_object_or_404(SmartChatConversation, id=conversation_id)
    message = request.POST.get("message", "").strip()
    private_note = request.POST.get("private_note") == "on"
    if message:
        if not conversation.assigned_admin:
            conversation.assign_admin(request.user)
        elif conversation.status != SmartChatConversation.STATUS_ADMIN_ACTIVE:
            conversation.status = SmartChatConversation.STATUS_ADMIN_ACTIVE
            conversation.save(update_fields=["status", "updated_at"])

        SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_ADMIN,
            user=request.user,
            message=message,
            is_private_note=private_note,
        )
    return redirect("smartchat:admin_conversation", conversation_id=conversation.id)


@staff_member_required
@require_POST
def admin_close(request, conversation_id):
    conversation = get_object_or_404(SmartChatConversation, id=conversation_id)
    conversation.status = SmartChatConversation.STATUS_CLOSED
    conversation.save(update_fields=["status", "updated_at"])
    create_system_message(conversation, "Conversation closed by admin.")
    return redirect("smartchat:admin_inbox")

@staff_member_required
@require_GET
def admin_poll(request, conversation_id):
    conversation = get_object_or_404(SmartChatConversation, id=conversation_id)

    after_id = int(request.GET.get("after_id") or 0)

    messages = (
        conversation.messages
        .filter(id__gt=after_id, is_private_note=False)
        .select_related("user")
        .order_by("id")
    )

    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "status": conversation.status,
        "messages": [_message_payload(message) for message in messages],
    })