from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from orders.models import Order


@login_required
def robot_status(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    if not (request.user.is_staff or request.user == order.user):
        return JsonResponse({"success": False, "error": "Not allowed."}, status=403)

    process = getattr(order, "robot_process", None)
    if not process:
        return JsonResponse({"success": True, "has_robot": False, "order_number": order.order_number})

    return JsonResponse({
        "success": True,
        "has_robot": True,
        "order_number": order.order_number,
        "status": process.current_status,
        "status_label": process.get_current_status_display(),
        "requires_admin": process.requires_admin,
        "legacy_delivery_id": process.legacy_delivery_id,
        "live_delivery_id": process.live_delivery_id,
        "activities": [
            {
                "status": activity.status,
                "level": activity.level,
                "message": activity.message,
                "created_at": activity.created_at.isoformat(),
            }
            for activity in process.activities.order_by("-created_at")[:12]
        ],
    })
