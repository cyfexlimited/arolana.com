import json
from django.contrib.auth import get_user_model
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.text import get_valid_filename
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Q
from django.core.cache import cache

from products.models import Product
from .models import SmartChatConversation, SmartChatMessage, SmartChatSupportTicket
from .services import ai_operations_reply, openai_reply, should_handoff, make_conversation_title, create_system_message, create_support_ticket

User = get_user_model()


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}



def _safe_int(value, default=0):
    """Safely convert query/body values to int.

    Prevents crashes when the browser sends values like:
    - NaN
    - undefined
    - null
    - empty string
    """
    try:
        if value in (None, "", "NaN", "nan", "undefined", "null"):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


SMARTCHAT_TYPING_TIMEOUT = 6


def _typing_key(conversation_id, actor):
    return f"smartchat:typing:{conversation_id}:{actor}"


def _set_typing(conversation_id, actor, is_typing=True):
    key = _typing_key(conversation_id, actor)
    if is_typing:
        cache.set(key, True, timeout=SMARTCHAT_TYPING_TIMEOUT)
    else:
        cache.delete(key)


def _typing_payload(conversation, actor):
    name = "Customer"
    if actor == "admin":
        name = (
            conversation.assigned_admin.get_full_name()
            or conversation.assigned_admin.username
            if conversation.assigned_admin else "Arolana Admin"
        )
    elif conversation.customer_display:
        name = conversation.customer_display

    return {
        "is_typing": bool(cache.get(_typing_key(conversation.id, actor))),
        "actor": actor,
        "name": name,
    }


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
    display_name = "Arolana Chat"
    if message.sender_type == SmartChatMessage.SENDER_USER:
        display_name = "Customer"
    elif message.sender_type == SmartChatMessage.SENDER_ADMIN:
        display_name = message.user.get_full_name() or message.user.username if message.user else "Arolana Admin"
    elif message.sender_type == SmartChatMessage.SENDER_SYSTEM:
        display_name = "System"

    image_url = ""
    image_name = ""
    if getattr(message, "image", None):
        try:
            image_url = message.image.url
            image_name = message.image.name.rsplit("/", 1)[-1]
        except Exception:
            image_url = ""
            image_name = ""

    return {
        "id": message.id,
        "sender_type": message.sender_type,
        "sender_name": display_name,
        "message": message.message,
        "image_url": image_url,
        "image_name": image_name,
        "has_image": bool(image_url),
        "created_at": message.created_at.isoformat(),
    }


def _get_customer_conversation(request, conversation_id):
    if not conversation_id:
        return None

    if request.user.is_authenticated:
        session_key = request.session.session_key or ""
        owner_lookup = Q(user=request.user)
        if session_key:
            owner_lookup |= Q(session_key=session_key)
        lookup = Q(id=conversation_id) & owner_lookup
    else:
        if not request.session.session_key:
            request.session.create()
        lookup = Q(id=conversation_id, session_key=request.session.session_key or "")

    return SmartChatConversation.objects.select_related("assigned_admin", "user").filter(lookup).first()


def _get_or_create_conversation(request, data, product=None):
    identity = _customer_identity(request)
    conversation_id = _safe_int(data.get("conversation_id"), default=0)

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


def _staff_notification_recipients(conversation):
    if conversation.assigned_admin_id and conversation.assigned_admin and conversation.assigned_admin.is_active:
        return [conversation.assigned_admin]

    return list(User.objects.filter(is_staff=True, is_active=True).only("id")[:25])


def _notify_staff_new_conversation(conversation, title, message, priority=3, metadata=None):
    try:
        from notifications.models import Notification

        link = reverse("smartchat:admin_conversation", args=[conversation.id])
        base_metadata = {
            "smartchat_conversation_id": conversation.id,
            "customer_name": conversation.customer_name,
            "customer_email": conversation.customer_email,
            "subject": conversation.title,
            "page_url": conversation.page_url,
        }
        if metadata:
            base_metadata.update(metadata)

        for staff_user in _staff_notification_recipients(conversation):
            Notification.send(
                user=staff_user,
                notification_type="message",
                title=title,
                message=message,
                link=link,
                metadata=base_metadata,
                priority=priority,
            )
    except Exception:
        # Smart chat must keep working even if the optional notification app is unavailable.
        return


def _notify_staff_customer_message(conversation, message):
    snippet = (message.message or "").strip()
    if getattr(message, "image", None):
        snippet = f"{snippet} [Image attachment]".strip()
    if len(snippet) > 240:
        snippet = f"{snippet[:237]}..."

    _notify_staff_new_conversation(
        conversation,
        "New Arolana Chat message",
        f"{conversation.customer_display} sent a Smart Chat message: {snippet}",
        priority=3,
        metadata={
            "smartchat_message_id": message.id,
            "event": "customer_message",
        },
    )


def _guest_thank_you_message(name):
    return (
        "Thank you for reaching out to Arolana support team. "
        "We will reach out to you. "
        "If you have any question, register on Arolana and chat with admin."
)


ALLOWED_SMARTCHAT_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
ALLOWED_SMARTCHAT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_SMARTCHAT_IMAGE_SIZE = 5 * 1024 * 1024


def _validate_chat_image(uploaded_file):
    if not uploaded_file:
        return "Please choose an image to upload."

    if uploaded_file.size > MAX_SMARTCHAT_IMAGE_SIZE:
        return "Please upload an image smaller than 5MB."

    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    filename = get_valid_filename(uploaded_file.name or "").lower()
    has_valid_extension = any(filename.endswith(ext) for ext in ALLOWED_SMARTCHAT_IMAGE_EXTENSIONS)

    if content_type not in ALLOWED_SMARTCHAT_IMAGE_TYPES or not has_valid_extension:
        return "Only JPG, PNG, WebP, or GIF images are allowed."

    return ""


GUEST_CONTACT_PROMPT = (
    "Please submit your first name, last name, email, and message first so an "
    "Arolana admin can help you properly."
)


@require_POST
def api_guest_contact(request):
    data = _json_body(request)
    first_name = str(data.get("first_name", "")).strip()
    last_name = str(data.get("last_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    message_text = str(data.get("message", "")).strip()
    full_name = f"{first_name} {last_name}".strip()

    errors = {}
    if not first_name:
        errors["first_name"] = "First name is required."
    if not last_name:
        errors["last_name"] = "Last name is required."
    try:
        validate_email(email)
    except ValidationError:
        errors["email"] = "Enter a valid email address."
    if not message_text:
        errors["message"] = "Message is required."

    if errors:
        return JsonResponse({"success": False, "errors": errors, "error": "Please complete the form."}, status=400)

    if not request.session.session_key:
        request.session.create()

    product = None
    product_id = data.get("product_id")
    if product_id:
        product = Product.objects.filter(id=product_id).select_related("category", "brand", "vendor").first()

    conversation = SmartChatConversation.objects.create(
        user=request.user if request.user.is_authenticated else None,
        session_key=request.session.session_key or "",
        product=product,
        status=SmartChatConversation.STATUS_ADMIN_REQUESTED,
        title="Arolana support request",
        customer_first_name=first_name[:100],
        customer_last_name=last_name[:100],
        customer_name=full_name[:200],
        customer_email=email,
        page_url=data.get("page_url", "")[:700],
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:1200],
        selected_variants=data.get("selected_variants") or {},
        admin_requested_at=timezone.now(),
    )
    create_system_message(conversation, f"Visitor details captured: {full_name} <{email}>.", {
        "guest_contact": True,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
    })
    user_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_USER,
        user=request.user if request.user.is_authenticated else None,
        message=message_text,
        metadata={
            "guest_contact": True,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "page_url": data.get("page_url", ""),
            "product_name": data.get("product_name", ""),
            "sku": data.get("sku", ""),
            "product_id": product_id or "",
            "selected_variants": data.get("selected_variants") or {},
            "source": "visitor_capture_form",
        },
    )
    reply = _guest_thank_you_message(full_name)
    ai_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_AI,
        message=reply,
        metadata={"guest_contact_confirmation": True},
    )
    _notify_staff_new_conversation(
        conversation,
        "New Arolana guest chat",
        (
            f"Guest contact details:\n"
            f"Name: {full_name}\n"
            f"Email: {email}\n"
            f"Message: {message_text[:500]}"
        ),
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


@require_POST
def api_message(request):
    data = _json_body(request)
    message = str(data.get("message", "")).strip()
    if not message:
        return JsonResponse({"success": False, "error": "Message is required."}, status=400)

    if not request.user.is_authenticated:
        guest_conversation_id = _safe_int(data.get("conversation_id"), default=0)
        if not guest_conversation_id or not _get_customer_conversation(request, guest_conversation_id):
            return JsonResponse({
                "success": False,
                "requires_guest_contact": True,
                "error": GUEST_CONTACT_PROMPT,
            }, status=403)

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
    _set_typing(conversation.id, "customer", False)

    if hasattr(conversation, "last_message_at"):
        conversation.last_message_at = user_message.created_at
        conversation.save(update_fields=["last_message_at", "updated_at"])

    if conversation.status in [SmartChatConversation.STATUS_ADMIN_REQUESTED, SmartChatConversation.STATUS_ADMIN_ACTIVE]:
        _notify_staff_customer_message(conversation, user_message)
        return JsonResponse({
            "success": True,
            "conversation_id": conversation.id,
            "status": conversation.status,
            "admin_only": True,
            "handoff_requested": conversation.status == SmartChatConversation.STATUS_ADMIN_REQUESTED,
            "messages": [_message_payload(user_message)],
        })

    handoff = should_handoff(message)
    if handoff:
        was_already_waiting = conversation.status in [
            SmartChatConversation.STATUS_ADMIN_REQUESTED,
            SmartChatConversation.STATUS_ADMIN_ACTIVE,
        ]
        conversation.mark_admin_requested()
        if not was_already_waiting:
            create_system_message(conversation, "Customer requested admin support. Waiting for admin takeover.")
            create_support_ticket(
                conversation,
                title="Customer requested Arolana admin",
                description=message,
                intent="human_handoff",
                priority="high",
                metadata={"source": "web_smartchat", "event": "handoff_request"},
            )
            _notify_staff_new_conversation(
                conversation,
                "Customer requested Arolana admin",
                f"{conversation.customer_display} requested admin support from Smart Chat.",
            )
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

    if product and not conversation.product_id:
        conversation.product = product
        conversation.save(update_fields=["product", "updated_at"])
    reply, ai_context = ai_operations_reply(
        conversation,
        message,
        audience=SmartChatConversation.AUDIENCE_CUSTOMER,
        actor_user=request.user if request.user.is_authenticated else None,
    )
    ai_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_AI,
        message=reply,
        metadata={"model_mode": "ai_operations", "context": ai_context},
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
def api_upload_image(request):
    if not request.user.is_authenticated:
        guest_conversation_id = _safe_int(request.POST.get("conversation_id"), default=0)
        if not guest_conversation_id or not _get_customer_conversation(request, guest_conversation_id):
            return JsonResponse({
                "success": False,
                "requires_guest_contact": True,
                "error": GUEST_CONTACT_PROMPT,
            }, status=403)

    uploaded_file = request.FILES.get("image")
    image_error = _validate_chat_image(uploaded_file)
    if image_error:
        return JsonResponse({"success": False, "error": image_error}, status=400)

    selected_variants = {}
    raw_variants = request.POST.get("selected_variants", "")
    if raw_variants:
        try:
            selected_variants = json.loads(raw_variants)
        except Exception:
            selected_variants = {}

    product = None
    product_id = request.POST.get("product_id")
    if product_id:
        product = Product.objects.filter(id=product_id).select_related("category", "brand", "vendor").first()

    data = {
        "conversation_id": request.POST.get("conversation_id", ""),
        "message": request.POST.get("message", "Customer uploaded an image."),
        "page_url": request.POST.get("page_url", "")[:700],
        "selected_variants": selected_variants,
    }
    conversation = _get_or_create_conversation(request, data, product=product)
    conversation.selected_variants = selected_variants
    conversation.save(update_fields=["selected_variants", "updated_at"])

    user_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_USER,
        user=request.user if request.user.is_authenticated else None,
        message=request.POST.get("message", "Image uploaded."),
        image=uploaded_file,
        metadata={
            "attachment_type": "image",
            "selected_variants": selected_variants,
            "sku": request.POST.get("sku", ""),
            "product_name": request.POST.get("product_name", ""),
            "content_type": uploaded_file.content_type,
            "file_size": uploaded_file.size,
        },
    )
    _set_typing(conversation.id, "customer", False)

    already_waiting = conversation.status in [
        SmartChatConversation.STATUS_ADMIN_REQUESTED,
        SmartChatConversation.STATUS_ADMIN_ACTIVE,
    ]
    if not already_waiting:
        conversation.mark_admin_requested()
        create_system_message(conversation, "Customer uploaded an image. Waiting for admin review.")

    _notify_staff_customer_message(conversation, user_message)

    messages = [_message_payload(user_message)]
    reply = ""
    if not already_waiting:
        reply = "I received your image. An Arolana admin can review it and continue from this chat shortly."
        ai_message = SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_AI,
            message=reply,
            metadata={"image_upload_confirmation": True},
        )
        messages.append(_message_payload(ai_message))

    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "status": conversation.status,
        "handoff_requested": conversation.status == SmartChatConversation.STATUS_ADMIN_REQUESTED,
        "reply": reply,
        "messages": messages,
    })


@require_POST
def api_request_admin(request):
    data = _json_body(request)
    if not request.user.is_authenticated:
        guest_conversation_id = _safe_int(data.get("conversation_id"), default=0)
        if not guest_conversation_id or not _get_customer_conversation(request, guest_conversation_id):
            return JsonResponse({
                "success": False,
                "requires_guest_contact": True,
                "error": GUEST_CONTACT_PROMPT,
            }, status=403)

    conversation = _get_or_create_conversation(request, data)
    already_waiting = conversation.status in [
        SmartChatConversation.STATUS_ADMIN_REQUESTED,
        SmartChatConversation.STATUS_ADMIN_ACTIVE,
    ]
    conversation.mark_admin_requested()
    if not already_waiting:
        message = str(data.get("message", "Customer requested admin support.")).strip()
        create_system_message(conversation, message)
        create_support_ticket(
            conversation,
            title="Admin support requested",
            description=message,
            intent="human_handoff",
            priority="high",
            metadata={"source": "request_admin_endpoint"},
        )
        _notify_staff_new_conversation(
            conversation,
            "Customer requested Arolana admin",
            f"{conversation.customer_display} requested admin support from Smart Chat.",
        )
    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "status": conversation.status,
        "reply": "" if already_waiting else "Admin support has been requested. Please keep this chat open.",
        "already_requested": already_waiting,
        "admin_inbox_url": reverse("smartchat:admin_inbox"),
    })


@require_GET
def api_poll(request):
    conversation_id = _safe_int(request.GET.get("conversation_id"), default=0)
    after_id = _safe_int(request.GET.get("after_id"), default=0)

    if not conversation_id:
        return JsonResponse({"success": False, "error": "conversation_id is required."}, status=400)

    conversation = _get_customer_conversation(request, conversation_id)
    if not conversation:
        payload = {"success": False, "error": "Conversation not found."}
        if not request.user.is_authenticated:
            payload["requires_guest_contact"] = True
            payload["error"] = GUEST_CONTACT_PROMPT
        return JsonResponse(payload, status=404)

    messages = conversation.messages.filter(id__gt=after_id, is_private_note=False).order_by("id")
    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "status": conversation.status,
        "assigned_admin": conversation.assigned_admin.get_full_name() or conversation.assigned_admin.username if conversation.assigned_admin else "",
        "typing": _typing_payload(conversation, "admin"),
        "messages": [_message_payload(m) for m in messages],
    })


@require_POST
def api_typing(request):
    data = _json_body(request)
    conversation_id = _safe_int(data.get("conversation_id"), default=0)
    conversation = _get_customer_conversation(request, conversation_id)
    if not conversation:
        return JsonResponse({"success": False, "error": "Conversation not found."}, status=404)

    _set_typing(conversation.id, "customer", bool(data.get("is_typing", True)))
    return JsonResponse({"success": True, "typing": _typing_payload(conversation, "customer")})


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

        admin_message = SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_ADMIN,
            user=request.user,
            message=message,
            is_private_note=private_note,
        )
        _set_typing(conversation.id, "admin", False)

        # Keep conversation ordering fresh for inbox/polling.
        if hasattr(conversation, "last_message_at"):
            conversation.last_message_at = admin_message.created_at
            conversation.save(update_fields=["last_message_at", "updated_at"])
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

    after_id = _safe_int(request.GET.get("after_id"), default=0)

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
        "typing": _typing_payload(conversation, "customer"),
        "messages": [_message_payload(message) for message in messages],
    })


@staff_member_required
@require_POST
def admin_typing(request, conversation_id):
    conversation = get_object_or_404(SmartChatConversation.objects.select_related("user", "assigned_admin"), id=conversation_id)
    data = _json_body(request)
    _set_typing(conversation.id, "admin", bool(data.get("is_typing", True)))
    return JsonResponse({"success": True, "typing": _typing_payload(conversation, "admin")})


def _mobile_clean_phone(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit() or ch == "+").strip()


def _mobile_clean_text(value):
    return str(value or "").strip()


def _mobile_json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _mobile_json_error(message, status=400):
    return JsonResponse(
        {
            "success": False,
            "message": str(message),
            "error": str(message),
        },
        status=status,
    )


def _mobile_customer_from_payload(payload):
    """
    Authenticates the mobile customer using the MobileCustomer phone + api_token
    created by the mobile Account PIN login flow.
    """
    try:
        from mobile_customers.models import MobileCustomer
    except Exception as error:
        raise RuntimeError(
            "mobile_customers app is required before mobile SmartChat can work."
        ) from error

    phone_number = _mobile_clean_phone(
        payload.get("phone_number")
        or payload.get("phoneNumber")
        or payload.get("phone")
    )
    api_token = _mobile_clean_text(
        payload.get("api_token") or payload.get("apiToken")
    )

    if not phone_number:
        raise ValueError("Phone number is required.")

    if not api_token:
        raise PermissionError("Login token is required. Login/register again.")

    customer = (
        MobileCustomer.objects
        .select_related("user")
        .filter(phone_number=phone_number, api_token=api_token)
        .first()
    )

    if not customer:
        raise PermissionError("Invalid login token. Login/register again.")

    return customer


def _mobile_customer_name(customer, payload=None):
    payload = payload or {}
    return (
        _mobile_clean_text(getattr(customer, "full_name", ""))
        or _mobile_clean_text(payload.get("full_name") or payload.get("fullName"))
        or _mobile_clean_text(getattr(customer.user, "get_full_name", lambda: "")())
        or _mobile_clean_text(getattr(customer.user, "username", ""))
        or "Mobile Customer"
    )


def _mobile_message_payload(message):
    """
    Keep the payload close to your existing _message_payload format,
    but also include simple aliases for the React Native app.
    """
    image_url = ""
    image_name = ""

    if getattr(message, "image", None):
        try:
            image_url = message.image.url
            image_name = message.image.name.rsplit("/", 1)[-1]
        except Exception:
            image_url = ""
            image_name = ""

    return {
        "id": message.id,
        "sender_type": message.sender_type,
        "sender": message.sender_type,
        "message": message.message,
        "text": message.message,
        "image_url": image_url,
        "image_name": image_name,
        "has_image": bool(image_url),
        "created_at": message.created_at.isoformat() if message.created_at else "",
        "is_private_note": getattr(message, "is_private_note", False),
    }


def _mobile_conversation_payload(conversation):
    messages = (
        conversation.messages
        .filter(is_private_note=False)
        .order_by("created_at")[:250]
    )

    return {
        "id": conversation.id,
        "conversation_id": conversation.id,
        "status": conversation.status,
        "title": conversation.title,
        "customer_name": conversation.customer_display,
        "customer_avatar_url": getattr(conversation, "customer_avatar_url", "") or "",
        "last_message_at": (
            conversation.last_message_at.isoformat()
            if conversation.last_message_at else ""
        ),
        "messages": [_mobile_message_payload(message) for message in messages],
    }


def _mobile_get_existing_conversation(customer, conversation_id=0):
    if not conversation_id:
        return None

    lookup = Q(id=conversation_id)

    # The mobile customer is linked to a Django user by mobile_customers.
    if getattr(customer, "user_id", None):
        lookup &= Q(user=customer.user)

    # Extra fallback ownership check.
    lookup |= Q(id=conversation_id, customer_phone=customer.phone_number)

    return SmartChatConversation.objects.filter(lookup).first()


def _mobile_get_or_create_conversation(customer, payload):
    conversation_id = _safe_int(payload.get("conversation_id"), default=0)
    conversation = _mobile_get_existing_conversation(customer, conversation_id)

    if conversation:
        return conversation

    # Reuse an existing open mobile conversation for this customer when available.
    conversation = (
        SmartChatConversation.objects
        .filter(
            Q(user=customer.user) | Q(customer_phone=customer.phone_number),
            status__in=[
                SmartChatConversation.STATUS_AI,
                SmartChatConversation.STATUS_ADMIN_REQUESTED,
                SmartChatConversation.STATUS_ADMIN_ACTIVE,
            ],
        )
        .order_by("-last_message_at")
        .first()
    )

    if conversation:
        return conversation

    full_name = _mobile_customer_name(customer, payload)
    email = (
        _mobile_clean_text(getattr(customer, "email", ""))
        or _mobile_clean_text(getattr(customer.user, "email", ""))
        or _mobile_clean_text(payload.get("email"))
    )

    conversation = SmartChatConversation.objects.create(
        user=customer.user,
        session_key=f"mobile-{customer.id}",
        status=SmartChatConversation.STATUS_AI,
        audience=SmartChatConversation.AUDIENCE_CUSTOMER,
        title="Arolana Mobile Smart Chat",
        customer_name=full_name[:200],
        customer_email=email,
        customer_phone=customer.phone_number,
        page_url="Arolana Mobile App",
        user_agent="Arolana Mobile App",
        selected_variants={
            "source": "arolana_mobile_app",
            "mobile_customer_id": customer.id,
        },
    )

    try:
        create_system_message(
            conversation,
            f"Mobile Smart Chat started by {full_name}.",
            {
                "source": "arolana_mobile_app",
                "mobile_customer_id": customer.id,
            },
        )
    except Exception:
        SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_SYSTEM,
            message=f"Mobile Smart Chat started by {full_name}.",
            metadata={
                "source": "arolana_mobile_app",
                "mobile_customer_id": customer.id,
            },
        )

    return conversation


def _mobile_notify_staff(conversation, message=None):
    """
    Reuse your existing notification helper when available.
    """
    try:
        if message:
            _notify_staff_customer_message(conversation, message)
        else:
            _notify_staff_new_conversation(
                conversation,
                "New Arolana mobile Smart Chat",
                f"{conversation.customer_display} started a mobile Smart Chat conversation.",
                priority=3,
                metadata={
                    "event": "mobile_smartchat",
                    "smartchat_conversation_id": conversation.id,
                },
            )
    except Exception:
        return


@csrf_exempt
@require_POST
def mobile_smartchat_start_api(request):
    payload = _mobile_json_body(request)

    try:
        customer = _mobile_customer_from_payload(payload)
        conversation = _mobile_get_or_create_conversation(customer, payload)
    except PermissionError as error:
        return _mobile_json_error(error, status=403)
    except Exception as error:
        return _mobile_json_error(error, status=400)

    _mobile_notify_staff(conversation)

    return JsonResponse(
        {
            "success": True,
            "conversation_id": conversation.id,
            "conversation": _mobile_conversation_payload(conversation),
            "messages": _mobile_conversation_payload(conversation)["messages"],
        }
    )


@csrf_exempt
@require_POST
def mobile_smartchat_send_api(request):
    payload = _mobile_json_body(request)

    try:
        customer = _mobile_customer_from_payload(payload)
        conversation = _mobile_get_or_create_conversation(customer, payload)
    except PermissionError as error:
        return _mobile_json_error(error, status=403)
    except Exception as error:
        return _mobile_json_error(error, status=400)

    message_text = _mobile_clean_text(payload.get("message") or payload.get("text"))

    if not message_text:
        return _mobile_json_error("Message is required.", status=400)

    if conversation.status == SmartChatConversation.STATUS_CLOSED:
        conversation.status = SmartChatConversation.STATUS_ADMIN_REQUESTED
        conversation.admin_requested_at = timezone.now()
        conversation.save(
            update_fields=[
                "status",
                "admin_requested_at",
                "updated_at",
            ]
        )

    user_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_USER,
        user=customer.user,
        message=message_text,
        metadata={
            "source": "arolana_mobile_app",
            "mobile_customer_id": customer.id,
            "phone_number": customer.phone_number,
        },
    )

    _set_typing(conversation.id, "customer", False)

    if hasattr(conversation, "touch"):
        conversation.touch()
    else:
        conversation.last_message_at = user_message.created_at
        conversation.save(update_fields=["last_message_at", "updated_at"])

    if conversation.status in [SmartChatConversation.STATUS_ADMIN_REQUESTED, SmartChatConversation.STATUS_ADMIN_ACTIVE]:
        _mobile_notify_staff(conversation, user_message)
    else:
        reply, ai_context = ai_operations_reply(
            conversation,
            message_text,
            audience=SmartChatConversation.AUDIENCE_CUSTOMER,
            actor_user=customer.user,
        )
        SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_AI,
            message=reply,
            metadata={
                "model_mode": "ai_operations",
                "context": ai_context,
                "source": "arolana_mobile_app",
            },
        )
        if conversation.status in [SmartChatConversation.STATUS_ADMIN_REQUESTED, SmartChatConversation.STATUS_ADMIN_ACTIVE]:
            _mobile_notify_staff(conversation, user_message)

    conversation.refresh_from_db()

    return JsonResponse(
        {
            "success": True,
            "message": "Message sent.",
            "conversation_id": conversation.id,
            "conversation": _mobile_conversation_payload(conversation),
            "messages": _mobile_conversation_payload(conversation)["messages"],
        }
    )


@csrf_exempt
@require_POST
def mobile_smartchat_upload_image_api(request):
    try:
        customer = _mobile_customer_from_payload(request.POST)
        conversation = _mobile_get_or_create_conversation(customer, request.POST)
    except PermissionError as error:
        return _mobile_json_error(error, status=403)
    except Exception as error:
        return _mobile_json_error(error, status=400)

    uploaded_file = request.FILES.get("image")
    image_error = _validate_chat_image(uploaded_file)
    if image_error:
        return _mobile_json_error(image_error, status=400)

    message_text = _mobile_clean_text(request.POST.get("message")) or "Customer uploaded an image from the Arolana mobile app."

    if conversation.status == SmartChatConversation.STATUS_CLOSED:
        conversation.status = SmartChatConversation.STATUS_ADMIN_REQUESTED
        conversation.admin_requested_at = timezone.now()
        conversation.save(update_fields=["status", "admin_requested_at", "updated_at"])

    if conversation.status == SmartChatConversation.STATUS_AI:
        conversation.mark_admin_requested()

    user_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_USER,
        user=customer.user,
        message=message_text,
        image=uploaded_file,
        metadata={
            "source": "arolana_mobile_app",
            "mobile_customer_id": customer.id,
            "phone_number": customer.phone_number,
            "attachment_type": "image",
            "content_type": uploaded_file.content_type,
            "file_size": uploaded_file.size,
        },
    )

    _set_typing(conversation.id, "customer", False)

    if hasattr(conversation, "touch"):
        conversation.touch()
    else:
        conversation.last_message_at = user_message.created_at
        conversation.save(update_fields=["last_message_at", "updated_at"])

    _mobile_notify_staff(conversation, user_message)
    conversation.refresh_from_db()

    return JsonResponse(
        {
            "success": True,
            "message": "Image sent.",
            "conversation_id": conversation.id,
            "conversation": _mobile_conversation_payload(conversation),
            "messages": _mobile_conversation_payload(conversation)["messages"],
        }
    )


@csrf_exempt
@require_POST
def mobile_smartchat_poll_api(request):
    payload = _mobile_json_body(request)

    try:
        customer = _mobile_customer_from_payload(payload)
        conversation = _mobile_get_or_create_conversation(customer, payload)
    except PermissionError as error:
        return _mobile_json_error(error, status=403)
    except Exception as error:
        return _mobile_json_error(error, status=400)

    return JsonResponse(
        {
            "success": True,
            "conversation_id": conversation.id,
            "conversation": _mobile_conversation_payload(conversation),
            "messages": _mobile_conversation_payload(conversation)["messages"],
            "typing": {
                "admin": _typing_payload(conversation, "admin"),
                "customer": _typing_payload(conversation, "customer"),
            },
        }
    )


@csrf_exempt
@require_POST
def mobile_smartchat_mark_read_api(request):
    payload = _mobile_json_body(request)

    try:
        customer = _mobile_customer_from_payload(payload)
        conversation = _mobile_get_or_create_conversation(customer, payload)
    except PermissionError as error:
        return _mobile_json_error(error, status=403)
    except Exception as error:
        return _mobile_json_error(error, status=400)

    # Your existing SmartChatMessage model does not currently have customer read flags,
    # so this is intentionally a safe no-op for now.
    return JsonResponse(
        {
            "success": True,
            "message": "Marked as read.",
            "conversation_id": conversation.id,
            "conversation": _mobile_conversation_payload(conversation),
            "messages": _mobile_conversation_payload(conversation)["messages"],
        }
    )


def _ticket_payload(ticket):
    return {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "audience": ticket.audience,
        "intent": ticket.intent,
        "priority": ticket.priority,
        "status": ticket.status,
        "conversation_id": ticket.conversation_id,
        "order_id": ticket.order_id,
        "product_id": ticket.product_id,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else "",
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else "",
    }


def _operations_actor_from_request(request, payload):
    token = (
        request.headers.get("Authorization", "")
        .replace("Bearer ", "")
        .strip()
        or payload.get("token")
        or payload.get("staff_token")
    )
    if token:
        try:
            from staff_mobile.models import StaffMobileToken

            session = (
                StaffMobileToken.objects
                .select_related("user", "rider", "rider__user")
                .filter(token=token, is_active=True)
                .first()
            )
            if session:
                session.last_used_at = timezone.now()
                session.save(update_fields=["last_used_at", "updated_at"])
                return {
                    "audience": session.role,
                    "user": session.user or (session.rider.user if session.rider_id else None),
                    "rider": session.rider,
                    "session": session,
                }
        except Exception:
            pass
    if request.user.is_authenticated:
        if request.user.is_staff:
            audience = SmartChatConversation.AUDIENCE_ADMIN
        elif hasattr(request.user, "vendor_profile"):
            audience = SmartChatConversation.AUDIENCE_VENDOR
        elif hasattr(request.user, "rider_profile"):
            audience = SmartChatConversation.AUDIENCE_RIDER
        else:
            audience = SmartChatConversation.AUDIENCE_CUSTOMER
        return {
            "audience": audience,
            "user": request.user,
            "rider": getattr(request.user, "rider_profile", None),
            "session": None,
        }
    return {"audience": SmartChatConversation.AUDIENCE_GUEST, "user": None, "rider": None, "session": None}


def _operations_conversation(actor, payload):
    conversation_id = _safe_int(payload.get("conversation_id"), default=0)
    user = actor.get("user")
    rider = actor.get("rider")
    audience = actor.get("audience") or SmartChatConversation.AUDIENCE_GUEST
    conversation = None
    if conversation_id:
        qs = SmartChatConversation.objects.filter(id=conversation_id)
        if user:
            qs = qs.filter(Q(user=user) | Q(assigned_admin=user))
        conversation = qs.first()
    if conversation:
        return conversation

    conversation = SmartChatConversation.objects.create(
        user=user,
        rider_profile=rider,
        vendor_profile=getattr(user, "vendor_profile", None) if user else None,
        audience=audience,
        status=SmartChatConversation.STATUS_AI,
        title=payload.get("title") or f"Arolana {audience.title()} Operations Assistant",
        customer_name=(user.get_full_name() or user.username if user else payload.get("name", ""))[:200],
        customer_email=(getattr(user, "email", "") if user else payload.get("email", ""))[:254],
        customer_phone=payload.get("phone", "")[:40],
        page_url=payload.get("page_url", "")[:700],
        user_agent=request_user_agent(payload),
        context={"source": payload.get("source", "operations_api")},
    )
    create_system_message(conversation, f"Arolana Chat started for {audience}.")
    return conversation


def request_user_agent(payload):
    return str(payload.get("user_agent") or payload.get("platform") or "Arolana Operations API")[:1200]


@csrf_exempt
@require_POST
def operations_message_api(request):
    payload = _json_body(request)
    message = str(payload.get("message") or payload.get("text") or "").strip()
    if not message:
        return JsonResponse({"success": False, "message": "Message is required."}, status=400)

    actor = _operations_actor_from_request(request, payload)
    if actor["audience"] == SmartChatConversation.AUDIENCE_GUEST:
        return JsonResponse({"success": False, "message": "Login is required for Arolana Operations Assistant."}, status=403)

    conversation = _operations_conversation(actor, payload)
    user_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_USER,
        user=actor.get("user"),
        message=message,
        metadata={
            "source": payload.get("source", "operations_api"),
            "audience": actor["audience"],
        },
    )
    reply, ai_context = ai_operations_reply(
        conversation,
        message,
        audience=actor["audience"],
        actor_user=actor.get("user"),
        rider=actor.get("rider"),
    )
    ai_message = SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_AI,
        message=reply,
        metadata={"model_mode": "ai_operations", "context": ai_context},
    )
    return JsonResponse({
        "success": True,
        "conversation_id": conversation.id,
        "status": conversation.status,
        "intent": conversation.current_intent,
        "urgency": conversation.urgency,
        "reply": reply,
        "messages": [_message_payload(user_message), _message_payload(ai_message)],
        "tickets": [_ticket_payload(ticket) for ticket in conversation.support_tickets.order_by("-created_at")[:5]],
    })


@csrf_exempt
@require_POST
def operations_create_ticket_api(request):
    payload = _json_body(request)
    actor = _operations_actor_from_request(request, payload)
    if actor["audience"] == SmartChatConversation.AUDIENCE_GUEST:
        return JsonResponse({"success": False, "message": "Login is required to create a support ticket."}, status=403)
    conversation = _operations_conversation(actor, payload)
    title = str(payload.get("title") or "Arolana support request").strip()
    description = str(payload.get("description") or payload.get("message") or "").strip()
    if not description:
        return JsonResponse({"success": False, "message": "Ticket description is required."}, status=400)
    ticket = create_support_ticket(
        conversation,
        title=title,
        description=description,
        intent=str(payload.get("intent") or conversation.current_intent or "support"),
        priority=str(payload.get("priority") or "normal"),
        metadata={"source": payload.get("source", "operations_api"), "audience": actor["audience"]},
    )
    return JsonResponse({"success": True, "ticket": _ticket_payload(ticket), "conversation_id": conversation.id})


@require_GET
def operations_tickets_api(request):
    actor = _operations_actor_from_request(request, request.GET)
    if actor["audience"] == SmartChatConversation.AUDIENCE_GUEST:
        return JsonResponse({"success": False, "message": "Login is required."}, status=403)
    tickets = SmartChatSupportTicket.objects.select_related("conversation", "created_by")
    user = actor.get("user")
    if actor["audience"] != SmartChatConversation.AUDIENCE_ADMIN:
        tickets = tickets.filter(Q(created_by=user) | Q(conversation__user=user))
    status = request.GET.get("status")
    if status:
        tickets = tickets.filter(status=status)
    return JsonResponse({"success": True, "tickets": [_ticket_payload(ticket) for ticket in tickets.order_by("-created_at")[:100]]})
