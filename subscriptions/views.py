import json
import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from arolana_payments.models import PaymentMethod, PaymentStatus, PaymentTransaction
from arolana_payments.services import gateway_is_available, get_gateway_options

from .lifecycle import (
    activate_free_subscription,
    activate_subscription_from_payment,
    cancel_scheduled_change,
    create_subscription_payment,
    get_effective_subscription,
    get_plan_entitlements,
    official_plans,
    request_cancellation,
    schedule_downgrade,
    set_auto_renew,
    sync_account_role_subscription,
    tier_rank,
    undo_cancellation,
)
from .models import SubscriptionHistory, SubscriptionPayment, SubscriptionPlan, VendorSubscription


logger = logging.getLogger(__name__)


SUBSCRIPTION_PURPOSES = ["account_subscription", "vendor_subscription", "provider_subscription"]


def _csrf_check_target(_request):
    """Non-exempt callback used to retain CSRF checks for browser sessions."""


def _session_csrf_failure(request):
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return None
    rejected = CsrfViewMiddleware(lambda _request: None).process_view(
        request,
        _csrf_check_target,
        (),
        {},
    )
    if rejected is None:
        return None
    return JsonResponse(
        {"success": False, "message": "CSRF verification failed. Refresh the page and try again."},
        status=403,
    )


def _subscription_bearer_user(token):
    """Resolve an existing mobile token to its server-owned Django account."""
    if not token:
        return None, ""

    from staff_mobile.models import StaffMobileToken

    staff_session = (
        StaffMobileToken.objects.select_related("user", "rider", "rider__user")
        .filter(token=token, is_active=True)
        .first()
    )
    if staff_session:
        user = staff_session.user or getattr(staff_session.rider, "user", None)
        if user and user.is_active:
            staff_session.last_used_at = timezone.now()
            staff_session.save(update_fields=["last_used_at", "updated_at"])
            return user, f"staff_mobile:{staff_session.role}"
        return None, ""

    from mobile_customers.models import MobileCustomer

    customer = (
        MobileCustomer.objects.select_related("user")
        .filter(api_token=token, is_active=True, user__is_active=True)
        .first()
    )
    if customer:
        return customer.user, "mobile_customer"
    return None, ""


def subscription_api_auth_required(view_func):
    """Allow the web session or either existing trusted mobile token.

    Mobile callers never submit an account id. The account always comes from a
    token record owned by the server. Browser sessions keep normal CSRF checks.
    """

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        authorization = request.headers.get("Authorization", "").strip()
        if authorization:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not token.strip():
                return JsonResponse(
                    {"success": False, "message": "A valid Bearer token is required."},
                    status=401,
                )
            user, source = _subscription_bearer_user(token.strip())
            if not user:
                return JsonResponse(
                    {"success": False, "message": "Login expired or invalid. Sign in again."},
                    status=401,
                )
            request.user = user
            request.subscription_auth_source = source
            return view_func(request, *args, **kwargs)

        if getattr(request.user, "is_authenticated", False):
            csrf_failure = _session_csrf_failure(request)
            if csrf_failure:
                return csrf_failure
            request.subscription_auth_source = "web_session"
            return view_func(request, *args, **kwargs)

        return JsonResponse(
            {"success": False, "message": "Authentication is required."},
            status=401,
        )

    return csrf_exempt(wrapped)


def _request_data(request):
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            return {}
    return request.POST


def _validation_message(error):
    if hasattr(error, "messages"):
        return " ".join(error.messages)
    return str(error)


def _role_context(request):
    requested = (request.GET.get("role") or request.POST.get("role") or "").strip().lower()
    if not requested and request.content_type and "application/json" in request.content_type:
        requested = str(_request_data(request).get("role") or "").strip().lower()
    if requested in {"provider", "installer", "engineer", "service_provider"}:
        return "provider"
    if requested == "manufacturer":
        return "manufacturer"
    if not hasattr(request.user, "vendor_profile") and hasattr(request.user, "service_provider_profile"):
        return "provider"
    return "vendor"


def _plans_redirect(request):
    """Return to the same role-aware plan view after a web action."""
    return redirect(f"{reverse('subscriptions:plans')}?role={_role_context(request)}")


def _plan_payload(plan, effective=None, role_context="vendor"):
    role_entitlements = {
        "vendor": get_plan_entitlements(plan, "vendor"),
        "manufacturer": get_plan_entitlements(plan, "manufacturer"),
        "provider": get_plan_entitlements(plan, "provider"),
    }
    return {
        "id": plan.id,
        "tier": plan.tier_key,
        "name": plan.display_name,
        "description": plan.description,
        "features": plan.get_features_list(),
        "price_monthly": str(plan.price_monthly),
        "price_yearly": str(plan.price_yearly),
        "currency": "NGN",
        "role_entitlements": role_entitlements,
        "entitlements": (
            effective.role_entitlements.get(role_context, {})
            if effective and effective.plan_id == plan.id else role_entitlements.get(role_context, {})
        ),
        "is_current": bool(effective and effective.plan_id == plan.id),
    }


def _usage_payload(user, role_context, effective):
    if role_context == "provider":
        provider = getattr(user, "service_provider_profile", None)
        if not provider:
            return {"projects": {"used": 0, "limit": effective.entitlements.get("max_projects", 0)}}
        try:
            from installers.project_services import ProjectEntitlementService

            project_usage = ProjectEntitlementService(provider).payload()
        except Exception:
            logger.exception("Unable to build provider subscription usage for user %s", user.pk)
            project_usage = {
                "projects_used": provider.portfolio_items.count(),
                "project_limit": effective.entitlements.get("max_projects", 0),
            }
        return {
            "projects": {
                "used": project_usage.get("projects_used", 0),
                "limit": project_usage.get("project_limit", effective.entitlements.get("max_projects", 0)),
                "remaining": project_usage.get("remaining_projects"),
            }
        }

    try:
        from .entitlements import vendor_listing_usage

        used = vendor_listing_usage(user)
    except Exception:
        logger.exception("Unable to build vendor subscription usage for user %s", user.pk)
        used = 0
    limit = effective.entitlements.get("max_products", 0)
    return {
        "products": {
            "used": used,
            "limit": "unlimited" if limit == -1 else limit,
            "remaining": "unlimited" if limit == -1 else max(limit - used, 0),
        }
    }


def _subscription_payload(user, role_context=None):
    role_context = role_context or "vendor"
    effective = get_effective_subscription(user, role_context=role_context)
    plan = SubscriptionPlan.objects.filter(pk=effective.plan_id).first() if effective.plan_id else None
    effective_data = effective.as_dict()
    subscription = {
        "id": effective.subscription_id,
        "subscription_id": effective.subscription_id,
        "account_id": effective.user_id,
        "user_id": effective.user_id,
        "plan_id": effective.plan_id,
        "tier_key": effective.tier,
        "tier": effective.tier,
        "display_name": effective.display_name,
        "role_context": effective.role_context,
        "status": effective.status,
        "payment_state": effective.payment_state,
        "billing_cycle": effective.billing_cycle,
        "currency": effective.currency,
        "current_price": effective.price,
        "price": effective.price,
        "start_date": effective.start_date,
        "expires_at": effective.end_date,
        "end_date": effective.end_date,
        "grace_period_ends_at": effective.grace_period_ends_at,
        "renewal_date": effective.renewal_date,
        "days_remaining": effective.days_remaining,
        "auto_renew": effective.auto_renew,
        "cancel_at_period_end": effective.cancel_at_period_end,
        "pending_change": {
            "plan_id": effective.pending_plan_id,
            "tier_key": effective.pending_tier,
            "change_type": effective.pending_change_type,
            "effective_at": effective.pending_change_effective_at,
        } if effective.pending_plan_id else None,
        "approved_roles": effective.approved_roles,
        "role_entitlements": effective.role_entitlements,
        "entitlements": effective.entitlements,
        "can_receive_serious_jobs": effective.can_receive_serious_jobs,
        "actions": effective.actions,
    }
    return {
        "subscription": subscription,
        "plan": _plan_payload(plan, effective, role_context) if plan else None,
        "entitlements": effective.role_entitlements,
        "effective_entitlements": effective.entitlements,
        "usage": _usage_payload(user, role_context, effective),
        "actions": effective.actions,
        # Compatibility while old app releases still read the original resolver shape.
        "effective_subscription": effective_data,
    }


def _invoice_payload(payment):
    checkout = payment.checkout_data or {}
    return {
        "id": payment.id,
        "reference": payment.reference,
        "gateway_reference": payment.gateway_reference,
        "plan_id": checkout.get("plan_id"),
        "plan_name": checkout.get("plan_name") or checkout.get("tier") or "Subscription",
        "tier": checkout.get("tier") or "subscription",
        "billing_cycle": checkout.get("billing_cycle") or VendorSubscription.BILLING_MONTHLY,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "gateway": payment.gateway,
        "status": payment.status,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
    }


def _owned_subscription_payment(user, reference):
    return PaymentTransaction.objects.filter(
        user=user,
        reference=reference,
        checkout_data__purpose__in=SUBSCRIPTION_PURPOSES,
    ).first()


def _history_payload(event):
    return {
        "id": event.id,
        "event_type": event.event_type,
        "previous_tier": event.previous_plan.tier_key if event.previous_plan else None,
        "new_tier": event.new_plan.tier_key if event.new_plan else None,
        "previous_status": event.previous_status,
        "new_status": event.new_status,
        "source_platform": event.source_platform,
        "payment_reference": event.payment_reference,
        "effective_at": event.effective_at.isoformat() if event.effective_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "metadata": event.metadata or {},
    }


def _limit_feature(value, singular, plural=None):
    plural = plural or f"{singular}s"
    if value == -1:
        return f"Unlimited {plural}"
    return f"{value} {singular if value == 1 else plural}"


def _web_plan_features(plan, role_context):
    entitlements = get_plan_entitlements(plan, role_context)
    if role_context == "provider":
        features = [
            _limit_feature(entitlements.get("max_projects", 0), "portfolio project"),
            _limit_feature(entitlements.get("max_project_media", 0), "project image or media item"),
            _limit_feature(entitlements.get("max_project_videos", 0), "project video"),
            _limit_feature(entitlements.get("project_product_links_limit", 0), "linked product per project", "linked products per project"),
        ]
        featured_slots = entitlements.get("featured_project_slots", 0)
        if featured_slots:
            features.append(_limit_feature(featured_slots, "featured project slot"))
        if entitlements.get("project_analytics_enabled"):
            features.append("Project performance analytics")
        if entitlements.get("project_leads_enabled"):
            features.append("Customer project leads and quote requests")
        if entitlements.get("can_receive_serious_jobs"):
            features.append("Eligible for serious and high-value jobs")
        return features
    return plan.get_features_list()


@login_required
def subscription_plans(request):
    """Show the six shared plans for any signed-in Arolana role."""
    role_context = _role_context(request)
    effective = get_effective_subscription(request.user, role_context=role_context)
    current_subscription = None
    if effective.subscription_id:
        current_subscription = VendorSubscription.objects.filter(pk=effective.subscription_id).select_related("plan", "pending_plan").first()
    plans = official_plans()
    current_rank = tier_rank(effective.tier)
    for plan in plans:
        plan.web_features = _web_plan_features(plan, role_context)
        plan.web_entitlements = get_plan_entitlements(plan, role_context)
        if effective.plan_id == plan.id:
            plan.web_action = "current"
        elif tier_rank(plan) < current_rank:
            plan.web_action = "downgrade"
        elif tier_rank(plan) > current_rank:
            plan.web_action = "upgrade"
        else:
            plan.web_action = "select"
    role_label = {
        "provider": "Service Provider",
        "manufacturer": "Manufacturer",
        "vendor": "Vendor",
    }[role_context]
    return render(request, "subscriptions/plans.html", {
        "plans": plans,
        "current_subscription": current_subscription,
        "effective_subscription": effective.as_dict(),
        "role_context": role_context,
        "role_label": role_label,
        "subscription_benefits_image_url": "/static/images/arolana-vendor-subscription-benefits.png",
        "payment_gateways": get_gateway_options(include_inactive=True),
    })


@require_POST
@login_required
def subscribe(request, plan_id):
    """Start a server-priced checkout or activate the shared Free tier."""
    plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True)
    billing_cycle = (request.POST.get("billing_cycle") or VendorSubscription.BILLING_MONTHLY).lower()
    if billing_cycle not in dict(VendorSubscription.BILLING_CYCLE_CHOICES):
        messages.error(request, "Choose monthly or yearly billing.")
        return _plans_redirect(request)
    selected_price = plan.price_yearly if billing_cycle == VendorSubscription.BILLING_YEARLY else plan.price_monthly
    if selected_price <= 0:
        try:
            activate_free_subscription(request.user, source_platform="web")
        except ValidationError as error:
            messages.error(request, _validation_message(error))
        else:
            messages.success(request, f"Successfully activated {plan.display_name}.")
        return _plans_redirect(request)

    gateway = (request.POST.get("payment_gateway") or PaymentMethod.PAYSTACK).lower()
    is_available, disabled_reason = gateway_is_available(gateway)
    if not is_available:
        messages.error(request, disabled_reason or "Selected payment gateway is not available yet.")
        return _plans_redirect(request)
    try:
        from staff_mobile.views import _hosted_subscription_checkout_url

        payment = create_subscription_payment(
            request.user,
            plan,
            billing_cycle,
            gateway,
            source_platform="web",
            role_context=_role_context(request),
        )
        checkout_url = _hosted_subscription_checkout_url(request, payment)
    except Exception as error:
        messages.error(request, f"Unable to start subscription checkout: {_validation_message(error)}")
        return _plans_redirect(request)
    if not checkout_url:
        payment.mark_failed({"error": "Gateway did not return checkout URL."})
        messages.error(request, "Payment gateway did not return a checkout link. Please try another gateway.")
        return _plans_redirect(request)
    return redirect(checkout_url)


@require_POST
@login_required
def cancel_subscription(request, subscription_id):
    try:
        subscription = request_cancellation(
            request.user,
            subscription_id=subscription_id,
            reason=request.POST.get("reason", ""),
            source_platform="web",
        )
    except ValidationError as error:
        messages.error(request, _validation_message(error))
    else:
        messages.success(request, f"Cancellation scheduled for {subscription.end_date:%d %b %Y}. Your access remains active until then.")
    return _plans_redirect(request)


@require_POST
@login_required
def undo_cancellation_web(request):
    try:
        undo_cancellation(
            request.user,
            subscription_id=request.POST.get("subscription_id"),
            source_platform="web",
        )
    except ValidationError as error:
        messages.error(request, _validation_message(error))
    else:
        messages.success(request, "Your scheduled cancellation was removed.")
    return _plans_redirect(request)


@require_POST
@login_required
def schedule_downgrade_web(request):
    plan = SubscriptionPlan.objects.filter(pk=request.POST.get("plan_id"), is_active=True).first()
    if not plan:
        messages.error(request, "Subscription plan not found.")
        return _plans_redirect(request)
    try:
        subscription = schedule_downgrade(request.user, plan, source_platform="web")
    except ValidationError as error:
        messages.error(request, _validation_message(error))
    else:
        messages.success(
            request,
            f"Downgrade scheduled for {subscription.end_date:%d %b %Y}. Your current access remains active until then.",
        )
    return _plans_redirect(request)


@require_POST
@login_required
def cancel_scheduled_change_web(request):
    try:
        cancel_scheduled_change(request.user, source_platform="web")
    except ValidationError as error:
        messages.error(request, _validation_message(error))
    else:
        messages.success(request, "Your scheduled plan change was removed.")
    return _plans_redirect(request)


@require_POST
@login_required
def set_auto_renew_web(request):
    enabled = str(request.POST.get("enabled", "true")).lower() in {"1", "true", "yes", "on"}
    try:
        set_auto_renew(request.user, enabled=enabled, source_platform="web")
    except ValidationError as error:
        messages.error(request, _validation_message(error))
    else:
        messages.success(request, f"Auto-renewal is now {'enabled' if enabled else 'disabled'}.")
    return _plans_redirect(request)


@require_POST
@login_required
def renew_subscription_web(request):
    effective = get_effective_subscription(request.user, role_context=_role_context(request))
    subscription = VendorSubscription.objects.filter(
        pk=effective.subscription_id,
        vendor=request.user,
    ).select_related("plan").first()
    if not subscription:
        messages.error(request, "No renewable subscription was found.")
        return _plans_redirect(request)
    request.POST = request.POST.copy()
    request.POST["billing_cycle"] = request.POST.get("billing_cycle") or subscription.billing_cycle
    return subscribe(request, subscription.plan_id)


@login_required
def subscription_history(request):
    role_context = _role_context(request)
    effective = get_effective_subscription(request.user, role_context=role_context)
    current_subscription = None
    if effective.subscription_id:
        current_subscription = VendorSubscription.objects.filter(pk=effective.subscription_id).select_related("plan", "pending_plan").first()
    invoices = PaymentTransaction.objects.filter(
        user=request.user,
        checkout_data__purpose__in=SUBSCRIPTION_PURPOSES,
    ).order_by("-created_at")
    subscriptions = VendorSubscription.objects.filter(vendor=request.user).select_related("plan").order_by("-created_at")
    return render(request, "subscriptions/history.html", {
        "vendor_profile": getattr(request.user, "vendor_profile", None),
        "provider_profile": getattr(request.user, "service_provider_profile", None),
        "current_subscription": current_subscription,
        "effective_subscription": effective.as_dict(),
        "invoices": invoices,
        "subscriptions": subscriptions,
    })


@require_GET
@subscription_api_auth_required
def api_plans(request):
    role_context = _role_context(request)
    effective = get_effective_subscription(request.user, role_context=role_context)
    payload = _subscription_payload(request.user, role_context)
    return JsonResponse({
        "success": True,
        "role_context": role_context,
        "plans": [_plan_payload(plan, effective, role_context) for plan in official_plans()],
        "current_subscription": effective.as_dict(),
        "payment_gateways": get_gateway_options(include_inactive=True),
        **payload,
    })


@require_GET
@subscription_api_auth_required
def api_plan_detail(request, plan_id):
    plan = get_object_or_404(SubscriptionPlan, pk=plan_id, is_active=True)
    role_context = _role_context(request)
    effective = get_effective_subscription(request.user, role_context=role_context)
    return JsonResponse({
        "success": True,
        "role_context": role_context,
        "plan": _plan_payload(plan, effective, role_context),
        "current_subscription": effective.as_dict(),
        "payment_gateways": get_gateway_options(include_inactive=True),
    })


@require_GET
@subscription_api_auth_required
def api_current(request):
    role_context = _role_context(request)
    return JsonResponse({
        "success": True,
        **_subscription_payload(request.user, role_context),
    })


@require_POST
@subscription_api_auth_required
def api_checkout(request):
    data = _request_data(request)
    plan = SubscriptionPlan.objects.filter(pk=data.get("plan_id"), is_active=True).first()
    if not plan:
        return JsonResponse({"success": False, "message": "Subscription plan not found."}, status=404)
    billing_cycle = str(data.get("billing_cycle") or VendorSubscription.BILLING_MONTHLY).lower()
    gateway = str(data.get("gateway") or data.get("payment_gateway") or PaymentMethod.PAYSTACK).lower()
    try:
        if billing_cycle not in dict(VendorSubscription.BILLING_CYCLE_CHOICES):
            raise ValidationError("Choose monthly or yearly billing.")
        selected_price = plan.price_yearly if billing_cycle == VendorSubscription.BILLING_YEARLY else plan.price_monthly
        if selected_price <= 0:
            activate_free_subscription(request.user, source_platform="api")
            return JsonResponse({
                "success": True,
                "message": "Free plan activated.",
                "subscription": get_effective_subscription(request.user, _role_context(request)).as_dict(),
            })
        is_available, disabled_reason = gateway_is_available(gateway)
        if not is_available:
            raise ValidationError(disabled_reason or "Selected payment gateway is not available yet.")
        payment = create_subscription_payment(
            request.user,
            plan,
            billing_cycle,
            gateway,
            source_platform="api",
            role_context=_role_context(request),
        )
        from staff_mobile.views import _hosted_subscription_checkout_url

        checkout_url = _hosted_subscription_checkout_url(request, payment)
        if not checkout_url:
            payment.mark_failed({"error": "Gateway did not return checkout URL."})
            raise ValidationError("Payment gateway did not return a checkout link.")
    except ValidationError as error:
        return JsonResponse({"success": False, "message": _validation_message(error)}, status=400)
    except Exception:
        logger.exception("Unable to initialize subscription checkout for user %s", request.user.pk)
        return JsonResponse({"success": False, "message": "Unable to start checkout. Please try again."}, status=502)
    return JsonResponse({
        "success": True,
        "message": "Payment initialized.",
        "payment": _invoice_payload(payment),
        "checkout_url": checkout_url,
    })


@require_GET
@subscription_api_auth_required
def api_payment_result(request, reference):
    payment = _owned_subscription_payment(request.user, reference)
    if not payment:
        return JsonResponse({"success": False, "message": "Subscription payment was not found."}, status=404)
    subscription = None
    if payment.status == PaymentStatus.SUCCESS:
        try:
            subscription = activate_subscription_from_payment(payment, source_platform="api_result")
        except ValidationError as error:
            logger.warning("Subscription result activation rejected for %s: %s", payment.reference, error)
            return JsonResponse({"success": False, "message": _validation_message(error)}, status=400)
    return JsonResponse({
        "success": True,
        "confirmed": payment.status == PaymentStatus.SUCCESS,
        "payment": _invoice_payload(payment),
        "activated_subscription_id": getattr(subscription, "pk", None),
        **_subscription_payload(request.user, _role_context(request)),
    })


@require_POST
@subscription_api_auth_required
def api_verify_payment(request):
    data = _request_data(request)
    reference = str(data.get("reference") or data.get("payment_reference") or "").strip()
    if not reference:
        return JsonResponse({"success": False, "message": "Payment reference is required."}, status=400)
    payment = _owned_subscription_payment(request.user, reference)
    if not payment:
        return JsonResponse({"success": False, "message": "Subscription payment was not found."}, status=404)
    try:
        from arolana_payments.views import _verify_transaction_now

        confirmed, message, _gateway_payload = _verify_transaction_now(payment)
        payment.refresh_from_db()
        subscription = None
        if confirmed or payment.status == PaymentStatus.SUCCESS:
            subscription = activate_subscription_from_payment(payment, source_platform="api_verify")
            confirmed = True
    except ValidationError as error:
        return JsonResponse({"success": False, "message": _validation_message(error)}, status=400)
    except Exception:
        logger.exception("Unable to verify subscription payment %s", payment.reference)
        return JsonResponse({"success": False, "message": "Payment verification is temporarily unavailable."}, status=502)
    return JsonResponse({
        "success": True,
        "confirmed": confirmed,
        "message": message,
        "payment": _invoice_payload(payment),
        "activated_subscription_id": getattr(subscription, "pk", None),
        **_subscription_payload(request.user, _role_context(request)),
    })


@require_POST
@subscription_api_auth_required
def api_renew(request):
    data = _request_data(request)
    effective = get_effective_subscription(request.user, role_context=_role_context(request))
    plan = SubscriptionPlan.objects.filter(pk=effective.plan_id, is_active=True).first()
    if not plan:
        return JsonResponse({"success": False, "message": "No renewable plan was found."}, status=404)
    billing_cycle = str(data.get("billing_cycle") or effective.billing_cycle or VendorSubscription.BILLING_MONTHLY).lower()
    gateway = str(data.get("gateway") or data.get("payment_gateway") or PaymentMethod.PAYSTACK).lower()
    try:
        if billing_cycle not in dict(VendorSubscription.BILLING_CYCLE_CHOICES):
            raise ValidationError("Choose monthly or yearly billing.")
        selected_price = plan.price_yearly if billing_cycle == VendorSubscription.BILLING_YEARLY else plan.price_monthly
        if selected_price <= 0:
            raise ValidationError("The Free plan does not require renewal.")
        is_available, disabled_reason = gateway_is_available(gateway)
        if not is_available:
            raise ValidationError(disabled_reason or "Selected payment gateway is not available yet.")
        payment = create_subscription_payment(
            request.user,
            plan,
            billing_cycle,
            gateway,
            source_platform="api_renew",
            role_context=_role_context(request),
        )
        from staff_mobile.views import _hosted_subscription_checkout_url

        checkout_url = _hosted_subscription_checkout_url(request, payment)
        if not checkout_url:
            payment.mark_failed({"error": "Gateway did not return checkout URL."})
            raise ValidationError("Payment gateway did not return a checkout link.")
    except ValidationError as error:
        return JsonResponse({"success": False, "message": _validation_message(error)}, status=400)
    except Exception:
        logger.exception("Unable to initialize renewal checkout for user %s", request.user.pk)
        return JsonResponse({"success": False, "message": "Unable to start renewal. Please try again."}, status=502)
    return JsonResponse({
        "success": True,
        "message": "Renewal payment initialized.",
        "payment": _invoice_payload(payment),
        "checkout_url": checkout_url,
    })


@require_POST
@subscription_api_auth_required
def api_reconcile(request):
    sync_account_role_subscription(request.user)
    return JsonResponse({
        "success": True,
        "message": "Account subscription roles synchronized.",
        **_subscription_payload(request.user, _role_context(request)),
    })


@require_POST
@subscription_api_auth_required
def api_cancel(request):
    data = _request_data(request)
    try:
        subscription = request_cancellation(
            request.user,
            subscription_id=data.get("subscription_id"),
            reason=data.get("reason", ""),
            source_platform="api",
        )
    except ValidationError as error:
        return JsonResponse({"success": False, "message": _validation_message(error)}, status=400)
    return JsonResponse({
        "success": True,
        "message": f"Cancellation scheduled for {subscription.end_date:%d %b %Y}.",
        "subscription": get_effective_subscription(request.user, _role_context(request)).as_dict(),
    })


@require_POST
@subscription_api_auth_required
def api_undo_cancellation(request):
    data = _request_data(request)
    try:
        undo_cancellation(request.user, subscription_id=data.get("subscription_id"), source_platform="api")
    except ValidationError as error:
        return JsonResponse({"success": False, "message": _validation_message(error)}, status=400)
    return JsonResponse({"success": True, "message": "Cancellation removed.", "subscription": get_effective_subscription(request.user, _role_context(request)).as_dict()})


@require_POST
@subscription_api_auth_required
def api_downgrade(request):
    data = _request_data(request)
    plan = SubscriptionPlan.objects.filter(pk=data.get("plan_id"), is_active=True).first()
    if not plan:
        return JsonResponse({"success": False, "message": "Subscription plan not found."}, status=404)
    try:
        schedule_downgrade(request.user, plan, source_platform="api")
    except ValidationError as error:
        return JsonResponse({"success": False, "message": _validation_message(error)}, status=400)
    return JsonResponse({"success": True, "message": "Downgrade scheduled for the next renewal date.", "subscription": get_effective_subscription(request.user, _role_context(request)).as_dict()})


@require_POST
@subscription_api_auth_required
def api_cancel_scheduled_change(request):
    try:
        cancel_scheduled_change(request.user, source_platform="api")
    except ValidationError as error:
        return JsonResponse({"success": False, "message": _validation_message(error)}, status=400)
    return JsonResponse({"success": True, "message": "Scheduled plan change removed.", "subscription": get_effective_subscription(request.user, _role_context(request)).as_dict()})


@require_POST
@subscription_api_auth_required
def api_auto_renew(request):
    data = _request_data(request)
    enabled = str(data.get("enabled", "true")).lower() in {"1", "true", "yes", "on"}
    try:
        set_auto_renew(request.user, enabled=enabled, source_platform="api")
    except ValidationError as error:
        return JsonResponse({"success": False, "message": _validation_message(error)}, status=400)
    return JsonResponse({"success": True, "message": "Auto-renewal preference updated.", "subscription": get_effective_subscription(request.user, _role_context(request)).as_dict()})


@require_GET
@subscription_api_auth_required
def api_history(request):
    events = SubscriptionHistory.objects.filter(user=request.user).select_related("previous_plan", "new_plan")[:100]
    payments = PaymentTransaction.objects.filter(user=request.user, checkout_data__purpose__in=SUBSCRIPTION_PURPOSES).order_by("-created_at")[:100]
    payload = _subscription_payload(request.user, _role_context(request))
    return JsonResponse({
        "success": True,
        "history": [_history_payload(event) for event in events],
        "payments": [_invoice_payload(payment) for payment in payments],
        **payload,
    })
