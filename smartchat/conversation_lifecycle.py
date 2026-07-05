from django.utils import timezone

from .models import HumanTakeoverRequest, SmartChatConversation, SmartChatMessage


def reopen_closed_conversation(conversation):
    if conversation.status != SmartChatConversation.STATUS_CLOSED:
        return False
    conversation.status = SmartChatConversation.STATUS_AI
    conversation.assigned_admin = None
    conversation.admin_requested_at = None
    conversation.resolved_at = None
    context = dict(conversation.context or {})
    state = dict(context.get("state") or {})
    support = dict(state.get("support") or {})
    support.update({"status": "ai", "requires_handoff": False, "handoff_reason": ""})
    state["support"] = support
    context["state"] = state
    context["support_status"] = SmartChatConversation.STATUS_AI
    conversation.context = context
    conversation.save(update_fields=[
        "status", "assigned_admin", "admin_requested_at", "resolved_at",
        "context", "updated_at",
    ])
    conversation.takeover_requests.filter(
        status__in=[
            HumanTakeoverRequest.STATUS_PENDING,
            HumanTakeoverRequest.STATUS_ASSIGNED,
        ],
    ).update(status=HumanTakeoverRequest.STATUS_CANCELLED, resolved_at=timezone.now())
    SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_SYSTEM,
        message="Conversation reopened for Arolana Chat.",
        metadata={"event": "conversation_reopened"},
    )
    return True
