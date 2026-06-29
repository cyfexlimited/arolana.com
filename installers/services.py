import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from notifications.models import Notification

from .models import ProviderProfileChangeRequest, ServiceCategory, ServiceProviderProfile


SENSITIVE_PROFILE_FIELDS = {
    "business_name",
    "contact_person",
    "phone_number",
    "whatsapp_number",
    "email",
    "address",
    "city",
    "state",
    "country",
    "service_coverage",
    "provider_type",
    "cac_number",
    "government_id_upload",
    "cac_certificate_upload",
    "business_logo",
    "business_banner",
    "profile_image",
    "bank_details",
}

NON_SENSITIVE_PROFILE_FIELDS = {
    "description",
    "years_of_experience",
    "availability_note",
    "business_hours",
    "preferred_language",
    "notification_preferences",
    "support_phone",
    "support_email",
    "support_whatsapp",
    "website",
}


def _product_category_ids(product):
    category = getattr(product, "category", None)
    ids = set()
    while category:
        ids.add(category.id)
        category = getattr(category, "parent", None)
    return ids


def _product_search_text(product):
    values = [
        getattr(product, "name", ""),
        getattr(product, "description", ""),
        getattr(product, "specifications", ""),
        getattr(product, "meta_keywords", ""),
        getattr(getattr(product, "category", None), "name", ""),
        getattr(getattr(product, "brand", None), "name", ""),
    ]
    return re.sub(r"<[^>]+>", " ", " ".join(str(value or "") for value in values)).lower()


def suggested_categories_for_product(product, limit=6):
    active = ServiceCategory.objects.filter(is_active=True).prefetch_related("product_categories")
    category_ids = _product_category_ids(product)
    explicit = list(active.filter(product_categories__id__in=category_ids).distinct())
    if len(explicit) >= limit:
        return explicit[:limit]

    text = _product_search_text(product)
    matched_ids = {item.id for item in explicit}
    keyword_matches = []
    for category in active.exclude(id__in=matched_ids):
        if any(keyword in text for keyword in category.keywords):
            keyword_matches.append(category)
            if len(explicit) + len(keyword_matches) >= limit:
                break
    return (explicit + keyword_matches)[:limit]


def suggested_providers_for_product(product, limit=6):
    categories = suggested_categories_for_product(product)
    if not categories:
        return ServiceProviderProfile.objects.none()
    return (
        ServiceProviderProfile.objects.public()
        .filter(services__is_active=True, services__category__in=categories)
        .select_related("user")
        .prefetch_related("services__category")
        .distinct()
        .order_by("-average_rating", "-total_completed_jobs")[:limit]
    )


def filter_public_providers(params):
    queryset = (
        ServiceProviderProfile.objects.public()
        .select_related("user")
        .prefetch_related("services__category")
        .distinct()
    )
    filters = {
        "country": "country__iexact",
        "state": "state__iexact",
        "city": "city__iexact",
        "provider_type": "provider_type",
    }
    for parameter, lookup in filters.items():
        value = str(params.get(parameter, "")).strip()
        if value:
            queryset = queryset.filter(**{lookup: value})
    category = str(params.get("category", "")).strip()
    if category:
        queryset = queryset.filter(services__category__slug=category, services__is_active=True)
    rating = str(params.get("rating", "")).strip()
    if rating:
        try:
            queryset = queryset.filter(average_rating__gte=float(rating))
        except ValueError:
            pass
    query = str(params.get("q", "")).strip()
    if query:
        queryset = queryset.filter(
            Q(business_name__icontains=query)
            | Q(description__icontains=query)
            | Q(city__icontains=query)
            | Q(state__icontains=query)
            | Q(services__service_name__icontains=query)
            | Q(services__category__name__icontains=query)
        )
    return queryset.distinct()


def provider_workspace_notifications(provider):
    quote_ids = list(provider.quote_requests.values_list("id", flat=True))
    workspace_filter = (
        Q(metadata__service_provider_id=provider.id)
        | Q(metadata__provider_id=provider.id)
        | Q(notification_type="security")
    )
    if quote_ids:
        workspace_filter |= Q(metadata__service_quote_request_id__in=quote_ids)
    return (
        Notification.objects.filter(user=provider.user, is_archived=False)
        .filter(workspace_filter)
        .order_by("-created_at")
    )


def submit_provider_profile(provider):
    now = timezone.now()
    provider.verification_status = ServiceProviderProfile.STATUS_PENDING
    provider.submitted_at = provider.submitted_at or now
    provider.review_due_at = now + timedelta(hours=72)
    provider.rejection_reason = ""
    provider.changes_requested_note = ""
    provider.is_verified = False
    provider.save(update_fields=[
        "verification_status",
        "submitted_at",
        "review_due_at",
        "rejection_reason",
        "changes_requested_note",
        "is_verified",
        "updated_at",
    ])
    notify_staff_provider_registration(provider)
    Notification.send(
        provider.user,
        "system",
        "Application submitted",
        "Your Arolana service provider application has been submitted for review. Expected review time is 24-72 hours.",
        link="/installers/dashboard/",
        metadata={"service_provider_id": provider.id, "status": provider.verification_status},
        priority=2,
    )
    return provider


def approve_provider(provider, admin_user=None, verify=False, note=""):
    now = timezone.now()
    provider.verification_status = ServiceProviderProfile.STATUS_VERIFIED if verify else ServiceProviderProfile.STATUS_APPROVED
    provider.is_verified = bool(verify)
    provider.is_active = True
    provider.approved_at = provider.approved_at or now
    provider.reviewed_by = admin_user
    provider.verification_note = note or provider.verification_note
    provider.admin_note = note or provider.admin_note
    provider.save(update_fields=[
        "verification_status",
        "is_verified",
        "is_active",
        "approved_at",
        "reviewed_by",
        "verification_note",
        "admin_note",
        "updated_at",
    ])
    Notification.send(
        provider.user,
        "system",
        "Service provider approved",
        "Your Arolana service provider profile has been approved. You can now access your provider dashboard.",
        link="/installers/dashboard/",
        metadata={"service_provider_id": provider.id, "status": provider.verification_status},
        priority=3,
    )
    return provider


def reject_provider(provider, admin_user=None, reason=""):
    now = timezone.now()
    provider.verification_status = ServiceProviderProfile.STATUS_REJECTED
    provider.is_verified = False
    provider.rejected_at = now
    provider.reviewed_by = admin_user
    provider.rejection_reason = reason or provider.rejection_reason
    provider.save(update_fields=[
        "verification_status",
        "is_verified",
        "rejected_at",
        "reviewed_by",
        "rejection_reason",
        "updated_at",
    ])
    Notification.send(
        provider.user,
        "system",
        "Service provider application rejected",
        provider.rejection_reason or "Your Arolana service provider application was not approved. Contact support for help.",
        link="/installers/dashboard/",
        metadata={"service_provider_id": provider.id, "status": provider.verification_status},
        priority=3,
    )
    return provider


def request_provider_changes(provider, admin_user=None, note=""):
    now = timezone.now()
    provider.verification_status = ServiceProviderProfile.STATUS_CHANGES_REQUESTED
    provider.is_verified = False
    provider.changes_requested_at = now
    provider.reviewed_by = admin_user
    provider.changes_requested_note = note or provider.changes_requested_note
    provider.save(update_fields=[
        "verification_status",
        "is_verified",
        "changes_requested_at",
        "reviewed_by",
        "changes_requested_note",
        "updated_at",
    ])
    Notification.send(
        provider.user,
        "system",
        "Changes requested",
        provider.changes_requested_note or "Arolana requested changes to your provider profile.",
        link="/installers/dashboard/",
        metadata={"service_provider_id": provider.id, "status": provider.verification_status},
        priority=3,
    )
    return provider


def suspend_provider(provider, admin_user=None, note=""):
    provider.verification_status = ServiceProviderProfile.STATUS_SUSPENDED
    provider.is_verified = False
    provider.reviewed_by = admin_user
    provider.admin_note = note or provider.admin_note
    provider.save(update_fields=["verification_status", "is_verified", "reviewed_by", "admin_note", "updated_at"])
    Notification.send(
        provider.user,
        "system",
        "Provider account suspended",
        provider.admin_note or "Your provider dashboard has been suspended. Contact Arolana support.",
        link="/installers/dashboard/",
        metadata={"service_provider_id": provider.id, "status": provider.verification_status},
        priority=4,
    )
    return provider


def approve_provider_kyc(provider, admin_user=None, note=""):
    provider.kyc_status = ServiceProviderProfile.KYC_APPROVED
    provider.kyc_note = note or provider.kyc_note
    provider.kyc_reviewed_at = timezone.now()
    provider.kyc_expires_at = timezone.now() + timedelta(days=365)
    provider.save(update_fields=["kyc_status", "kyc_note", "kyc_reviewed_at", "kyc_expires_at", "updated_at"])
    Notification.send(provider.user, "system", "Provider KYC approved", "Your service provider KYC has been approved.", metadata={"service_provider_id": provider.id}, priority=3)
    return provider


def reject_provider_kyc(provider, admin_user=None, note=""):
    provider.kyc_status = ServiceProviderProfile.KYC_REJECTED
    provider.kyc_note = note or provider.kyc_note
    provider.kyc_reviewed_at = timezone.now()
    provider.save(update_fields=["kyc_status", "kyc_note", "kyc_reviewed_at", "updated_at"])
    Notification.send(provider.user, "system", "Provider KYC rejected", provider.kyc_note or "Your service provider KYC was rejected. Please resubmit valid documents.", metadata={"service_provider_id": provider.id}, priority=3)
    return provider


def submit_provider_kyc(provider):
    provider.kyc_status = ServiceProviderProfile.KYC_PENDING
    provider.save(update_fields=["kyc_status", "updated_at"])
    staff = get_user_model().objects.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True)).distinct()
    Notification.bulk_create(
        staff,
        "system",
        "Provider KYC pending",
        f"{provider.business_name} submitted provider KYC documents for review.",
        link="/admin/installers/serviceproviderprofile/",
        metadata={"service_provider_id": provider.id},
    )
    Notification.send(provider.user, "system", "KYC submitted", "Your KYC documents have been submitted for Arolana review.", metadata={"service_provider_id": provider.id})
    return provider


def update_provider_profile(provider, data, user=None, force_live=False):
    incoming = {key: value for key, value in data.items() if key in SENSITIVE_PROFILE_FIELDS or key in NON_SENSITIVE_PROFILE_FIELDS}
    sensitive = {key: value for key, value in incoming.items() if key in SENSITIVE_PROFILE_FIELDS}
    non_sensitive = {key: value for key, value in incoming.items() if key in NON_SENSITIVE_PROFILE_FIELDS}

    for key, value in non_sensitive.items():
        setattr(provider, key, value)
    if non_sensitive:
        provider.save(update_fields=[*non_sensitive.keys(), "updated_at"])

    if not sensitive:
        return provider, None

    if force_live or not provider.approval_allows_dashboard:
        for key, value in sensitive.items():
            setattr(provider, key, value)
        provider.verification_status = ServiceProviderProfile.STATUS_PENDING
        provider.is_verified = False
        provider.review_due_at = timezone.now() + timedelta(hours=72)
        provider.save(update_fields=[*sensitive.keys(), "verification_status", "is_verified", "review_due_at", "updated_at"])
        notify_staff_provider_registration(provider)
        return provider, None

    if provider.sensitive_update_locked:
        available = provider.sensitive_update_available_at
        raise ValidationError(f"Sensitive profile changes are locked until {available:%Y-%m-%d}. Contact admin support if this is urgent.")
    if provider.profile_change_requests.filter(status=ProviderProfileChangeRequest.STATUS_PENDING).exists():
        raise ValidationError("A sensitive profile update is already awaiting Arolana approval.")

    old_values = {key: str(getattr(provider, key, "") or "") for key in sensitive}
    change = ProviderProfileChangeRequest.objects.create(
        provider=provider,
        requested_by=user,
        old_values=old_values,
        proposed_values={key: str(value or "") for key, value in sensitive.items()},
        sensitive_fields=list(sensitive.keys()),
    )
    staff = get_user_model().objects.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True)).distinct()
    Notification.bulk_create(
        staff,
        "system",
        "Provider profile change pending",
        f"{provider.business_name} submitted sensitive profile changes for admin approval.",
        link="/admin/installers/providerprofilechangerequest/",
        metadata={"service_provider_id": provider.id, "change_request_id": change.id},
    )
    Notification.send(
        provider.user,
        "system",
        "Profile change pending approval",
        "Your sensitive provider profile change was submitted for Arolana approval.",
        metadata={"service_provider_id": provider.id, "change_request_id": change.id},
    )
    return provider, change


def approve_profile_change_request(change, admin_user=None, note=""):
    if change.status != ProviderProfileChangeRequest.STATUS_PENDING:
        return change
    provider = change.provider
    for key, value in change.proposed_values.items():
        if hasattr(provider, key):
            setattr(provider, key, value)
    if change.proposed_file and change.proposed_file_field and hasattr(provider, change.proposed_file_field):
        setattr(provider, change.proposed_file_field, change.proposed_file)
    provider.last_sensitive_update_approved_at = timezone.now()
    provider.save()
    change.status = ProviderProfileChangeRequest.STATUS_APPROVED
    change.admin_note = note or change.admin_note
    change.reviewed_by = admin_user
    change.reviewed_at = timezone.now()
    change.save(update_fields=["status", "admin_note", "reviewed_by", "reviewed_at", "updated_at"])
    Notification.send(provider.user, "system", "Profile change approved", "Your provider profile change was approved.", metadata={"change_request_id": change.id}, priority=3)
    return change


def reject_profile_change_request(change, admin_user=None, note=""):
    change.status = ProviderProfileChangeRequest.STATUS_REJECTED
    change.admin_note = note or change.admin_note
    change.reviewed_by = admin_user
    change.reviewed_at = timezone.now()
    change.save(update_fields=["status", "admin_note", "reviewed_by", "reviewed_at", "updated_at"])
    Notification.send(change.provider.user, "system", "Profile change rejected", change.admin_note or "Your provider profile change was rejected.", metadata={"change_request_id": change.id}, priority=3)
    return change


def assign_service_request(quote, provider, admin_user=None, note=""):
    if not provider.can_receive_serious_jobs:
        raise ValidationError("Provider must be approved, KYC-ready, active, and subscribed before serious jobs can be assigned.")
    quote.provider = provider
    quote.status = "assigned"
    quote.assigned_by = admin_user
    quote.assigned_at = timezone.now()
    quote.admin_note = note or quote.admin_note
    quote.save(update_fields=["provider", "status", "assigned_by", "assigned_at", "admin_note", "updated_at"])
    Notification.send(
        provider.user,
        "message",
        "New service request assigned",
        f"Arolana assigned a service request: {quote.service_needed} in {quote.city}, {quote.state}.",
        link="/installers/dashboard/",
        metadata={"service_quote_request_id": quote.id},
        priority=4,
    )
    return quote


def notify_staff_provider_registration(provider):
    staff = get_user_model().objects.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True)).distinct()
    Notification.bulk_create(
        staff,
        "system",
        "Service provider registration pending",
        f"{provider.business_name} submitted a {provider.get_provider_type_display()} profile for verification.",
        link="/admin/installers/serviceproviderprofile/",
        metadata={"service_provider_id": provider.id},
    )


def notify_staff_service_quote(quote):
    staff = get_user_model().objects.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True)).distinct()
    Notification.bulk_create(
        staff,
        "message",
        "New service quote request",
        f"{quote.name} requested {quote.service_needed} in {quote.city}, {quote.state}.",
        link="/admin/installers/servicequoterequest/",
        metadata={"service_quote_request_id": quote.id, "product_id": quote.product_id},
    )
