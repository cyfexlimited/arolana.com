import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from accounts.utils.otp_utils import create_otp
from notifications.models import Notification
from staff_mobile.models import RiderCredential

from .models import (
    DeliveryRequest,
    DeliveryVehicle,
    RiderPayout,
    RiderProfile,
    RiderWallet,
)
from .services import (
    accept_delivery,
    calculate_live_delivery_quote,
    update_rider_current_location,
    update_rider_location,
)


# =============================================================================
# RIDER DELIVERY STATUS WORKFLOW
# =============================================================================


RIDER_STATUS_ACTIONS = {
    DeliveryRequest.STATUS_ASSIGNED: [
        (
            DeliveryRequest.STATUS_ACCEPTED,
            "Accept assigned job",
            "fa-check",
            "bg-green-600",
        ),
    ],
    DeliveryRequest.STATUS_ACCEPTED: [
        (
            DeliveryRequest.STATUS_ARRIVED_PICKUP,
            "Arrived at pickup",
            "fa-location-dot",
            "bg-indigo-600",
        ),
    ],
    DeliveryRequest.STATUS_ARRIVED_PICKUP: [
        (
            DeliveryRequest.STATUS_PICKED_UP,
            "Mark picked up",
            "fa-box",
            "bg-blue-600",
        ),
    ],
    DeliveryRequest.STATUS_PICKED_UP: [
        (
            DeliveryRequest.STATUS_IN_TRANSIT,
            "Start delivery",
            "fa-route",
            "bg-blue-600",
        ),
    ],
    DeliveryRequest.STATUS_IN_TRANSIT: [
        (
            DeliveryRequest.STATUS_ARRIVED_CUSTOMER,
            "Arrived at customer",
            "fa-location-crosshairs",
            "bg-indigo-600",
        ),
    ],
    DeliveryRequest.STATUS_ARRIVED_CUSTOMER: [
        (
            DeliveryRequest.STATUS_DELIVERED,
            "Mark delivered",
            "fa-check",
            "bg-green-600",
        ),
        (
            DeliveryRequest.STATUS_FAILED,
            "Report issue",
            "fa-triangle-exclamation",
            "bg-red-600",
        ),
    ],
    DeliveryRequest.STATUS_FAILED: [
        (
            DeliveryRequest.STATUS_RETURNED,
            "Mark returned",
            "fa-rotate-left",
            "bg-gray-800",
        ),
    ],
}


# =============================================================================
# GENERIC HELPERS
# =============================================================================


def _json_body(request):
    try:
        return json.loads(
            request.body.decode("utf-8")
            or "{}"
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return {}


def _validation_error_messages(exc):
    """
    Convert Django ValidationError into readable messages.
    """

    if hasattr(
        exc,
        "message_dict",
    ):
        output = []

        for (
            field_name,
            field_errors,
        ) in exc.message_dict.items():
            for error in field_errors:
                output.append(
                    f"{field_name}: {error}"
                )

        return output

    return [
        str(message)
        for message in exc.messages
    ]


def _show_validation_errors(
    request,
    exc,
):
    for error in (
        _validation_error_messages(
            exc
        )
    ):
        messages.error(
            request,
            error,
        )


# =============================================================================
# SECURE UPLOAD VALIDATION HELPERS
# =============================================================================


def _validate_model_upload(
    model_class,
    field_name,
    upload,
):
    """
    Explicitly run the validators attached to a model upload field.

    This is used for direct request.FILES assignment paths where no ModelForm
    or serializer validation boundary exists.
    """

    if not upload:
        return

    field = (
        model_class._meta.get_field(
            field_name
        )
    )

    field.run_validators(
        upload
    )

    try:
        upload.seek(0)

    except Exception:
        pass


def _validate_rider_uploads(
    uploads,
):
    """
    Validate all submitted RiderProfile private upload fields.

    Only fields actually supplied are validated.
    """

    upload_field_names = (
        "id_document",
        "driver_license",
        "vehicle_document",
        "profile_photo",
        "dashboard_image",
    )

    for field_name in upload_field_names:
        upload = uploads.get(
            field_name
        )

        if not upload:
            continue

        _validate_model_upload(
            RiderProfile,
            field_name,
            upload,
        )


def _validate_delivery_proof(
    upload,
):
    if not upload:
        return

    _validate_model_upload(
        DeliveryRequest,
        "proof_of_delivery",
        upload,
    )


def _reset_upload_streams(
    uploads,
):
    for upload in uploads.values():
        if not upload:
            continue

        try:
            upload.seek(0)

        except Exception:
            pass


# =============================================================================
# DELIVERY ACCESS
# =============================================================================


def _user_can_view_delivery(
    request,
    delivery,
):
    if (
        request.user.is_authenticated
        and request.user.is_staff
    ):
        return True

    if (
        request.user.is_authenticated
        and delivery.order.user_id
        == request.user.id
    ):
        return True

    return False


# =============================================================================
# RIDER ACCOUNT HELPERS
# =============================================================================


def _unique_rider_username(
    email,
):
    User = get_user_model()

    base = (
        slugify(
            str(email).split("@")[0]
        )
        or "rider"
    )

    username = base
    suffix = 2

    while User.objects.filter(
        username=username
    ).exists():
        username = (
            f"{base}{suffix}"
        )

        suffix += 1

    return username


def _rider_register_context(
    request,
    vehicles,
    rider=None,
):
    return {
        "vehicles": vehicles,
        "rider": rider,
        "is_public_registration": (
            not request.user.is_authenticated
        ),
        "rider_type_choices": (
            RiderProfile.RIDER_TYPE_CHOICES
        ),
    }


def _render_rider_registration(
    request,
    vehicles,
    rider=None,
):
    return render(
        request,
        "deliveries/rider_register.html",
        _rider_register_context(
            request,
            vehicles,
            rider,
        ),
    )


# =============================================================================
# PUBLIC / EXISTING RIDER REGISTRATION
# =============================================================================


def rider_register(request):
    vehicles = (
        DeliveryVehicle.objects
        .filter(
            is_active=True
        )
        .order_by(
            "name"
        )
    )

    rider = None

    if request.user.is_authenticated:
        rider = (
            RiderProfile.objects
            .filter(
                user=request.user
            )
            .first()
        )

    # -------------------------------------------------------------------------
    # AUTHENTICATED USER MUST VERIFY EMAIL
    # -------------------------------------------------------------------------

    if (
        request.user.is_authenticated
        and not getattr(
            request.user,
            "email_verified",
            False,
        )
    ):
        create_otp(
            request.user,
            request.user.email,
            "email",
        )

        request.session[
            "pending_email_verification_user_id"
        ] = request.user.id

        request.session[
            "pending_email_verification_next"
        ] = "deliveries:rider_dashboard"

        messages.info(
            request,
            (
                "Verify your email before submitting rider KYC. "
                "We sent a verification OTP to your email."
            ),
        )

        return redirect(
            "accounts:verify_email"
        )

    if request.method != "POST":
        return _render_rider_registration(
            request,
            vehicles,
            rider,
        )

    # -------------------------------------------------------------------------
    # COMMON PROFILE INPUT
    # -------------------------------------------------------------------------

    rider_type = (
        request.POST.get(
            "rider_type"
        )
        or RiderProfile.RIDER_INDEPENDENT
    )

    vehicle = (
        DeliveryVehicle.objects
        .filter(
            id=(
                request.POST.get(
                    "vehicle"
                )
                or request.POST.get(
                    "vehicle_id"
                )
            ),
            is_active=True,
        )
        .first()
    )

    phone = (
        request.POST.get(
            "phone",
            "",
        )
        .strip()
    )

    emergency_phone = (
        request.POST.get(
            "emergency_phone",
            "",
        )
        .strip()
    )

    about = (
        request.POST.get(
            "about",
            "",
        )
        .strip()
    )

    if (
        rider_type
        not in dict(
            RiderProfile.RIDER_TYPE_CHOICES
        )
    ):
        messages.error(
            request,
            "Please choose a valid rider type.",
        )

        return _render_rider_registration(
            request,
            vehicles,
            rider,
        )

    if not vehicle:
        messages.error(
            request,
            "Please choose your delivery vehicle.",
        )

        return _render_rider_registration(
            request,
            vehicles,
            rider,
        )

    if not phone:
        messages.error(
            request,
            "Please enter your phone number.",
        )

        return _render_rider_registration(
            request,
            vehicles,
            rider,
        )

    if len(
        about
    ) < 20:
        messages.error(
            request,
            (
                "About rider should be at least 20 characters "
                "so admin can review your delivery experience."
            ),
        )

        return _render_rider_registration(
            request,
            vehicles,
            rider,
        )

    # =========================================================================
    # NEW PUBLIC RIDER REGISTRATION
    # =========================================================================

    if not request.user.is_authenticated:
        User = get_user_model()

        full_name = (
            request.POST.get(
                "full_name",
                "",
            )
            .strip()
        )

        email = (
            request.POST.get(
                "email",
                "",
            )
            .strip()
            .lower()
        )

        password = (
            request.POST.get(
                "password",
                "",
            )
            .strip()
        )

        if (
            not full_name
            or not email
            or not password
        ):
            messages.error(
                request,
                (
                    "Full name, email and password/PIN "
                    "are required for rider registration."
                ),
            )

            return _render_rider_registration(
                request,
                vehicles,
                rider,
            )

        try:
            validate_email(
                email
            )

        except ValidationError:
            messages.error(
                request,
                "Enter a valid email address.",
            )

            return _render_rider_registration(
                request,
                vehicles,
                rider,
            )

        if User.objects.filter(
            email__iexact=email
        ).exists():
            messages.error(
                request,
                (
                    "An account with this email already exists. "
                    "Please sign in, then submit or update your rider profile."
                ),
            )

            return _render_rider_registration(
                request,
                vehicles,
                rider,
            )

        rider_uploads = {
            "id_document": (
                request.FILES.get(
                    "id_document"
                )
            ),
            "driver_license": (
                request.FILES.get(
                    "driver_license"
                )
            ),
            "vehicle_document": (
                request.FILES.get(
                    "vehicle_document"
                )
            ),
            "profile_photo": (
                request.FILES.get(
                    "profile_photo"
                )
            ),
            "dashboard_image": (
                request.FILES.get(
                    "dashboard_image"
                )
            ),
        }

        required_uploads = {
            "id_document": (
                rider_uploads[
                    "id_document"
                ]
            ),
            "driver_license": (
                rider_uploads[
                    "driver_license"
                ]
            ),
            "vehicle_document": (
                rider_uploads[
                    "vehicle_document"
                ]
            ),
        }

        missing = [
            label.replace(
                "_",
                " ",
            ).title()
            for (
                label,
                upload,
            ) in required_uploads.items()
            if not upload
        ]

        if missing:
            messages.error(
                request,
                (
                    f"{', '.join(missing)} "
                    "required for rider KYC."
                ),
            )

            return _render_rider_registration(
                request,
                vehicles,
                rider,
            )

        # ---------------------------------------------------------------------
        # VALIDATE ALL FILES BEFORE CREATING ACCOUNT
        # ---------------------------------------------------------------------

        try:
            _validate_rider_uploads(
                rider_uploads
            )

        except ValidationError as exc:
            _show_validation_errors(
                request,
                exc,
            )

            return _render_rider_registration(
                request,
                vehicles,
                rider,
            )

        _reset_upload_streams(
            rider_uploads
        )

        try:
            with transaction.atomic():
                user = (
                    User.objects.create_user(
                        username=(
                            _unique_rider_username(
                                email
                            )
                        ),
                        email=email,
                        password=password,
                    )
                )

                parts = (
                    full_name.split()
                )

                user.first_name = (
                    parts[0]
                )

                user.last_name = (
                    " ".join(
                        parts[1:]
                    )
                )

                if hasattr(
                    user,
                    "phone_number",
                ):
                    user.phone_number = (
                        phone
                    )

                if hasattr(
                    user,
                    "user_type",
                ):
                    user.user_type = (
                        "customer"
                    )

                user.email_verified = False

                user.save()

                rider = RiderProfile(
                    user=user,
                    rider_type=rider_type,
                    vehicle=vehicle,
                    phone=phone,
                    emergency_phone=(
                        emergency_phone
                    ),
                    about=about,
                    kyc_status=(
                        RiderProfile.KYC_PENDING
                    ),
                    is_online=False,
                    is_available=False,
                    profile_edit_status=(
                        "pending_admin_review"
                    ),
                    profile_edit_requested_at=(
                        timezone.now()
                    ),
                    id_document=(
                        rider_uploads[
                            "id_document"
                        ]
                    ),
                    driver_license=(
                        rider_uploads[
                            "driver_license"
                        ]
                    ),
                    vehicle_document=(
                        rider_uploads[
                            "vehicle_document"
                        ]
                    ),
                    profile_photo=(
                        rider_uploads[
                            "profile_photo"
                        ]
                    ),
                    dashboard_image=(
                        rider_uploads[
                            "dashboard_image"
                        ]
                    ),
                )

                # Run complete model validation before persistence.
                rider.full_clean()

                _reset_upload_streams(
                    rider_uploads
                )

                rider.save()

                credential = (
                    RiderCredential.objects
                    .create(
                        rider=rider
                    )
                )

                credential.set_pin(
                    password
                )

                credential.save(
                    update_fields=[
                        "pin_hash",
                        "updated_at",
                    ]
                )

                RiderWallet.objects.get_or_create(
                    rider=rider
                )

                admin_users = (
                    User.objects
                    .filter(
                        Q(
                            is_staff=True
                        )
                        | Q(
                            is_superuser=True
                        ),
                        is_active=True,
                    )[:20]
                )

                for admin_user in admin_users:
                    Notification.objects.create(
                        user=admin_user,
                        notification_type="shipping",
                        priority=3,
                        title=(
                            "New rider registration"
                        ),
                        message=(
                            f"{full_name} submitted rider KYC "
                            "from the website and is waiting for "
                            "email verification/admin approval."
                        ),
                        metadata={
                            "rider_id": rider.id,
                            "submitted_from": (
                                "web"
                            ),
                        },
                    )

                create_otp(
                    user,
                    user.email,
                    "email",
                )

        except ValidationError as exc:
            _show_validation_errors(
                request,
                exc,
            )

            return _render_rider_registration(
                request,
                vehicles,
                None,
            )

        request.session[
            "pending_email_verification_user_id"
        ] = user.id

        request.session[
            "pending_email_verification_next"
        ] = "deliveries:rider_dashboard"

        messages.success(
            request,
            (
                "Rider registration submitted. "
                "Enter the OTP sent to your email "
                "before entering Rider Center."
            ),
        )

        return redirect(
            "accounts:verify_email"
        )

    # =========================================================================
    # EXISTING AUTHENTICATED RIDER PROFILE UPDATE
    # =========================================================================

    rider, _created = (
        RiderProfile.objects
        .get_or_create(
            user=request.user
        )
    )

    if not rider.can_request_profile_edit:
        next_date = (
            rider.profile_edit_available_at.strftime(
                "%b %d, %Y"
            )
            if rider.profile_edit_available_at
            else "later"
        )

        messages.error(
            request,
            (
                "You can edit your rider profile again from "
                f"{next_date}. Rider profile edits are limited "
                "to once every 14 days."
            ),
        )

        return _render_rider_registration(
            request,
            vehicles,
            rider,
        )

    rider_uploads = {
        "id_document": (
            request.FILES.get(
                "id_document"
            )
        ),
        "driver_license": (
            request.FILES.get(
                "driver_license"
            )
        ),
        "vehicle_document": (
            request.FILES.get(
                "vehicle_document"
            )
        ),
        "profile_photo": (
            request.FILES.get(
                "profile_photo"
            )
        ),
        "dashboard_image": (
            request.FILES.get(
                "dashboard_image"
            )
        ),
    }

    # -------------------------------------------------------------------------
    # VALIDATE FILES BEFORE MUTATING RIDER STATE
    # -------------------------------------------------------------------------

    try:
        _validate_rider_uploads(
            rider_uploads
        )

    except ValidationError as exc:
        _show_validation_errors(
            request,
            exc,
        )

        return _render_rider_registration(
            request,
            vehicles,
            rider,
        )

    _reset_upload_streams(
        rider_uploads
    )

    now = timezone.now()

    try:
        with transaction.atomic():
            rider.profile_edit_pending_data = {
                "first_name": (
                    request.POST.get(
                        "first_name",
                        request.user.first_name,
                    )
                    .strip()
                ),
                "last_name": (
                    request.POST.get(
                        "last_name",
                        request.user.last_name,
                    )
                    .strip()
                ),
                "phone": phone,
                "emergency_phone": (
                    emergency_phone
                ),
                "about": about,
                "rider_type": (
                    rider_type
                ),
                "vehicle_id": (
                    vehicle.id
                ),
                "vehicle_name": (
                    vehicle.name
                ),
                "submitted_from": (
                    "web"
                ),
            }

            rider.profile_edit_status = (
                "pending_admin_review"
            )

            rider.profile_edit_requested_at = (
                now
            )

            rider.profile_edit_available_at = (
                now
                + timedelta(
                    days=14
                )
            )

            rider.kyc_status = (
                RiderProfile.KYC_PENDING
            )

            rider.is_online = False
            rider.is_available = False

            for (
                field_name,
                upload,
            ) in rider_uploads.items():
                if upload:
                    setattr(
                        rider,
                        field_name,
                        upload,
                    )

            rider.full_clean()

            _reset_upload_streams(
                rider_uploads
            )

            rider.save()

    except ValidationError as exc:
        _show_validation_errors(
            request,
            exc,
        )

        return _render_rider_registration(
            request,
            vehicles,
            rider,
        )

    messages.success(
        request,
        (
            "Your rider profile changes have been submitted "
            "for admin verification. You can submit another "
            "edit after 14 days."
        ),
    )

    return redirect(
        "deliveries:rider_dashboard"
    )


# =============================================================================
# RIDER DASHBOARD
# =============================================================================


@login_required
def rider_dashboard(request):
    rider = (
        RiderProfile.objects
        .filter(
            user=request.user
        )
        .select_related(
            "vehicle",
            "zone",
        )
        .first()
    )

    if not rider:
        return redirect(
            "deliveries:rider_register"
        )

    active_statuses = [
        DeliveryRequest.STATUS_ASSIGNED,
        DeliveryRequest.STATUS_ACCEPTED,
        DeliveryRequest.STATUS_ARRIVED_PICKUP,
        DeliveryRequest.STATUS_PICKED_UP,
        DeliveryRequest.STATUS_IN_TRANSIT,
        DeliveryRequest.STATUS_ARRIVED_CUSTOMER,
    ]

    active_deliveries = (
        DeliveryRequest.objects
        .filter(
            rider=rider,
            status__in=active_statuses,
        )
        .select_related(
            "order"
        )
        .prefetch_related(
            "status_history"
        )
        .order_by(
            "-created_at"
        )
    )

    for delivery in active_deliveries:
        delivery.rider_actions = (
            RIDER_STATUS_ACTIONS.get(
                delivery.status,
                [],
            )
        )

    available_deliveries = (
        DeliveryRequest.objects
        .filter(
            rider__isnull=True,
            is_ready_for_rider=True,
            status__in=[
                DeliveryRequest.STATUS_PENDING,
                DeliveryRequest.STATUS_ASSIGNED,
            ],
        )
        .select_related(
            "order"
        )
        .order_by(
            "-created_at"
        )[:30]
    )

    completed_deliveries = (
        DeliveryRequest.objects
        .filter(
            rider=rider,
            status=(
                DeliveryRequest.STATUS_DELIVERED
            ),
        )
        .order_by(
            "-updated_at"
        )[:10]
    )

    new_pickup_count = (
        active_deliveries
        .filter(
            status=(
                DeliveryRequest.STATUS_ASSIGNED
            )
        )
        .count()
    )

    unread_notification_count = (
        Notification.objects
        .filter(
            user=request.user,
            is_read=False,
            is_archived=False,
        )
        .count()
    )

    wallet, _created = (
        RiderWallet.objects
        .get_or_create(
            rider=rider
        )
    )

    completed_total = (
        DeliveryRequest.objects
        .filter(
            rider=rider,
            status=(
                DeliveryRequest.STATUS_DELIVERED
            ),
            delivered_at__isnull=False,
        )
        .aggregate(
            total=Sum(
                "rider_earning"
            )
        )["total"]
        or 0
    )

    paid_total = (
        RiderPayout.objects
        .filter(
            rider=rider,
            status=(
                RiderPayout.STATUS_PAID
            ),
        )
        .aggregate(
            total=Sum(
                "amount"
            )
        )["total"]
        or 0
    )

    approved_total = (
        RiderPayout.objects
        .filter(
            rider=rider,
            status=(
                RiderPayout.STATUS_APPROVED
            ),
        )
        .aggregate(
            total=Sum(
                "amount"
            )
        )["total"]
        or 0
    )

    pending_payout_total = (
        RiderPayout.objects
        .filter(
            rider=rider,
            status=(
                RiderPayout.STATUS_PENDING
            ),
        )
        .aggregate(
            total=Sum(
                "amount"
            )
        )["total"]
        or 0
    )

    pending_earnings = max(
        (
            completed_total
            - paid_total
            - approved_total
            - pending_payout_total
        ),
        0,
    )

    wallet.balance = (
        pending_earnings
        + approved_total
        + pending_payout_total
    )

    wallet.pending_balance = (
        pending_earnings
        + pending_payout_total
    )

    wallet.total_earned = (
        completed_total
    )

    wallet.total_paid_out = (
        paid_total
    )

    wallet.save(
        update_fields=[
            "balance",
            "pending_balance",
            "total_earned",
            "total_paid_out",
            "updated_at",
        ]
    )

    return render(
        request,
        "deliveries/rider_dashboard.html",
        {
            "rider": rider,
            "wallet": wallet,
            "active_deliveries": (
                active_deliveries
            ),
            "available_deliveries": (
                available_deliveries
            ),
            "completed_deliveries": (
                completed_deliveries
            ),
            "assigned_deliveries_count": (
                active_deliveries.count()
            ),
            "new_pickup_count": (
                new_pickup_count
            ),
            "delivery_inbox_count": (
                new_pickup_count
            ),
            "unread_notification_count": (
                unread_notification_count
            ),
        },
    )


# =============================================================================
# RIDER ONLINE / OFFLINE
# =============================================================================


@login_required
@require_POST
def rider_go_online(request):
    rider = get_object_or_404(
        RiderProfile,
        user=request.user,
    )

    if (
        rider.kyc_status
        != RiderProfile.KYC_APPROVED
        or rider.is_suspended
    ):
        messages.error(
            request,
            (
                "Admin must approve your rider profile "
                "before you can go online."
            ),
        )

    else:
        rider.is_online = True
        rider.is_available = True

        rider.save(
            update_fields=[
                "is_online",
                "is_available",
                "updated_at",
            ]
        )

        messages.success(
            request,
            (
                "You are now online "
                "for deliveries."
            ),
        )

    return redirect(
        "deliveries:rider_dashboard"
    )


@login_required
@require_POST
def rider_go_offline(request):
    rider = get_object_or_404(
        RiderProfile,
        user=request.user,
    )

    rider.is_online = False
    rider.is_available = False

    rider.save(
        update_fields=[
            "is_online",
            "is_available",
            "updated_at",
        ]
    )

    messages.success(
        request,
        "You are now offline.",
    )

    return redirect(
        "deliveries:rider_dashboard"
    )


# =============================================================================
# ACCEPT DELIVERY
# =============================================================================


@login_required
@require_POST
def rider_accept_delivery(
    request,
    delivery_id,
):
    rider = get_object_or_404(
        RiderProfile,
        user=request.user,
    )

    delivery = get_object_or_404(
        DeliveryRequest,
        id=delivery_id,
    )

    try:
        accept_delivery(
            delivery,
            rider,
        )

        try:
            from order_robot.services import (
                sync_from_live_delivery,
            )

            sync_from_live_delivery(
                delivery
            )

        except Exception:
            pass

        messages.success(
            request,
            (
                f"Delivery {delivery.tracking_code} "
                "accepted."
            ),
        )

    except ValueError as exc:
        messages.error(
            request,
            str(exc),
        )

    return redirect(
        "deliveries:rider_dashboard"
    )


# =============================================================================
# RIDER STATUS UPDATE + PROOF OF DELIVERY
# =============================================================================


@login_required
@require_POST
def rider_update_status(
    request,
    delivery_id,
):
    rider = get_object_or_404(
        RiderProfile,
        user=request.user,
    )

    delivery = get_object_or_404(
        DeliveryRequest.objects
        .select_related(
            "rider",
            "legacy_delivery",
            "order",
        ),
        id=delivery_id,
        rider=rider,
    )

    requested_status = (
        request.POST.get(
            "status"
        )
    )

    note = (
        request.POST.get(
            "note",
            "",
        )
        .strip()
    )

    latitude = (
        request.POST.get(
            "latitude"
        )
        or None
    )

    longitude = (
        request.POST.get(
            "longitude"
        )
        or None
    )

    proof_note = (
        request.POST.get(
            "proof_note",
            "",
        )
        .strip()
    )

    failed_reason = (
        request.POST.get(
            "failed_reason",
            "",
        )
        .strip()
    )

    uploaded_proof = (
        request.FILES.get(
            "proof_of_delivery"
        )
    )

    # -------------------------------------------------------------------------
    # ENFORCE RIDER STATUS TRANSITION WORKFLOW
    # -------------------------------------------------------------------------

    allowed_next_statuses = {
        action[0]
        for action in (
            RIDER_STATUS_ACTIONS.get(
                delivery.status,
                []
            )
        )
    }

    if (
        requested_status
        not in allowed_next_statuses
    ):
        messages.error(
            request,
            (
                "That delivery status transition is not allowed. "
                f"Current status: {delivery.get_status_display()}."
            ),
        )

        return redirect(
            "deliveries:rider_dashboard"
        )

    # -------------------------------------------------------------------------
    # DELIVERY PROOF IS IMMUTABLE ONCE PRESENT
    # -------------------------------------------------------------------------

    if (
        uploaded_proof
        and delivery.proof_of_delivery
    ):
        messages.error(
            request,
            (
                "Proof of delivery has already been submitted "
                "and cannot be replaced."
            ),
        )

        return redirect(
            "deliveries:rider_dashboard"
        )

    # -------------------------------------------------------------------------
    # VALIDATE PROOF BEFORE SAVE
    # -------------------------------------------------------------------------

    if uploaded_proof:
        try:
            _validate_delivery_proof(
                uploaded_proof
            )

        except ValidationError as exc:
            _show_validation_errors(
                request,
                exc,
            )

            return redirect(
                "deliveries:rider_dashboard"
            )

        try:
            uploaded_proof.seek(0)

        except Exception:
            pass

    try:
        with transaction.atomic():
            update_fields = []

            if uploaded_proof:
                delivery.proof_of_delivery = (
                    uploaded_proof
                )

                update_fields.append(
                    "proof_of_delivery"
                )

            if proof_note:
                delivery.proof_note = (
                    proof_note
                )

                update_fields.append(
                    "proof_note"
                )

            if failed_reason:
                delivery.failed_reason = (
                    failed_reason
                )

                update_fields.append(
                    "failed_reason"
                )

            if update_fields:
                update_fields.append(
                    "updated_at"
                )

                delivery.save(
                    update_fields=(
                        update_fields
                    )
                )

            delivery.set_status(
                requested_status,
                actor=request.user,
                note=note,
                latitude=latitude,
                longitude=longitude,
            )

    except ValueError as exc:
        messages.error(
            request,
            str(exc),
        )

        return redirect(
            "deliveries:rider_dashboard"
        )

    try:
        from order_robot.services import (
            sync_from_live_delivery,
        )

        sync_from_live_delivery(
            delivery
        )

    except Exception:
        pass

    messages.success(
        request,
        (
            "Delivery status updated to "
            f"{delivery.get_status_display()}."
        ),
    )

    return redirect(
        "deliveries:rider_dashboard"
    )


# =============================================================================
# RIDER CURRENT LOCATION
# =============================================================================


@login_required
@require_POST
def api_rider_current_location(
    request,
):
    rider = get_object_or_404(
        RiderProfile,
        user=request.user,
    )

    data = (
        _json_body(
            request
        )
        or request.POST
    )

    try:
        update_rider_current_location(
            rider,
            data.get(
                "latitude"
            ),
            data.get(
                "longitude"
            ),
        )

    except ValueError as exc:
        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )

    return JsonResponse(
        {
            "success": True,
            "latitude": str(
                rider.current_latitude
            ),
            "longitude": str(
                rider.current_longitude
            ),
            "last_location_at": (
                rider.last_location_at.isoformat()
                if rider.last_location_at
                else ""
            ),
        }
    )


# =============================================================================
# DELIVERY LOCATION PING
# =============================================================================


@login_required
@require_POST
def api_rider_location(
    request,
    delivery_id,
):
    rider = get_object_or_404(
        RiderProfile,
        user=request.user,
    )

    delivery = get_object_or_404(
        DeliveryRequest,
        id=delivery_id,
        rider=rider,
    )

    data = (
        _json_body(
            request
        )
        or request.POST
    )

    try:
        ping = update_rider_location(
            delivery,
            rider,
            data.get(
                "latitude"
            ),
            data.get(
                "longitude"
            ),
            heading=data.get(
                "heading"
            ),
            speed_kmph=data.get(
                "speed_kmph"
            ),
            accuracy_meters=data.get(
                "accuracy_meters"
            ),
        )

    except ValueError as exc:
        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )

    return JsonResponse(
        {
            "success": True,
            "latitude": str(
                ping.latitude
            ),
            "longitude": str(
                ping.longitude
            ),
            "created_at": (
                ping.created_at.isoformat()
            ),
        }
    )


# =============================================================================
# ADMIN DELIVERY LOCATION API
# =============================================================================


@staff_member_required
@require_GET
def api_admin_delivery_location(
    request,
    delivery_id,
):
    delivery = get_object_or_404(
        DeliveryRequest.objects
        .select_related(
            "rider__user"
        )
        .prefetch_related(
            "location_pings"
        ),
        id=delivery_id,
    )

    latest = (
        delivery.latest_location
    )

    rider_latitude = (
        latest.latitude
        if latest
        else getattr(
            delivery.rider,
            "current_latitude",
            None,
        )
    )

    rider_longitude = (
        latest.longitude
        if latest
        else getattr(
            delivery.rider,
            "current_longitude",
            None,
        )
    )

    return JsonResponse(
        {
            "success": True,
            "tracking_code": (
                delivery.tracking_code
            ),
            "status": (
                delivery.status
            ),
            "status_display": (
                delivery.get_status_display()
            ),
            "pickup": {
                "label": (
                    delivery.pickup_name
                    or "Vendor pickup"
                ),
                "address": (
                    delivery.pickup_address
                ),
                "latitude": str(
                    delivery.pickup_latitude
                    or ""
                ),
                "longitude": str(
                    delivery.pickup_longitude
                    or ""
                ),
            },
            "dropoff": {
                "label": (
                    delivery.dropoff_name
                    or "Customer drop-off"
                ),
                "address": (
                    delivery.dropoff_address
                ),
                "latitude": str(
                    delivery.dropoff_latitude
                    or ""
                ),
                "longitude": str(
                    delivery.dropoff_longitude
                    or ""
                ),
            },
            "rider": {
                "name": str(
                    delivery.rider
                    or ""
                ),
                "phone": (
                    getattr(
                        delivery.rider,
                        "phone",
                        "",
                    )
                    if delivery.rider_id
                    else ""
                ),
                "latitude": str(
                    rider_latitude
                    or ""
                ),
                "longitude": str(
                    rider_longitude
                    or ""
                ),
                "last_location_at": (
                    latest.created_at.isoformat()
                    if latest
                    else (
                        delivery.rider.last_location_at.isoformat()
                        if (
                            delivery.rider_id
                            and delivery.rider.last_location_at
                        )
                        else ""
                    )
                ),
            },
        }
    )


# =============================================================================
# DELIVERY QUOTE API
# =============================================================================


@require_GET
def api_delivery_quote(request):
    quote = (
        calculate_live_delivery_quote(
            pickup_latitude=(
                request.GET.get(
                    "pickup_latitude"
                )
            ),
            pickup_longitude=(
                request.GET.get(
                    "pickup_longitude"
                )
            ),
            dropoff_latitude=(
                request.GET.get(
                    "dropoff_latitude"
                )
            ),
            dropoff_longitude=(
                request.GET.get(
                    "dropoff_longitude"
                )
            ),
            service_level=(
                request.GET.get(
                    "delivery_service_level"
                )
                or "standard"
            ),
            fallback_fee=(
                request.GET.get(
                    "fallback_fee"
                )
            ),
            package_weight_kg=(
                request.GET.get(
                    "package_weight_kg",
                    0,
                )
            ),
        )
    )

    return JsonResponse(
        {
            "success": True,
            "fee": str(
                quote["fee"]
            ),
            "fee_float": float(
                quote["fee"]
            ),
            "distance_km": str(
                quote[
                    "distance_km"
                ]
            ),
            "estimated_duration_minutes": (
                quote[
                    "estimated_duration_minutes"
                ]
            ),
            "package_weight_kg": str(
                quote[
                    "package_weight_kg"
                ]
            ),
            "base_fare": str(
                quote[
                    "base_fare"
                ]
            ),
            "distance_fee": str(
                quote[
                    "distance_fee"
                ]
            ),
            "time_fee": str(
                quote[
                    "time_fee"
                ]
            ),
            "weight_fee": str(
                quote[
                    "weight_fee"
                ]
            ),
            "service_fee": str(
                quote[
                    "service_fee"
                ]
            ),
            "express_fee": str(
                quote[
                    "express_fee"
                ]
            ),
            "surge_multiplier": str(
                quote[
                    "surge_multiplier"
                ]
            ),
            "pricing_subtotal": str(
                quote[
                    "pricing_subtotal"
                ]
            ),
            "rider_earning": str(
                quote[
                    "rider_earning"
                ]
            ),
            "is_distance_based": (
                quote[
                    "is_distance_based"
                ]
            ),
            "message": (
                quote["message"]
            ),
        }
    )


# =============================================================================
# CUSTOMER DELIVERY TRACKING
# =============================================================================


def customer_tracking(
    request,
    tracking_code,
):
    delivery = get_object_or_404(
        DeliveryRequest.objects
        .select_related(
            "order__user",
            "rider__user",
            "requested_vehicle",
        )
        .prefetch_related(
            "status_history",
            "location_pings",
        ),
        tracking_code__iexact=(
            tracking_code
        ),
    )

    email = (
        request.GET.get(
            "email"
        )
        or ""
    ).strip().lower()

    can_view = (
        _user_can_view_delivery(
            request,
            delivery,
        )
    )

    order_user_email = ""

    if (
        delivery.order.user_id
        and delivery.order.user
        and delivery.order.user.email
    ):
        order_user_email = (
            delivery.order.user.email
            .strip()
            .lower()
        )

    if (
        not can_view
        and email
        and order_user_email
        and email == order_user_email
    ):
        can_view = True

    if not can_view:
        return render(
            request,
            (
                "deliveries/"
                "customer_tracking.html"
            ),
            {
                "delivery": delivery,
                "needs_email": True,
                "email": email,
            },
        )

    return render(
        request,
        (
            "deliveries/"
            "customer_tracking.html"
        ),
        {
            "delivery": delivery,
            "needs_email": False,
            "latest_location": (
                delivery.latest_location
            ),
            "history": (
                delivery.status_history.all()
            ),
        },
    )