import json
import urllib.request

from django.db.models import Q


def send_support_reply_push(conversation, message):
    try:
        from orders.models import MobilePushToken

        lookup = Q()
        if conversation.customer_phone:
            lookup |= Q(phone_number=conversation.customer_phone)
        if conversation.customer_email:
            lookup |= Q(email__iexact=conversation.customer_email)
        if not lookup:
            return False
        tokens = MobilePushToken.objects.filter(
            lookup, is_active=True,
        ).exclude(expo_push_token="").values_list("expo_push_token", flat=True).distinct()[:20]
        payloads = [{
            "to": token,
            "sound": "default",
            "title": "Arolana support replied",
            "body": str(message)[:180],
            "data": {
                "screen": "ArolanaSmartChat",
                "smartchat_conversation_id": conversation.id,
            },
        } for token in tokens]
        if not payloads:
            return False
        push_request = urllib.request.Request(
            "https://exp.host/--/api/v2/push/send",
            data=json.dumps(payloads).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(push_request, timeout=4).read()
        return True
    except Exception:
        return False
