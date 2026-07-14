"""Shared Arolana account subscription lifecycle and entitlement resolver."""

from dataclasses import asdict, dataclass
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    SubscriptionHistory,
    SubscriptionPayment,
    SubscriptionPlan,
    SubscriptionReminderLog,
    VendorSubscription,
    apply_vendor_subscription_benefits,
    get_tier_limits,
    normalize_subscription_tier,
)
from .notifications import dispatch_subscription_notification


OFFICIAL_TIER_ORDER = ("free", "basic", "plus", "pro", "special", "enterprise")
SERIOUS_JOB_TIERS = {"pro", "special", "enterprise"}
ACTIVE_ACCESS_STATUSES = {
    VendorSubscription.STATUS_ACTIVE,
    VendorSubscription.STATUS_TRIAL,
    VendorSubscription.STATUS_PAST_DUE,
    VendorSubscription.STATUS_GRACE_PERIOD,
}

PROVIDER_ENTITLEMENT_DEFAULTS = {
    "free": {
        "max_projects": 1,
        "max_project_media": 5,
        "max_project_videos": 1,
        "max_local_video_uploads": 0,
        "max_video_size_mb": 0,
        "project_analytics_enabled": False,
        "project_leads_enabled": True,
        "featured_project_slots": 0,
        "project_product_links_limit": 2,
        "can_receive_serious_jobs": False,
    },
    "basic": {
        "max_projects": 5,
        "max_project_media": 8,
        "max_project_videos": 2,
        "max_local_video_uploads": 1,
        "max_video_size_mb": 50,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": 0,
        "project_product_links_limit": 5,
        "can_receive_serious_jobs": False,
    },
    "plus": {
        "max_projects": 20,
        "max_project_media": 15,
        "max_project_videos": 5,
        "max_local_video_uploads": 5,
        "max_video_size_mb": 150,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": 2,
        "project_product_links_limit": 15,
        "can_receive_serious_jobs": False,
    },
    "pro": {
        "max_projects": 100,
        "max_project_media": 30,
        "max_project_videos": 15,
        "max_local_video_uploads": 20,
        "max_video_size_mb": 300,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": 8,
        "project_product_links_limit": 30,
        "can_receive_serious_jobs": True,
    },
    "special": {
        "max_projects": 300,
        "max_project_media": 45,
        "max_project_videos": 30,
        "max_local_video_uploads": 40,
        "max_video_size_mb": 400,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": 20,
        "project_product_links_limit": 50,
        "can_receive_serious_jobs": True,
    },
    "enterprise": {
        "max_projects": -1,
        "max_project_media": 60,
        "max_project_videos": -1,
        "max_local_video_uploads": -1,
        "max_video_size_mb": 500,
        "project_analytics_enabled": True,
        "project_leads_enabled": True,
        "featured_project_slots": -1,
        "project_product_links_limit": -1,
        "can_receive_serious_jobs": True,
    },
}


def account_user(value):
    if value is None:
        return None
    if hasattr(value, "is_authenticated") and hasattr(value, "email"):
        return value
    return getattr(value, "user", None) or getattr(value, "vendor", None)


def calculate_period_end(start, billing_cycle):
    if billing_cycle == VendorSubscription.BILLING_YEARLY:
        return start + relativedelta(years=1)
    if billing_cycle != VendorSubscription.BILLING_MONTHLY:
        raise ValidationError("Choose monthly or yearly billing.")
    return start + relativedelta(months=1)


def plan_price(plan, billing_cycle):
    if billing_cycle == VendorSubscription.BILLING_YEARLY:
        return Decimal(plan.price_yearly)
    if billing_cycle == VendorSubscription.BILLING_MONTHLY:
        return Decimal(plan.price_monthly)
    raise ValidationError("Choose monthly or yearly billing.")


def tier_rank(value):
    tier = normalize_subscription_tier(getattr(value, "tier_key", None) or getattr(value, "name", None) or value)
    return OFFICIAL_TIER_ORDER.index(tier)


def official_plans():
    """Return one active database plan for each official tier, in product order."""
    found = {}
    for plan in SubscriptionPlan.objects.filter(is_active=True).order_by("order", "price_monthly", "id"):
        found.setdefault(plan.tier_key, plan)
    return [found[tier] for tier in OFFICIAL_TIER_ORDER if tier in found]


def _active_plan_for_tier(tier):
    """Resolve a computed tier key without pretending it is a database field."""
    normalized = normalize_subscription_tier(tier)
    for plan in SubscriptionPlan.objects.filter(is_active=True).order_by("order", "price_monthly", "id"):
        if plan.tier_key == normalized:
            return plan
    return None


def _role_entitlements(plan, tier, role_context):
    role_context = (role_context or "vendor").strip().lower()
    if role_context in {"provider", "installer", "engineer", "service_provider"}:
        defaults = dict(PROVIDER_ENTITLEMENT_DEFAULTS[tier])
        role_key = "provider"
    else:
        defaults = get_tier_limits(tier)
        role_key = "manufacturer" if role_context == "manufacturer" else "vendor"
    configured = plan.role_entitlements if plan and isinstance(plan.role_entitlements, dict) else {}
    overrides = configured.get(role_key, {})
    if isinstance(overrides, dict):
        defaults.update(overrides)
    return defaults


def get_plan_entitlements(plan, role_context="vendor"):
    """Return role entitlements for a catalog plan without activating it."""
    tier = normalize_subscription_tier(
        getattr(plan, "tier_key", None) or getattr(plan, "name", None) or plan
    )
    return _role_entitlements(plan, tier, role_context)


def _current_subscription(user, now=None, lock=False):
    now = now or timezone.now()
    queryset = VendorSubscription.objects.filter(vendor=user, is_active=True).select_related("plan")
    if lock:
        queryset = queryset.select_for_update()
    for subscription in queryset.order_by("-end_date", "-created_at"):
        if subscription.status in {VendorSubscription.STATUS_ACTIVE, VendorSubscription.STATUS_TRIAL}:
            if subscription.end_date > now:
                return subscription
        elif subscription.status in {VendorSubscription.STATUS_PAST_DUE, VendorSubscription.STATUS_GRACE_PERIOD}:
            if subscription.grace_period_ends_at and subscription.grace_period_ends_at > now:
                return subscription
    return None


def _legacy_provider_subscription(user, now=None):
    """Read an official provider mirror only until the shared row is backfilled.

    Legacy provider fields are never allowed to override shared subscription
    history. They remain a temporary compatibility source for approved accounts
    created before account-level subscriptions were introduced.
    """
    now = now or timezone.now()
    if not user or not getattr(user, "pk", None):
        return None
    if VendorSubscription.objects.filter(vendor=user).exists():
        return None
    provider = getattr(user, "service_provider_profile", None)
    if not provider or provider.subscription_status not in {"active", "trial"}:
        return None
    if provider.subscription_expires_at and provider.subscription_expires_at <= now:
        return None
    tier = normalize_subscription_tier(provider.subscription_plan)
    if tier not in OFFICIAL_TIER_ORDER:
        return None
    plan = _active_plan_for_tier(tier)
    return provider, tier, plan


@dataclass(frozen=True)
class EffectiveSubscription:
    user_id: int | None
    subscription_id: int | None
    plan_id: int | None
    tier: str
    display_name: str
    role_context: str
    status: str
    payment_state: str
    billing_cycle: str
    currency: str
    price: str
    start_date: str | None
    end_date: str | None
    grace_period_ends_at: str | None
    renewal_date: str | None
    days_remaining: int | None
    auto_renew: bool
    cancel_at_period_end: bool
    pending_plan_id: int | None
    pending_tier: str | None
    pending_change_type: str
    pending_change_effective_at: str | None
    approved_roles: list
    role_entitlements: dict
    entitlements: dict
    can_receive_serious_jobs: bool
    actions: dict

    def as_dict(self):
        return asdict(self)


def get_effective_subscription(user_or_business, role_context=None, now=None):
    """Return the single effective account plan plus role-aware entitlements."""
    now = now or timezone.now()
    user = account_user(user_or_business)
    role_context = (role_context or "vendor").strip().lower()
    current = _current_subscription(user, now=now) if user and getattr(user, "pk", None) else None
    legacy_provider = None
    if not current and role_context in {"provider", "installer", "engineer", "service_provider"}:
        legacy_provider = _legacy_provider_subscription(user, now=now)
    if current:
        plan = current.plan
        tier = normalize_subscription_tier(plan.name)
    elif legacy_provider:
        _, tier, plan = legacy_provider
    else:
        plan = _active_plan_for_tier("free")
        tier = "free"
    entitlements = _role_entitlements(plan, tier, role_context)
    status = (
        current.status if current else
        legacy_provider[0].subscription_status if legacy_provider else
        VendorSubscription.STATUS_ACTIVE
    )
    payment_state = current.payment_state if current else "legacy_mirror" if legacy_provider else "free"
    billing_cycle = current.billing_cycle if current else VendorSubscription.BILLING_MONTHLY
    price = plan_price(plan, billing_cycle) if plan else Decimal("0.00")
    days_remaining = None
    if current:
        effective_end = current.grace_period_ends_at if status in {
            VendorSubscription.STATUS_PAST_DUE,
            VendorSubscription.STATUS_GRACE_PERIOD,
        } and current.grace_period_ends_at else current.end_date
        days_remaining = max((effective_end.date() - now.date()).days, 0)
    elif legacy_provider and legacy_provider[0].subscription_expires_at:
        days_remaining = max(
            (legacy_provider[0].subscription_expires_at.date() - now.date()).days,
            0,
        )

    serious_jobs = False
    if role_context in {"provider", "installer", "engineer", "service_provider"} and user:
        provider = getattr(user, "service_provider_profile", None)
        if provider:
            serious_jobs = bool(
                tier in SERIOUS_JOB_TIERS
                and status in {VendorSubscription.STATUS_ACTIVE, VendorSubscription.STATUS_TRIAL}
                and provider.approval_allows_dashboard
                and provider.is_active
                and (
                    provider.kyc_status == provider.KYC_APPROVED
                    or provider.allow_limited_jobs_without_kyc
                )
                and entitlements.get("can_receive_serious_jobs", False)
            )

    approved_roles = []
    if user:
        vendor_profile = getattr(user, "vendor_profile", None)
        if vendor_profile:
            approved_roles.append("vendor")
        provider_profile = getattr(user, "service_provider_profile", None)
        if provider_profile and provider_profile.approval_allows_dashboard:
            approved_roles.append("provider")
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            approved_roles.append("admin")
        if getattr(user, "rider_profile", None):
            approved_roles.append("rider")

    role_entitlements = {
        "vendor": _role_entitlements(plan, tier, "vendor"),
        "manufacturer": _role_entitlements(plan, tier, "manufacturer"),
        "provider": _role_entitlements(plan, tier, "provider"),
    }
    pending_plan = current.pending_plan if current else None
    actions = {
        "can_renew": bool(current and current.status in ACTIVE_ACCESS_STATUSES),
        "can_cancel": bool(current and not current.cancel_at_period_end and tier != "free"),
        "can_undo_cancellation": bool(current and current.cancel_at_period_end and current.end_date > now),
        "can_cancel_scheduled_change": bool(current and current.pending_plan_id),
        "can_upgrade": tier != "enterprise",
        "can_downgrade": tier != "free",
    }

    return EffectiveSubscription(
        user_id=getattr(user, "pk", None),
        subscription_id=getattr(current, "pk", None),
        plan_id=getattr(plan, "pk", None),
        tier=tier,
        display_name=getattr(plan, "display_name", "") or tier.title(),
        role_context=role_context,
        status=status,
        payment_state=payment_state,
        billing_cycle=billing_cycle,
        currency=current.currency if current else "NGN",
        price=str(price),
        start_date=current.start_date.isoformat() if current else None,
        end_date=(
            current.end_date.isoformat() if current else
            legacy_provider[0].subscription_expires_at.isoformat()
            if legacy_provider and legacy_provider[0].subscription_expires_at else None
        ),
        grace_period_ends_at=current.grace_period_ends_at.isoformat() if current and current.grace_period_ends_at else None,
        renewal_date=current.end_date.isoformat() if current and current.auto_renew and not current.cancel_at_period_end else None,
        days_remaining=days_remaining,
        auto_renew=bool(current and current.auto_renew),
        cancel_at_period_end=bool(current and current.cancel_at_period_end),
        pending_plan_id=getattr(pending_plan, "pk", None),
        pending_tier=pending_plan.tier_key if pending_plan else None,
        pending_change_type=current.pending_change_type if current else "",
        pending_change_effective_at=(
            current.pending_change_effective_at.isoformat()
            if current and current.pending_change_effective_at else None
        ),
        approved_roles=approved_roles,
        role_entitlements=role_entitlements,
        entitlements=entitlements,
        can_receive_serious_jobs=serious_jobs,
        actions=actions,
    )


def _history(user, event_type, subscription=None, previous_plan=None, new_plan=None, previous_status="", new_status="", actor=None, source_platform="", payment_reference="", metadata=None):
    return SubscriptionHistory.objects.create(
        user=user,
        subscription=subscription,
        event_type=event_type,
        previous_plan=previous_plan,
        new_plan=new_plan,
        previous_status=previous_status,
        new_status=new_status,
        actor=actor,
        source_platform=source_platform,
        payment_reference=payment_reference,
        metadata=metadata or {},
    )


def sync_account_role_subscription(user, subscription=None):
    """Mirror the shared subscription into legacy role fields during migration."""
    # Callers such as admin deletion and lifecycle expiry intentionally omit the
    # record. Resolve again so another valid account subscription is not erased
    # from the legacy role mirrors. An implicit Free fallback remains available
    # through get_effective_subscription, but is not presented as a paid/current
    # subscription unless an actual Free subscription record exists.
    subscription = subscription if subscription and subscription.is_current else _current_subscription(user)
    effective = get_effective_subscription(user, role_context="vendor")
    has_current_record = bool(subscription)
    vendor_profile = getattr(user, "vendor_profile", None)
    if vendor_profile:
        vendor_profile.subscription_active = has_current_record
        vendor_profile.subscription_started_at = subscription.start_date if subscription else None
        vendor_profile.subscription_expires_at = subscription.end_date if subscription else None
        vendor_profile.subscription_expiry = subscription.end_date if subscription else None
        vendor_profile.save(update_fields=[
            "subscription_active",
            "subscription_started_at",
            "subscription_expires_at",
            "subscription_expiry",
            "updated_at",
        ])
        apply_vendor_subscription_benefits(vendor_profile, effective.tier)

    provider = getattr(user, "service_provider_profile", None)
    if provider:
        provider.subscription_plan = effective.tier
        provider.subscription_status = (
            "trial" if has_current_record and effective.status == VendorSubscription.STATUS_TRIAL else
            "active" if has_current_record and effective.status in {
                VendorSubscription.STATUS_ACTIVE,
                VendorSubscription.STATUS_GRACE_PERIOD,
                VendorSubscription.STATUS_PAST_DUE,
            } else "inactive"
        )
        provider.subscription_expires_at = subscription.end_date if subscription else None
        provider.save(update_fields=[
            "subscription_plan",
            "subscription_status",
            "subscription_expires_at",
            "updated_at",
        ])
    return effective


def _notify_account(user, title, message, metadata=None, priority=3):
    return dispatch_subscription_notification(
        user,
        title,
        message,
        metadata=metadata,
        priority=priority,
    )


@transaction.atomic
def activate_free_subscription(user_or_business, source_platform="web", actor=None):
    user = account_user(user_or_business)
    if not user or not user.pk:
        raise ValidationError("A signed-in Arolana account is required.")
    current = _current_subscription(user, lock=True)
    if current and normalize_subscription_tier(current.plan.name) != "free":
        return current
    plan = SubscriptionPlan.objects.select_for_update().filter(name__iexact="free", is_active=True).first()
    if not plan:
        raise ValidationError("The Free subscription plan is not configured.")
    now = timezone.now()
    if (
        current
        and current.plan_id == plan.id
        and current.status == VendorSubscription.STATUS_ACTIVE
        and current.payment_state == "free"
        and not current.cancel_at_period_end
        and current.end_date > now
    ):
        # Role profiles can be added after account creation, so keep their
        # compatibility mirrors synchronized without duplicating audit events.
        transaction.on_commit(lambda: sync_account_role_subscription(user, current))
        return current
    VendorSubscription.objects.filter(vendor=user, is_active=True).exclude(pk=getattr(current, "pk", None)).update(
        is_active=False,
        status=VendorSubscription.STATUS_INACTIVE,
    )
    if current:
        subscription = current
        subscription.plan = plan
        subscription.status = VendorSubscription.STATUS_ACTIVE
        subscription.payment_state = "free"
        subscription.is_active = True
        subscription.cancel_at_period_end = False
        subscription.end_date = max(subscription.end_date, now + relativedelta(years=10))
        subscription.save()
    else:
        subscription = VendorSubscription.objects.create(
            vendor=user,
            plan=plan,
            start_date=now,
            end_date=now + relativedelta(years=10),
            status=VendorSubscription.STATUS_ACTIVE,
            payment_state="free",
            billing_cycle=VendorSubscription.BILLING_MONTHLY,
            currency="NGN",
            is_active=True,
            auto_renew=True,
            payment_method="free",
            source_platform=source_platform,
        )
    _history(
        user,
        "free_plan_activated",
        subscription=subscription,
        new_plan=plan,
        new_status=subscription.status,
        actor=actor,
        source_platform=source_platform,
    )
    transaction.on_commit(lambda: sync_account_role_subscription(user, subscription))
    return subscription


@transaction.atomic
def activate_subscription_from_payment(payment, source_platform="", actor=None):
    """Idempotently activate only a successful, server-matched subscription payment."""
    from arolana_payments.models import PaymentStatus, PaymentTransaction

    payment = PaymentTransaction.objects.select_for_update().select_related("user").get(pk=payment.pk)
    checkout = payment.checkout_data or {}
    if checkout.get("purpose") not in {"account_subscription", "vendor_subscription", "provider_subscription"}:
        return None
    if payment.status != PaymentStatus.SUCCESS:
        raise ValidationError("Subscription payment has not been verified.")
    plan = SubscriptionPlan.objects.select_for_update().filter(pk=checkout.get("plan_id"), is_active=True).first()
    if not plan:
        raise ValidationError("The subscription plan attached to this payment is unavailable.")
    billing_cycle = checkout.get("billing_cycle") or VendorSubscription.BILLING_MONTHLY
    expected_amount = plan_price(plan, billing_cycle)
    expected_currency = "NGN"
    if Decimal(payment.amount) != expected_amount:
        raise ValidationError("Subscription payment amount does not match the selected plan.")
    if (payment.currency or "").upper() != expected_currency:
        raise ValidationError("Subscription payment currency does not match the selected plan.")
    if checkout.get("user_id") and int(checkout["user_id"]) != payment.user_id:
        raise ValidationError("Subscription payment owner does not match the signed-in account.")

    source_platform = source_platform or checkout.get("source_platform") or "payment_webhook"
    receipt, _ = SubscriptionPayment.objects.select_for_update().get_or_create(
        payment_transaction=payment,
        defaults={
            "user": payment.user,
            "plan": plan,
            "billing_cycle": billing_cycle,
            "amount": payment.amount,
            "currency": expected_currency,
            "gateway": payment.gateway,
            "reference": payment.reference,
            "status": SubscriptionPayment.STATUS_SUCCESS,
            "verified_at": payment.paid_at or timezone.now(),
            "source_platform": source_platform,
            "verification_summary": {"gateway_reference": payment.gateway_reference or ""},
        },
    )
    if receipt.activated_at and receipt.subscription_id:
        return receipt.subscription

    now = timezone.now()
    current = _current_subscription(payment.user, now=now, lock=True)
    previous_plan = current.plan if current else None
    previous_status = current.status if current else ""
    anchor = max(now, current.end_date) if current else now
    end_date = calculate_period_end(anchor, billing_cycle)
    same_plan = bool(current and current.plan_id == plan.id and current.billing_cycle == billing_cycle)
    if same_plan:
        subscription = current
        subscription.end_date = end_date
        subscription.status = VendorSubscription.STATUS_ACTIVE
        subscription.payment_state = "paid"
        subscription.cancel_at_period_end = False
        subscription.cancellation_requested_at = None
        subscription.cancelled_at = None
        subscription.cancellation_reason = ""
        subscription.transaction_id = payment.reference
        subscription.payment_method = payment.gateway
        subscription.source_platform = source_platform
        subscription.save()
        event_type = "renewed"
    else:
        VendorSubscription.objects.filter(vendor=payment.user, is_active=True).update(
            is_active=False,
            status=VendorSubscription.STATUS_INACTIVE,
            auto_renew=False,
        )
        subscription = VendorSubscription.objects.create(
            vendor=payment.user,
            plan=plan,
            start_date=now,
            end_date=end_date,
            status=VendorSubscription.STATUS_ACTIVE,
            billing_cycle=billing_cycle,
            currency=expected_currency,
            payment_state="paid",
            is_active=True,
            auto_renew=True,
            payment_method=payment.gateway,
            transaction_id=payment.reference,
            source_platform=source_platform,
        )
        event_type = "upgraded" if previous_plan and tier_rank(plan) > tier_rank(previous_plan) else "activated"

    receipt.subscription = subscription
    receipt.user = payment.user
    receipt.plan = plan
    receipt.billing_cycle = billing_cycle
    receipt.amount = payment.amount
    receipt.currency = expected_currency
    receipt.gateway = payment.gateway
    receipt.status = SubscriptionPayment.STATUS_SUCCESS
    receipt.verified_at = payment.paid_at or now
    receipt.activated_at = now
    receipt.source_platform = source_platform
    receipt.save()
    _history(
        payment.user,
        event_type,
        subscription=subscription,
        previous_plan=previous_plan,
        new_plan=plan,
        previous_status=previous_status,
        new_status=subscription.status,
        actor=actor,
        source_platform=source_platform,
        payment_reference=payment.reference,
        metadata={
            "billing_cycle": billing_cycle,
            "amount": str(payment.amount),
            "currency": expected_currency,
            "billing_policy": "non_prorated_period_stacked" if current and event_type == "upgraded" else "full_period",
        },
    )
    transaction.on_commit(lambda: sync_account_role_subscription(payment.user, subscription))
    transaction.on_commit(lambda: _notify_account(
        payment.user,
        "Arolana subscription activated",
        f"Your {plan.display_name} subscription is active until {subscription.end_date:%d %b %Y}.",
        {"subscription_id": subscription.id, "tier": plan.tier_key, "payment_reference": payment.reference},
    ))
    return subscription


@transaction.atomic
def request_cancellation(user_or_business, subscription_id=None, reason="", source_platform="web"):
    user = account_user(user_or_business)
    queryset = VendorSubscription.objects.select_for_update().filter(vendor=user, is_active=True)
    if subscription_id:
        queryset = queryset.filter(pk=subscription_id)
    subscription = queryset.order_by("-end_date").first()
    if not subscription or not subscription.is_current:
        raise ValidationError("No current subscription was found.")
    subscription.cancel_at_period_end = True
    subscription.auto_renew = False
    subscription.cancellation_requested_at = timezone.now()
    subscription.cancellation_reason = (reason or "").strip()
    subscription.save(update_fields=[
        "cancel_at_period_end",
        "auto_renew",
        "cancellation_requested_at",
        "cancellation_reason",
        "updated_at",
    ])
    _history(
        user,
        "cancellation_scheduled",
        subscription=subscription,
        previous_plan=subscription.plan,
        new_plan=subscription.plan,
        previous_status=subscription.status,
        new_status=subscription.status,
        source_platform=source_platform,
        metadata={"effective_at": subscription.end_date.isoformat()},
    )
    transaction.on_commit(lambda: _notify_account(
        user,
        "Subscription cancellation scheduled",
        f"Your {subscription.plan.display_name} plan remains active until {subscription.end_date:%d %b %Y}.",
        {"subscription_id": subscription.id, "event": "cancellation_scheduled"},
    ))
    return subscription


@transaction.atomic
def undo_cancellation(user_or_business, subscription_id=None, source_platform="web"):
    user = account_user(user_or_business)
    queryset = VendorSubscription.objects.select_for_update().filter(vendor=user, is_active=True)
    if subscription_id:
        queryset = queryset.filter(pk=subscription_id)
    subscription = queryset.order_by("-end_date").first()
    if not subscription or subscription.end_date <= timezone.now():
        raise ValidationError("This subscription can no longer be reactivated.")
    subscription.cancel_at_period_end = False
    subscription.auto_renew = True
    subscription.cancellation_requested_at = None
    subscription.cancellation_reason = ""
    subscription.save(update_fields=[
        "cancel_at_period_end",
        "auto_renew",
        "cancellation_requested_at",
        "cancellation_reason",
        "updated_at",
    ])
    _history(
        user,
        "cancellation_undone",
        subscription=subscription,
        previous_plan=subscription.plan,
        new_plan=subscription.plan,
        previous_status=subscription.status,
        new_status=subscription.status,
        source_platform=source_platform,
    )
    transaction.on_commit(lambda: _notify_account(
        user,
        "Subscription cancellation removed",
        f"Auto-renewal is active again for your {subscription.plan.display_name} plan.",
        {"subscription_id": subscription.id, "event": "cancellation_undone"},
    ))
    return subscription


@transaction.atomic
def schedule_downgrade(user_or_business, new_plan, source_platform="web"):
    user = account_user(user_or_business)
    subscription = _current_subscription(user, lock=True)
    if not subscription:
        raise ValidationError("No current subscription was found.")
    if tier_rank(new_plan) >= tier_rank(subscription.plan):
        raise ValidationError("Choose a lower plan for a scheduled downgrade.")
    subscription.pending_plan = new_plan
    subscription.pending_change_type = VendorSubscription.CHANGE_DOWNGRADE
    subscription.pending_change_effective_at = subscription.end_date
    subscription.save(update_fields=["pending_plan", "pending_change_type", "pending_change_effective_at", "updated_at"])
    _history(
        user,
        "downgrade_scheduled",
        subscription=subscription,
        previous_plan=subscription.plan,
        new_plan=new_plan,
        previous_status=subscription.status,
        new_status=subscription.status,
        source_platform=source_platform,
        metadata={"effective_at": subscription.end_date.isoformat()},
    )
    transaction.on_commit(lambda: _notify_account(
        user,
        "Subscription downgrade scheduled",
        f"Your plan will change to {new_plan.display_name} on {subscription.end_date:%d %b %Y}.",
        {
            "subscription_id": subscription.id,
            "event": "downgrade_scheduled",
            "pending_tier": new_plan.tier_key,
        },
    ))
    return subscription


@transaction.atomic
def cancel_scheduled_change(user_or_business, source_platform="web"):
    user = account_user(user_or_business)
    subscription = _current_subscription(user, lock=True)
    if not subscription or not subscription.pending_plan_id:
        raise ValidationError("No scheduled subscription change was found.")
    pending_plan = subscription.pending_plan
    subscription.pending_plan = None
    subscription.pending_change_type = ""
    subscription.pending_change_effective_at = None
    subscription.save(update_fields=[
        "pending_plan",
        "pending_change_type",
        "pending_change_effective_at",
        "updated_at",
    ])
    _history(
        user,
        "scheduled_change_cancelled",
        subscription=subscription,
        previous_plan=subscription.plan,
        new_plan=pending_plan,
        previous_status=subscription.status,
        new_status=subscription.status,
        source_platform=source_platform,
    )
    transaction.on_commit(lambda: _notify_account(
        user,
        "Scheduled subscription change cancelled",
        f"Your {subscription.plan.display_name} plan will continue unchanged.",
        {"subscription_id": subscription.id, "event": "scheduled_change_cancelled"},
    ))
    return subscription


@transaction.atomic
def set_auto_renew(user_or_business, enabled, source_platform="web"):
    user = account_user(user_or_business)
    subscription = _current_subscription(user, lock=True)
    if not subscription:
        raise ValidationError("No current subscription was found.")
    subscription.auto_renew = bool(enabled)
    if enabled:
        subscription.cancel_at_period_end = False
        subscription.cancellation_requested_at = None
        subscription.cancellation_reason = ""
    subscription.save(update_fields=[
        "auto_renew",
        "cancel_at_period_end",
        "cancellation_requested_at",
        "cancellation_reason",
        "updated_at",
    ])
    _history(
        user,
        "auto_renew_enabled" if enabled else "auto_renew_disabled",
        subscription=subscription,
        previous_plan=subscription.plan,
        new_plan=subscription.plan,
        previous_status=subscription.status,
        new_status=subscription.status,
        source_platform=source_platform,
    )
    transaction.on_commit(lambda: _notify_account(
        user,
        "Subscription auto-renewal updated",
        f"Auto-renewal is now {'enabled' if enabled else 'disabled'} for your {subscription.plan.display_name} plan.",
        {
            "subscription_id": subscription.id,
            "event": "auto_renew_enabled" if enabled else "auto_renew_disabled",
        },
    ))
    return subscription


def create_subscription_payment(
    user_or_business,
    plan,
    billing_cycle,
    gateway,
    source_platform="web",
    role_context="vendor",
):
    """Create a server-priced checkout record; the gateway still must verify it."""
    from arolana_payments.models import PaymentStatus, PaymentTransaction

    user = account_user(user_or_business)
    if not user or not getattr(user, "pk", None):
        raise ValidationError("A signed-in Arolana account is required.")
    if not plan or not plan.is_active:
        raise ValidationError("Choose an active subscription plan.")
    amount = plan_price(plan, billing_cycle)
    if amount <= 0:
        raise ValidationError("The Free plan does not require checkout.")
    current = get_effective_subscription(user)
    role_context = str(role_context or "vendor").strip().lower()
    if role_context in {"installer", "engineer", "service_provider"}:
        role_context = "provider"
    elif role_context not in {"vendor", "manufacturer", "provider"}:
        role_context = "vendor"
    requested_change = "upgrade" if tier_rank(plan) > tier_rank(current.tier) else (
        "downgrade" if tier_rank(plan) < tier_rank(current.tier) else "renewal"
    )
    vendor_profile = getattr(user, "vendor_profile", None)
    provider_profile = getattr(user, "service_provider_profile", None)
    name = user.get_full_name() or getattr(vendor_profile, "store_name", "") or getattr(provider_profile, "business_name", "")
    phone = (
        getattr(vendor_profile, "support_phone", "")
        or getattr(provider_profile, "phone_number", "")
        or getattr(user, "phone_number", "")
        or ""
    )
    return PaymentTransaction.objects.create(
        user=user,
        order_id=f"account_subscription:{user.pk}:{plan.pk}",
        gateway=gateway,
        status=PaymentStatus.PENDING,
        amount=amount,
        currency="NGN",
        customer_email=user.email,
        customer_name=name,
        customer_phone=phone,
        checkout_data={
            "purpose": "account_subscription",
            "user_id": user.pk,
            "plan_id": plan.pk,
            "tier": plan.tier_key,
            "plan_name": plan.display_name,
            "billing_cycle": billing_cycle,
            "source_platform": source_platform,
            "role_context": role_context,
            "requested_change": requested_change,
            "server_priced": True,
        },
    )


def _send_expiry_reminder(subscription, days_remaining):
    is_trial = subscription.status == VendorSubscription.STATUS_TRIAL
    event_prefix = "trial_expiry" if is_trial else "expiry"
    event_key = f"{event_prefix}_{days_remaining}_days"
    log, created = SubscriptionReminderLog.objects.get_or_create(
        subscription=subscription,
        event_key=event_key,
        channel="combined",
        defaults={"metadata": {"days_remaining": days_remaining, "is_trial": is_trial}},
    )
    if not created:
        return False
    _notify_account(
        subscription.vendor,
        "Arolana trial reminder" if is_trial else "Arolana subscription reminder",
        (
            f"Your {subscription.plan.display_name} trial ends in {days_remaining} "
            f"day{'s' if days_remaining != 1 else ''}."
            if is_trial else
            f"Your {subscription.plan.display_name} subscription expires in {days_remaining} "
            f"day{'s' if days_remaining != 1 else ''}."
        ),
        {
            "subscription_id": subscription.id,
            "tier": subscription.plan.tier_key,
            "days_remaining": days_remaining,
            "event": event_key,
        },
    )
    return True


def _send_grace_reminder(subscription, days_remaining):
    event_key = f"grace_expiry_{days_remaining}_days"
    _, created = SubscriptionReminderLog.objects.get_or_create(
        subscription=subscription,
        event_key=event_key,
        channel="combined",
        defaults={"metadata": {"days_remaining": days_remaining}},
    )
    if not created:
        return False
    _notify_account(
        subscription.vendor,
        "Arolana subscription payment reminder",
        (
            f"Your {subscription.plan.display_name} grace period ends in {days_remaining} "
            f"day{'s' if days_remaining != 1 else ''}. Renew now to keep paid features active."
        ),
        {
            "subscription_id": subscription.id,
            "tier": subscription.plan.tier_key,
            "days_remaining": days_remaining,
            "event": event_key,
        },
        priority=4,
    )
    return True


def process_subscription_lifecycle(now=None):
    """Idempotently process reminders, expiry, grace, cancellation and downgrades."""
    now = now or timezone.now()
    result = {
        "reminders": 0,
        "grace_reminders": 0,
        "grace_started": 0,
        "expired": 0,
        "cancelled": 0,
        "downgrades": 0,
    }
    active = VendorSubscription.objects.filter(is_active=True).select_related("vendor", "plan", "pending_plan")

    for subscription in active.filter(status__in=[VendorSubscription.STATUS_ACTIVE, VendorSubscription.STATUS_TRIAL], end_date__gt=now):
        days = (subscription.end_date.date() - now.date()).days
        reminder_days = {14, 7, 3, 1}
        if subscription.billing_cycle == VendorSubscription.BILLING_YEARLY:
            reminder_days.add(30)
        if days in reminder_days and _send_expiry_reminder(subscription, days):
            result["reminders"] += 1

    grace_active = active.filter(
        status__in=[VendorSubscription.STATUS_PAST_DUE, VendorSubscription.STATUS_GRACE_PERIOD],
        grace_period_ends_at__gt=now,
    )
    for subscription in grace_active:
        days = (subscription.grace_period_ends_at.date() - now.date()).days
        if days in {2, 1} and _send_grace_reminder(subscription, days):
            result["grace_reminders"] += 1

    for subscription_id in list(active.filter(end_date__lte=now).values_list("id", flat=True)):
        with transaction.atomic():
            subscription = VendorSubscription.objects.select_for_update().select_related(
                "vendor", "plan", "pending_plan"
            ).filter(pk=subscription_id, is_active=True).first()
            if not subscription:
                continue
            user = subscription.vendor
            previous_status = subscription.status
            pending_plan = subscription.pending_plan
            event_notice = None

            if subscription.cancel_at_period_end:
                subscription.status = VendorSubscription.STATUS_CANCELLED
                subscription.is_active = False
                subscription.cancelled_at = now
                subscription.save(update_fields=["status", "is_active", "cancelled_at", "updated_at"])
                _history(user, "cancelled", subscription=subscription, previous_plan=subscription.plan,
                         new_plan=None, previous_status=previous_status, new_status=subscription.status,
                         source_platform="lifecycle")
                event_notice = (
                    "Subscription cancelled",
                    f"Your {subscription.plan.display_name} subscription has ended.",
                    "cancelled",
                )
                result["cancelled"] += 1
            elif pending_plan and subscription.pending_change_type == VendorSubscription.CHANGE_DOWNGRADE:
                subscription.status = VendorSubscription.STATUS_EXPIRED
                subscription.is_active = False
                subscription.save(update_fields=["status", "is_active", "updated_at"])
                if pending_plan.tier_key == "free":
                    new_subscription = activate_free_subscription(user, source_platform="lifecycle")
                    new_status = new_subscription.status
                else:
                    new_subscription = VendorSubscription.objects.create(
                        vendor=user,
                        plan=pending_plan,
                        start_date=now,
                        end_date=calculate_period_end(now, subscription.billing_cycle),
                        status=VendorSubscription.STATUS_PENDING_PAYMENT,
                        billing_cycle=subscription.billing_cycle,
                        currency="NGN",
                        payment_state="pending",
                        is_active=False,
                        auto_renew=False,
                        source_platform="lifecycle",
                    )
                    new_status = new_subscription.status
                if pending_plan.tier_key == "free":
                    history_event = "downgrade_effective"
                    event_notice = (
                        "Subscription plan changed",
                        f"Your Arolana plan is now {pending_plan.display_name}.",
                        history_event,
                    )
                else:
                    history_event = "downgrade_payment_required"
                    event_notice = (
                        "Subscription payment required",
                        (
                            f"Your {subscription.plan.display_name} period has ended. "
                            "Your account is using Free access until payment is completed for "
                            f"{pending_plan.display_name}."
                        ),
                        history_event,
                    )
                _history(user, history_event, subscription=new_subscription,
                         previous_plan=subscription.plan, new_plan=pending_plan,
                         previous_status=previous_status, new_status=new_status,
                         source_platform="lifecycle")
                result["downgrades"] += 1
            elif subscription.auto_renew and subscription.status in {
                VendorSubscription.STATUS_ACTIVE,
                VendorSubscription.STATUS_TRIAL,
            }:
                grace_days = max(int(getattr(settings, "SUBSCRIPTION_GRACE_PERIOD_DAYS", 3)), 0)
                if grace_days:
                    subscription.status = VendorSubscription.STATUS_GRACE_PERIOD
                    subscription.payment_state = "past_due"
                    subscription.grace_period_ends_at = now + relativedelta(days=grace_days)
                    subscription.save(update_fields=["status", "payment_state", "grace_period_ends_at", "updated_at"])
                    _history(user, "grace_period_started", subscription=subscription,
                             previous_plan=subscription.plan, new_plan=subscription.plan,
                             previous_status=previous_status, new_status=subscription.status,
                             source_platform="lifecycle")
                    transaction.on_commit(lambda user=user, subscription=subscription, grace_days=grace_days: _notify_account(
                        user,
                        "Subscription payment required",
                        f"Your {subscription.plan.display_name} subscription is in a {grace_days}-day grace period. Renew to keep paid features active.",
                        {"subscription_id": subscription.id, "event": "grace_period_started"},
                    ))
                    transaction.on_commit(lambda user=user: sync_account_role_subscription(user, None))
                    result["grace_started"] += 1
                    continue
                subscription.status = VendorSubscription.STATUS_EXPIRED
                subscription.is_active = False
                subscription.save(update_fields=["status", "is_active", "updated_at"])
                _history(user, "expired", subscription=subscription, previous_plan=subscription.plan,
                         new_plan=None, previous_status=previous_status, new_status=subscription.status,
                         source_platform="lifecycle")
                event_notice = (
                    "Subscription expired",
                    f"Your {subscription.plan.display_name} subscription has expired. Your account now uses Free plan access.",
                    "expired",
                )
                result["expired"] += 1
            else:
                subscription.status = VendorSubscription.STATUS_EXPIRED
                subscription.is_active = False
                subscription.save(update_fields=["status", "is_active", "updated_at"])
                _history(user, "expired", subscription=subscription, previous_plan=subscription.plan,
                         new_plan=None, previous_status=previous_status, new_status=subscription.status,
                         source_platform="lifecycle")
                event_notice = (
                    "Subscription expired",
                    f"Your {subscription.plan.display_name} subscription has expired. Your account now uses Free plan access.",
                    "expired",
                )
                result["expired"] += 1
            if event_notice:
                title, message, event = event_notice
                transaction.on_commit(
                    lambda user=user, subscription=subscription, title=title, message=message, event=event: _notify_account(
                        user,
                        title,
                        message,
                        {"subscription_id": subscription.id, "event": event},
                    )
                )
            transaction.on_commit(lambda user=user: sync_account_role_subscription(user, None))

    grace_ids = list(VendorSubscription.objects.filter(
        is_active=True,
        status__in=[VendorSubscription.STATUS_PAST_DUE, VendorSubscription.STATUS_GRACE_PERIOD],
        grace_period_ends_at__lte=now,
    ).values_list("id", flat=True))
    for subscription_id in grace_ids:
        with transaction.atomic():
            subscription = VendorSubscription.objects.select_for_update().select_related("vendor", "plan").filter(
                pk=subscription_id, is_active=True
            ).first()
            if not subscription:
                continue
            previous_status = subscription.status
            subscription.status = VendorSubscription.STATUS_EXPIRED
            subscription.is_active = False
            subscription.save(update_fields=["status", "is_active", "updated_at"])
            _history(subscription.vendor, "grace_period_expired", subscription=subscription,
                     previous_plan=subscription.plan, new_plan=None,
                     previous_status=previous_status, new_status=subscription.status,
                     source_platform="lifecycle")
            transaction.on_commit(
                lambda user=subscription.vendor, subscription=subscription: _notify_account(
                    user,
                    "Subscription grace period ended",
                    f"Your {subscription.plan.display_name} subscription has expired. Your account now uses Free plan access.",
                    {"subscription_id": subscription.id, "event": "grace_period_expired"},
                )
            )
            transaction.on_commit(lambda user=subscription.vendor: sync_account_role_subscription(user, None))
            result["expired"] += 1
    return result
