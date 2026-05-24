import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .models import DeliveryRequest, DeliveryVehicle, RiderProfile
from .services import accept_delivery, calculate_live_delivery_quote, update_rider_location


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _user_can_view_delivery(request, delivery):
    if request.user.is_authenticated and request.user.is_staff:
        return True
    if request.user.is_authenticated and delivery.order.user_id == request.user.id:
        return True
    return False


@login_required
def rider_register(request):
    vehicles = DeliveryVehicle.objects.filter(is_active=True).order_by("name")
    rider = RiderProfile.objects.filter(user=request.user).first()
    if request.method == "POST":
        rider_type = request.POST.get("rider_type") or RiderProfile.RIDER_INDEPENDENT
        vehicle = DeliveryVehicle.objects.filter(id=request.POST.get("vehicle")).first()
        rider, _created = RiderProfile.objects.get_or_create(user=request.user)
        rider.rider_type = rider_type
        rider.vehicle = vehicle
        rider.phone = request.POST.get("phone", "").strip()
        rider.emergency_phone = request.POST.get("emergency_phone", "").strip()
        if request.FILES.get("id_document"):
            rider.id_document = request.FILES["id_document"]
        if request.FILES.get("driver_license"):
            rider.driver_license = request.FILES["driver_license"]
        if request.FILES.get("vehicle_document"):
            rider.vehicle_document = request.FILES["vehicle_document"]
        rider.save()
        messages.success(request, "Your rider profile has been submitted for approval.")
        return redirect("deliveries:rider_dashboard")
    return render(request, "deliveries/rider_register.html", {"vehicles": vehicles, "rider": rider})


@login_required
def rider_dashboard(request):
    rider = RiderProfile.objects.filter(user=request.user).select_related("vehicle", "zone").first()
    if not rider:
        return redirect("deliveries:rider_register")

    active_deliveries = (
        DeliveryRequest.objects
        .filter(rider=rider)
        .exclude(status__in=[DeliveryRequest.STATUS_DELIVERED, DeliveryRequest.STATUS_CANCELLED, DeliveryRequest.STATUS_FAILED, DeliveryRequest.STATUS_RETURNED])
        .select_related("order")
        .order_by("-created_at")
    )
    available_deliveries = DeliveryRequest.objects.filter(
        rider__isnull=True,
        status__in=[DeliveryRequest.STATUS_PENDING, DeliveryRequest.STATUS_ASSIGNED],
    ).select_related("order").order_by("-created_at")[:30]
    completed_deliveries = DeliveryRequest.objects.filter(rider=rider, status=DeliveryRequest.STATUS_DELIVERED).order_by("-updated_at")[:10]
    return render(request, "deliveries/rider_dashboard.html", {
        "rider": rider,
        "active_deliveries": active_deliveries,
        "available_deliveries": available_deliveries,
        "completed_deliveries": completed_deliveries,
    })


@login_required
@require_POST
def rider_go_online(request):
    rider = get_object_or_404(RiderProfile, user=request.user)
    if rider.kyc_status != RiderProfile.KYC_APPROVED or rider.is_suspended:
        messages.error(request, "Admin must approve your rider profile before you can go online.")
    else:
        rider.is_online = True
        rider.save(update_fields=["is_online", "updated_at"])
        messages.success(request, "You are now online for deliveries.")
    return redirect("deliveries:rider_dashboard")


@login_required
@require_POST
def rider_go_offline(request):
    rider = get_object_or_404(RiderProfile, user=request.user)
    rider.is_online = False
    rider.save(update_fields=["is_online", "updated_at"])
    messages.success(request, "You are now offline.")
    return redirect("deliveries:rider_dashboard")


@login_required
@require_POST
def rider_accept_delivery(request, delivery_id):
    rider = get_object_or_404(RiderProfile, user=request.user)
    delivery = get_object_or_404(DeliveryRequest, id=delivery_id)
    try:
        accept_delivery(delivery, rider)
        messages.success(request, f"Delivery {delivery.tracking_code} accepted.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("deliveries:rider_dashboard")


@login_required
@require_POST
def rider_update_status(request, delivery_id):
    rider = get_object_or_404(RiderProfile, user=request.user)
    delivery = get_object_or_404(DeliveryRequest, id=delivery_id, rider=rider)
    status = request.POST.get("status")
    note = request.POST.get("note", "")
    latitude = request.POST.get("latitude") or None
    longitude = request.POST.get("longitude") or None
    if status not in dict(DeliveryRequest.STATUS_CHOICES):
        messages.error(request, "Invalid delivery status.")
    else:
        delivery.set_status(status, actor=request.user, note=note, latitude=latitude, longitude=longitude)
        messages.success(request, f"Delivery status updated to {delivery.get_status_display()}.")
    return redirect("deliveries:rider_dashboard")


@login_required
@require_POST
def api_rider_location(request, delivery_id):
    rider = get_object_or_404(RiderProfile, user=request.user)
    delivery = get_object_or_404(DeliveryRequest, id=delivery_id, rider=rider)
    data = _json_body(request) or request.POST
    try:
        ping = update_rider_location(
            delivery,
            rider,
            data.get("latitude"),
            data.get("longitude"),
            heading=data.get("heading"),
            speed_kmph=data.get("speed_kmph"),
            accuracy_meters=data.get("accuracy_meters"),
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    return JsonResponse({
        "success": True,
        "latitude": str(ping.latitude),
        "longitude": str(ping.longitude),
        "created_at": ping.created_at.isoformat(),
    })


@require_GET
def api_delivery_quote(request):
    quote = calculate_live_delivery_quote(
        pickup_latitude=request.GET.get("pickup_latitude"),
        pickup_longitude=request.GET.get("pickup_longitude"),
        dropoff_latitude=request.GET.get("dropoff_latitude"),
        dropoff_longitude=request.GET.get("dropoff_longitude"),
        service_level=request.GET.get("delivery_service_level") or "standard",
        fallback_fee=request.GET.get("fallback_fee"),
    )
    return JsonResponse({
        "success": True,
        "fee": str(quote["fee"]),
        "fee_float": float(quote["fee"]),
        "distance_km": str(quote["distance_km"]),
        "estimated_duration_minutes": quote["estimated_duration_minutes"],
        "rider_earning": str(quote["rider_earning"]),
        "is_distance_based": quote["is_distance_based"],
        "message": quote["message"],
    })


def customer_tracking(request, tracking_code):
    delivery = get_object_or_404(
        DeliveryRequest.objects.select_related("order__user", "rider__user", "requested_vehicle").prefetch_related("status_history", "location_pings"),
        tracking_code__iexact=tracking_code,
    )
    email = (request.GET.get("email") or "").strip().lower()
    can_view = _user_can_view_delivery(request, delivery)
    if not can_view and email and delivery.order.user.email.lower() == email:
        can_view = True
    if not can_view:
        return render(request, "deliveries/customer_tracking.html", {
            "delivery": delivery,
            "needs_email": True,
            "email": email,
        })
    return render(request, "deliveries/customer_tracking.html", {
        "delivery": delivery,
        "needs_email": False,
        "latest_location": delivery.latest_location,
        "history": delivery.status_history.all(),
    })
