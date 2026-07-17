from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Max, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from arolana_payments.models import PaymentMethod, PaymentStatus, PaymentTransaction
from arolana_payments.services import gateway_is_available, init_paystack_checkout

from notifications.models import Notification
from products.models import Product

from core.private_upload_validation import (
    validate_project_document_upload,
    validate_project_video_upload,
    validate_private_profile_image_upload,
)

from .forms import (
    ProviderAvailabilityForm,
    ProviderRegistrationForm,
    ProviderServiceForm,
    ProviderWorkspaceProfileForm,
    ProviderWorkspaceSettingsForm,
    ServicePortfolioForm,
    ServiceProjectBulkMediaForm,
    ServiceProjectMediaForm,
    ServiceQuoteRequestForm,
    ServiceReviewForm,
)
from .models import (
    ProviderKYCDocument,
    ProviderProfileChangeRequest,
    ProviderSubscriptionPlan,
    SavedServiceProject,
    ServiceCategory,
    ServicePortfolio,
    ServiceProjectMedia,
    ProviderService,
    ServiceProviderProfile,
    ServiceQuoteRequest,
)
from subscriptions.lifecycle import get_effective_subscription, official_plans
from .project_services import (
    ProjectEntitlementService,
    group_project_gallery_media,
    notify_project_submitted,
    record_project_event,
    resolve_project_gallery_media,
)
from .subscription_services import create_provider_subscription_payment
from .service_offerings import ProviderServicePolicy
from .services import (
    filter_public_providers,
    notify_staff_service_quote,
    submit_provider_kyc,
    submit_provider_profile,
    update_provider_profile,
)


# =============================================================================
# HELPERS
# =============================================================================


def _validation_error_messages(exc: ValidationError) -> list[str]:
    """
    Convert a Django ValidationError into clean user-facing strings.
    """

    if hasattr(exc, "message_dict"):
        output = []

        for field_name, field_errors in exc.message_dict.items():
            for error in field_errors:
                output.append(
                    f"{field_name}: {error}"
                )

        return output

    return [
        str(message)
        for message in exc.messages
    ]


def _project_media_summary(project):
    if not project or not project.pk:
        return {
            "cover": None,
            "images": 0,
            "videos": 0,
            "documents": 0,
            "total": 0,
        }

    media = project.media_items.all()
    counts = media.aggregate(
        images=Count("id", filter=Q(media_type=ServiceProjectMedia.TYPE_IMAGE)),
        videos=Count("id", filter=Q(media_type=ServiceProjectMedia.TYPE_VIDEO)),
        documents=Count("id", filter=Q(media_type=ServiceProjectMedia.TYPE_DOCUMENT)),
        total=Count("id"),
    )
    counts["cover"] = (
        media.filter(
            media_type=ServiceProjectMedia.TYPE_IMAGE,
            is_cover=True,
        ).first()
        or media.filter(
            media_type=ServiceProjectMedia.TYPE_IMAGE,
        ).order_by("-is_featured", "display_order", "id").first()
    )
    return counts


def _show_validation_errors(
    request,
    exc: ValidationError,
):
    """
    Add validation errors to Django messages.
    """

    for error in _validation_error_messages(exc):
        messages.error(
            request,
            error,
        )


def _provider_workspace(request):
    return get_object_or_404(
        ServiceProviderProfile.objects.select_related(
            "user"
        ),
        user=request.user,
    )


def _workspace_context(
    provider,
    active,
):
    return {
        "provider": provider,
        "workspace_active": active,
        "profile_steps": (
            provider.profile_completion_items
        ),
        "profile_missing_steps": (
            provider.profile_missing_steps
        ),
        "project_entitlements": (
            ProjectEntitlementService(
                provider
            ).payload()
        ),
        "effective_subscription": get_effective_subscription(
            provider.user,
            role_context="provider",
        ).as_dict(),
        "subscription_plans": official_plans(),
    }


# =============================================================================
# PUBLIC PROVIDER DIRECTORY
# =============================================================================


def directory(request):
    providers = filter_public_providers(
        request.GET
    )

    categories = (
        ServiceCategory.objects
        .filter(
            is_active=True
        )
        .annotate(
            provider_count=Count(
                "provider_services__provider",
                distinct=True,
            )
        )
        .order_by(
            "name"
        )
    )

    page = Paginator(
        providers,
        18,
    ).get_page(
        request.GET.get(
            "page"
        )
    )

    return render(
        request,
        "installers/directory.html",
        {
            "page_obj": page,
            "providers": page.object_list,
            "categories": categories,
            "provider_types": (
                ServiceProviderProfile.PROVIDER_TYPES
            ),
            "seo_title": (
                "Verified Installers & Engineers | Arolana"
            ),
            "seo_description": (
                "Find verified installers, repair engineers, "
                "technicians, trainers, and consultants on Arolana."
            ),
        },
    )


def category_detail(
    request,
    slug,
):
    category = get_object_or_404(
        ServiceCategory,
        slug=slug,
        is_active=True,
    )

    providers = filter_public_providers(
        {
            **request.GET.dict(),
            "category": category.slug,
        }
    )

    projects = (
        ServicePortfolio.objects
        .public()
        .optimized()
        .filter(
            service_category=category
        )[:8]
    )

    page = Paginator(
        providers,
        18,
    ).get_page(
        request.GET.get(
            "page"
        )
    )

    return render(
        request,
        "installers/category_detail.html",
        {
            "category": category,
            "page_obj": page,
            "providers": page.object_list,
            "projects": projects,
            "seo_title": (
                f"Verified {category.name} "
                "in Nigeria | Arolana"
            ),
            "seo_description": (
                category.description
                or (
                    f"Find trusted and verified "
                    f"{category.name.lower()} on Arolana."
                )
            ),
        },
    )


def provider_detail(
    request,
    slug,
):
    provider = get_object_or_404(
        ServiceProviderProfile.objects
        .public()
        .select_related(
            "user"
        )
        .prefetch_related(
            Prefetch(
                "services",
                queryset=ProviderService.objects.filter(is_active=True).select_related("category"),
                to_attr="public_services",
            ),
            "portfolio_items__media_items",
            "portfolio_items__service_category",
            "reviews__customer",
        ),
        slug=slug,
    )
    return render(
        request,
        "installers/provider_detail.html",
        {
            "provider": provider,
            "services": provider.public_services,
            "portfolio_items": (
                ServicePortfolio.objects
                .public()
                .optimized()
                .filter(
                    provider=provider
                )
            ),
            "reviews": (
                provider.reviews
                .filter(
                    is_approved=True
                )
                .select_related(
                    "customer"
                )[:20]
            ),
            "review_form": ServiceReviewForm(),
            "seo_title": (
                f"{provider.business_name} - Verified "
                f"{provider.get_provider_type_display()} "
                "| Arolana"
            ),
            "seo_description": (
                provider.description[:160]
            ),
        },
    )


# =============================================================================
# PUBLIC SERVICE DETAIL
# =============================================================================


def service_detail(request, provider_slug, service_id):
    provider = get_object_or_404(
        ServiceProviderProfile.objects.public().select_related("user"),
        slug=provider_slug,
    )
    service = get_object_or_404(
        ProviderService.objects.select_related("category", "provider", "provider__user"),
        pk=service_id,
        provider=provider,
        is_active=True,
    )
    related_services = (
        provider.services.filter(is_active=True)
        .exclude(pk=service.pk)
        .select_related("category", "provider")[:6]
    )
    related_projects = (
        ServicePortfolio.objects.public()
        .optimized()
        .filter(provider=provider)[:3]
    )
    return render(request, "installers/service_detail.html", {
        "provider": provider,
        "service": service,
        "related_services": related_services,
        "related_projects": related_projects,
        "seo_title": f"{service.service_name} by {provider.business_name} | Arolana",
        "seo_description": service.card_excerpt,
    })


# =============================================================================
# PROVIDER REGISTRATION
# =============================================================================


@login_required
def register_provider(request):
    instance = (
        ServiceProviderProfile.objects
        .filter(
            user=request.user
        )
        .first()
    )

    if request.method == "POST":
        form = ProviderRegistrationForm(
            request.POST,
            request.FILES,
            instance=instance,
        )

        if form.is_valid():
            provider = form.save(
                commit=False
            )

            provider.user = request.user

            provider.save()

            submit_provider_profile(
                provider
            )

            messages.success(
                request,
                (
                    "Your provider profile was saved and sent "
                    "for Arolana verification."
                ),
            )

            return redirect(
                "installers:provider_dashboard"
            )

    else:
        initial = {
            "contact_person": (
                request.user.get_full_name()
            ),
            "email": request.user.email,
            "phone_number": (
                getattr(
                    request.user,
                    "phone_number",
                    "",
                )
                or ""
            ),
        }

        form = ProviderRegistrationForm(
            instance=instance,
            initial=initial,
        )

    return render(
        request,
        "installers/provider_form.html",
        {
            "form": form,
            "provider": instance,
        },
    )


# =============================================================================
# PROVIDER DASHBOARD
# =============================================================================


@login_required
def provider_dashboard(request):
    provider = get_object_or_404(
        ServiceProviderProfile,
        user=request.user,
    )

    if not provider.approval_allows_dashboard:
        return render(
            request,
            "installers/provider_pending.html",
            {
                "provider": provider,
                "kyc_documents": (
                    provider.kyc_documents
                    .filter(
                        is_active=True
                    )
                ),
                "change_requests": (
                    provider.profile_change_requests
                    .all()[:10]
                ),
            },
        )

    if request.method == "POST":
        action = request.POST.get(
            "action"
        )

        if action == "update_availability":
            availability = request.POST.get(
                "availability_status"
            )

            allowed = {
                value
                for value, _label
                in (
                    ServiceProviderProfile
                    ._meta
                    .get_field(
                        "availability_status"
                    )
                    .choices
                )
            }

            if availability in allowed:
                provider.availability_status = (
                    availability
                )

                provider.availability_note = (
                    request.POST.get(
                        "availability_note",
                        "",
                    )[:300]
                )

                provider.save(
                    update_fields=[
                        "availability_status",
                        "availability_note",
                        "updated_at",
                    ]
                )

                messages.success(
                    request,
                    "Availability updated.",
                )

            else:
                messages.error(
                    request,
                    (
                        "Select a valid "
                        "availability status."
                    ),
                )

            return redirect(
                "installers:provider_dashboard"
            )

        if action == "update_quote_status":
            quote = get_object_or_404(
                ServiceQuoteRequest,
                pk=request.POST.get(
                    "quote_id"
                ),
                provider=provider,
            )

            next_status = request.POST.get(
                "status"
            )

            allowed_statuses = {
                value
                for value, _label
                in ServiceQuoteRequest.STATUS_CHOICES
            }

            if next_status in allowed_statuses:
                quote.status = next_status

                quote.provider_note = (
                    request.POST.get(
                        "provider_note",
                        quote.provider_note,
                    )[:2000]
                )

                if (
                    next_status == "accepted"
                    and not quote.accepted_at
                ):
                    quote.accepted_at = (
                        timezone.now()
                    )

                if (
                    next_status == "completed"
                    and not quote.completed_at
                ):
                    quote.completed_at = (
                        timezone.now()
                    )

                quote.save(
                    update_fields=[
                        "status",
                        "provider_note",
                        "accepted_at",
                        "completed_at",
                        "updated_at",
                    ]
                )

                messages.success(
                    request,
                    "Service request updated.",
                )

            else:
                messages.error(
                    request,
                    (
                        "Select a valid service "
                        "request status."
                    ),
                )

            return redirect(
                "installers:provider_dashboard"
            )

    quote_requests = (
        provider.quote_requests
        .select_related(
            "product",
            "category",
        )
        .order_by(
            "-created_at"
        )
    )

    active_jobs = quote_requests.filter(
        status__in=[
            "assigned",
            "accepted",
            "on_the_way",
            "in_progress",
        ]
    )

    pending_jobs = quote_requests.filter(
        status__in=[
            "new",
            "under_review",
            "assigned",
        ]
    )

    completed_jobs = quote_requests.filter(
        status__in=[
            "completed",
            "closed",
        ]
    )

    notifications = (
        Notification.objects
        .filter(
            user=request.user
        )
        .order_by(
            "-created_at"
        )[:8]
    )

    effective_subscription = get_effective_subscription(
        request.user,
        role_context="provider",
    )
    subscription_plans = official_plans()

    return render(
        request,
        "installers/provider_dashboard.html",
        {
            "provider": provider,
            "services": (
                provider.services
                .select_related(
                    "category"
                )
            ),
            "portfolio_items": (
                provider.portfolio_items
                .all()
            ),
            "project_entitlements": (
                ProjectEntitlementService(
                    provider
                ).payload()
            ),
            "quote_requests": (
                quote_requests[:30]
            ),
            "active_jobs": (
                active_jobs[:8]
            ),
            "pending_jobs": (
                pending_jobs[:8]
            ),
            "completed_jobs": (
                completed_jobs[:8]
            ),
            "quote_request_count": (
                quote_requests.count()
            ),
            "pending_job_count": (
                pending_jobs.count()
            ),
            "active_job_count": (
                active_jobs.count()
            ),
            "completed_job_count": (
                completed_jobs.count()
            ),
            "urgent_job_count": (
                quote_requests
                .filter(
                    Q(
                        urgency="urgent"
                    )
                    | Q(
                        urgency="emergency"
                    )
                )
                .exclude(
                    status__in=[
                        "completed",
                        "closed",
                        "cancelled",
                    ]
                )
                .count()
            ),
            "kyc_documents": (
                provider.kyc_documents
                .filter(
                    is_active=True
                )
            ),
            "change_requests": (
                provider.profile_change_requests
                .all()[:8]
            ),
            "notifications": notifications,
            "subscription_plans": (
                subscription_plans
            ),
            "effective_subscription": (
                effective_subscription.as_dict()
            ),
            "availability_choices": (
                ServiceProviderProfile
                ._meta
                .get_field(
                    "availability_status"
                )
                .choices
            ),
            "quote_status_choices": (
                ServiceQuoteRequest.STATUS_CHOICES
            ),
        },
    )



# =============================================================================
# WORKSPACE DASHBOARD
# =============================================================================


@login_required
def workspace_dashboard(request):
    """
    Canonical provider operations dashboard at /dashboard/provider/.
    """

    provider = (
        ServiceProviderProfile.objects
        .select_related(
            "user"
        )
        .filter(
            user=request.user
        )
        .first()
    )

    if provider is None:
        messages.info(
            request,
            (
                "Set up your Provider Profile to open "
                "the Provider Dashboard."
            ),
        )
        return redirect(
            "installers:register"
        )

    if not provider.approval_allows_dashboard:
        return redirect(
            "installers:provider_dashboard"
        )

    quotes = provider.quote_requests.all()

    projects = (
        provider.portfolio_items
        .all()
    )

    notifications = Notification.objects.filter(
        user=request.user,
        is_archived=False,
    )

    context = _workspace_context(
        provider,
        "dashboard",
    )

    context.update(
        {
            "cards": {
                "services": (
                    provider.services
                    .filter(
                        is_active=True
                    )
                    .count()
                ),
                "projects": (
                    projects.count()
                ),
                "approved_projects": (
                    provider.approved_project_count
                ),
                "project_media": (
                    projects.aggregate(
                        total=Count(
                            "media_items"
                        )
                    )["total"]
                    or 0
                ),
                "views": (
                    provider.project_views_count
                ),
                "video_views": (
                    provider.project_video_views_count
                ),
                "leads": (
                    provider.project_leads_count
                ),
                "quotes": (
                    quotes.count()
                ),
                "active_jobs": (
                    quotes.filter(
                        status__in=[
                            "assigned",
                            "accepted",
                            "on_the_way",
                            "in_progress",
                        ]
                    ).count()
                ),
                "completed_jobs": (
                    quotes.filter(
                        status__in=[
                            "completed",
                            "closed",
                        ]
                    ).count()
                ),
                "reviews": (
                    provider.total_reviews
                ),
                "unread_notifications": (
                    notifications.filter(
                        is_read=False
                    ).count()
                ),
            },
            "recent_projects": (
                projects
                .select_related(
                    "service_category"
                )
                .order_by(
                    "-updated_at"
                )[:4]
            ),
            "recent_jobs": (
                quotes
                .select_related(
                    "category",
                    "product",
                )
                .order_by(
                    "-updated_at"
                )[:5]
            ),
            "recent_notifications": (
                notifications
                .order_by(
                    "-created_at"
                )[:5]
            ),
        }
    )

    return render(
        request,
        "installers/workspace/dashboard.html",
        context,
    )


# =============================================================================
# WORKSPACE PROFILE
# =============================================================================


@login_required
def workspace_profile(request):
    provider = _provider_workspace(
        request
    )

    form = ProviderWorkspaceProfileForm(
        request.POST or None,
        instance=provider,
    )

    # -------------------------------------------------------------------------
    # TEXT PROFILE UPDATE
    # -------------------------------------------------------------------------

    if (
        request.method == "POST"
        and request.POST.get("action") == "profile"
        and form.is_valid()
    ):
        try:
            provider, change = update_provider_profile(
                provider,
                form.cleaned_data,
                user=request.user,
            )

        except Exception as exc:
            messages.error(
                request,
                str(exc),
            )

        else:
            messages.success(
                request,
                (
                    "Sensitive changes were submitted "
                    "for approval."
                    if change
                    else "Profile updated."
                ),
            )

            return redirect(
                "provider_workspace:profile"
            )

    # -------------------------------------------------------------------------
    # MEDIA UPDATE
    # -------------------------------------------------------------------------

    if (
        request.method == "POST"
        and request.POST.get("action") == "media"
    ):
        field_name = (
            request.POST.get(
                "field_name",
                "",
            )
            or ""
        ).strip()

        upload = request.FILES.get(
            "file"
        )

        allowed_fields = {
            "profile_image",
            "business_logo",
            "business_banner",
        }

        if field_name not in allowed_fields:
            messages.error(
                request,
                (
                    "Choose a valid provider "
                    "image type."
                ),
            )

        elif upload is None:
            messages.error(
                request,
                "Choose an image to upload.",
            )

        else:
            try:
                validate_private_profile_image_upload(
                    upload
                )

            except ValidationError as exc:
                _show_validation_errors(
                    request,
                    exc,
                )

            else:
                try:
                    upload.seek(0)
                except Exception:
                    pass

                # -------------------------------------------------------------
                # APPROVED PROVIDER:
                # CREATE REVIEWABLE CHANGE REQUEST
                # -------------------------------------------------------------

                if provider.approval_allows_dashboard:
                    if provider.sensitive_update_locked:
                        messages.error(
                            request,
                            (
                                "Sensitive profile changes "
                                "are locked until "
                                f"{provider.sensitive_update_available_at:%Y-%m-%d}."
                            ),
                        )

                    elif (
                        provider.profile_change_requests
                        .filter(
                            status=(
                                ProviderProfileChangeRequest
                                .STATUS_PENDING
                            )
                        )
                        .exists()
                    ):
                        messages.error(
                            request,
                            (
                                "A profile change is already "
                                "awaiting Arolana approval."
                            ),
                        )

                    else:
                        current_field = getattr(
                            provider,
                            field_name,
                            None,
                        )

                        current_name = (
                            getattr(
                                current_field,
                                "name",
                                "",
                            )
                            or ""
                        )

                        change_request = (
                            ProviderProfileChangeRequest(
                                provider=provider,
                                requested_by=request.user,
                                old_values={
                                    field_name: current_name,
                                },
                                proposed_values={
                                    field_name: upload.name,
                                },
                                sensitive_fields=[
                                    field_name,
                                ],
                                proposed_file=upload,
                                proposed_file_field=(
                                    field_name
                                ),
                            )
                        )

                        try:
                            change_request.full_clean()

                            with transaction.atomic():
                                change_request.save()

                        except ValidationError as exc:
                            _show_validation_errors(
                                request,
                                exc,
                            )

                        else:
                            messages.success(
                                request,
                                (
                                    "Provider image submitted "
                                    "for Arolana approval."
                                ),
                            )

                            return redirect(
                                "provider_workspace:profile"
                            )

                # -------------------------------------------------------------
                # PRE-APPROVAL PROVIDER:
                # DIRECT PROFILE IMAGE SAVE
                # -------------------------------------------------------------

                else:
                    setattr(
                        provider,
                        field_name,
                        upload,
                    )

                    try:
                        provider.save(
                            update_fields=[
                                field_name,
                                "updated_at",
                            ]
                        )

                    except Exception as exc:
                        messages.error(
                            request,
                            (
                                "The provider image could "
                                f"not be saved: {exc}"
                            ),
                        )

                    else:
                        messages.success(
                            request,
                            "Provider image saved.",
                        )

                        return redirect(
                            "provider_workspace:profile"
                        )

    context = _workspace_context(
        provider,
        "profile",
    )

    context.update(
        {
            "form": form,
            "pending_changes": (
                provider.profile_change_requests
                .filter(
                    status=(
                        ProviderProfileChangeRequest
                        .STATUS_PENDING
                    )
                )
            ),
        }
    )

    return render(
        request,
        "installers/workspace/profile.html",
        context,
    )


# =============================================================================
# WORKSPACE SERVICES
# =============================================================================


@login_required
def workspace_services(
    request,
    service_id=None,
):
    provider = _provider_workspace(
        request
    )

    service = (
        get_object_or_404(
            provider.services,
            pk=service_id,
        )
        if service_id
        else None
    )

    form = ProviderServiceForm(
        request.POST or None,
        instance=service,
    )

    if request.method == "POST":
        action = request.POST.get(
            "action",
            "save",
        )

        if (
            action in {"delete", "deactivate"}
            and service
        ):
            service.is_active = False

            service.save(
                update_fields=[
                    "is_active",
                    "updated_at",
                ]
            )

            messages.success(
                request,
                (
                    "Service deactivated. "
                    "Historical requests remain intact."
                ),
            )

            return redirect(
                "provider_workspace:services"
            )

        if action == "activate" and service:
            access = ProviderServicePolicy(provider).can_activate(service=service)
            if not access.allowed:
                messages.error(request, access.message)
            else:
                service.is_active = True
                service.save(update_fields=["is_active", "updated_at"])
                messages.success(request, "Service activated and visible to customers.")
            return redirect("provider_workspace:services")
        if form.is_valid():
            offering = form.save(
                commit=False
            )

            offering.provider = provider
            access = ProviderServicePolicy(provider).can_activate(service=offering)
            if offering.is_active and not access.allowed:
                form.add_error(None, access.message)
            else:
                offering.save()
                messages.success(request, "Service offering saved.")
                return redirect("provider_workspace:services")
    service_access = ProviderServicePolicy(provider).payload(service=service)
    context = _workspace_context(provider, "services")
    context.update({
        "services": provider.services.select_related("category"),
        "form": form,
        "editing_service": service,
        "service_access": service_access,
    })
    return render(request, "installers/workspace/services.html", context)


# =============================================================================
# WORKSPACE AVAILABILITY
# =============================================================================


@login_required
def workspace_availability(request):
    provider = _provider_workspace(
        request
    )

    form = ProviderAvailabilityForm(
        request.POST or None,
        instance=provider,
    )

    if (
        request.method == "POST"
        and form.is_valid()
    ):
        form.save()

        messages.success(
            request,
            (
                "Coverage and availability updated."
            ),
        )

        return redirect(
            "provider_workspace:availability"
        )

    context = _workspace_context(
        provider,
        "availability",
    )

    context["form"] = form

    return render(
        request,
        "installers/workspace/form_page.html",
        {
            **context,
            "page_title": (
                "Coverage & Availability"
            ),
            "page_subtitle": (
                "Control where and when customers "
                "can request your services."
            ),
            "submit_label": (
                "Save availability"
            ),
        },
    )


# =============================================================================
# WORKSPACE KYC
# =============================================================================


@login_required
def workspace_kyc(request):
    provider = _provider_workspace(
        request
    )

    if request.method == "POST":
        pending_documents = []

        # ---------------------------------------------------------------------
        # VALIDATE EVERY SUBMITTED DOCUMENT BEFORE SAVING ANY
        # ---------------------------------------------------------------------

        for (
            document_type,
            _label,
        ) in ProviderKYCDocument.DOCUMENT_TYPES:
            upload = request.FILES.get(
                document_type
            )

            if not upload:
                continue

            document = ProviderKYCDocument(
                provider=provider,
                document_type=document_type,
                file=upload,
            )

            try:
                document.full_clean()

            except ValidationError as exc:
                label = dict(
                    ProviderKYCDocument.DOCUMENT_TYPES
                ).get(
                    document_type,
                    document_type,
                )

                messages.error(
                    request,
                    f"{label}: upload rejected.",
                )

                _show_validation_errors(
                    request,
                    exc,
                )

                context = _workspace_context(
                    provider,
                    "kyc",
                )

                context["documents"] = (
                    provider.kyc_documents
                    .filter(
                        is_active=True
                    )
                )

                return render(
                    request,
                    "installers/workspace/kyc.html",
                    context,
                )

            pending_documents.append(
                document
            )

        if not pending_documents:
            messages.error(
                request,
                (
                    "Choose at least one "
                    "KYC document."
                ),
            )

        else:
            try:
                with transaction.atomic():
                    for document in pending_documents:
                        document.save()

                    submit_provider_kyc(
                        provider
                    )

            except Exception as exc:
                messages.error(
                    request,
                    (
                        "The KYC submission could "
                        f"not be completed: {exc}"
                    ),
                )

            else:
                messages.success(
                    request,
                    (
                        "KYC documents submitted "
                        "for Arolana review."
                    ),
                )

                return redirect(
                    "provider_workspace:kyc"
                )

    context = _workspace_context(
        provider,
        "kyc",
    )

    context["documents"] = (
        provider.kyc_documents
        .filter(
            is_active=True
        )
    )

    return render(
        request,
        "installers/workspace/kyc.html",
        context,
    )


# =============================================================================
# WORKSPACE SETTINGS
# =============================================================================


@login_required
def workspace_settings(request):
    provider = _provider_workspace(
        request
    )

    form = ProviderWorkspaceSettingsForm(
        request.POST or None,
        instance=provider,
    )

    if (
        request.method == "POST"
        and form.is_valid()
    ):
        form.save()

        messages.success(
            request,
            "Provider settings saved.",
        )

        return redirect(
            "provider_workspace:settings"
        )

    context = _workspace_context(
        provider,
        "settings",
    )

    context["form"] = form

    return render(
        request,
        "installers/workspace/form_page.html",
        {
            **context,
            "page_title": (
                "Provider Settings"
            ),
            "page_subtitle": (
                "Manage support contacts, payout details, "
                "language, and notifications."
            ),
            "submit_label": (
                "Save settings"
            ),
        },
    )


# =============================================================================
# WORKSPACE ANALYTICS
# =============================================================================


@login_required
def workspace_analytics(request):
    provider = _provider_workspace(
        request
    )

    projects = (
        provider.portfolio_items
        .all()
    )

    context = _workspace_context(
        provider,
        "analytics",
    )

    context.update(
        {
            "totals": projects.aggregate(
                views=Sum(
                    "views_count"
                ),
                video_views=Sum(
                    "video_views_count"
                ),
                product_clicks=Sum(
                    "product_click_count"
                ),
                provider_clicks=Sum(
                    "provider_click_count"
                ),
                leads=Sum(
                    "quote_requests_count"
                ),
                shares=Sum(
                    "shares_count"
                ),
                saves=Sum(
                    "saves_count"
                ),
            ),
            "projects": (
                projects.order_by(
                    "-views_count"
                )[:12]
            ),
        }
    )

    return render(
        request,
        "installers/workspace/analytics.html",
        context,
    )


# =============================================================================
# WORKSPACE NOTIFICATIONS
# =============================================================================


@login_required
def workspace_notifications(request):
    provider = _provider_workspace(
        request
    )

    notifications = (
        Notification.objects
        .filter(
            user=request.user,
            is_archived=False,
        )
        .order_by(
            "-created_at"
        )
    )

    if request.method == "POST":
        notifications.filter(
            is_read=False
        ).update(
            is_read=True
        )

        return redirect(
            "provider_workspace:notifications"
        )

    context = _workspace_context(
        provider,
        "notifications",
    )

    context["notifications"] = (
        notifications[:100]
    )

    return render(
        request,
        "installers/workspace/notifications.html",
        context,
    )


# =============================================================================
# ADD PROVIDER SERVICE
# =============================================================================


@login_required
def add_provider_service(request):
    provider = get_object_or_404(
        ServiceProviderProfile,
        user=request.user,
    )

    form = ProviderServiceForm(
        request.POST or None
    )

    if (
        request.method == "POST"
        and form.is_valid()
    ):
        service = form.save(
            commit=False
        )

        service.provider = provider
        access = ProviderServicePolicy(provider).can_activate(service=service)
        if service.is_active and not access.allowed:
            form.add_error(None, access.message)
        else:
            service.save()
            messages.success(request, "Service added.")
            return redirect("provider_workspace:services")
    return render(request, "installers/simple_form.html", {
        "form": form,
        "title": "Add service",
        "service_access": ProviderServicePolicy(provider).payload(),
    })


# =============================================================================
# ADD PORTFOLIO
# =============================================================================


@login_required
def add_portfolio(request):
    provider = get_object_or_404(
        ServiceProviderProfile,
        user=request.user,
    )

    entitlement = (
        ProjectEntitlementService(
            provider
        ).can_create_project()
    )

    if not entitlement.allowed:
        messages.error(
            request,
            entitlement.message,
        )

        return redirect(
            "provider_workspace:projects"
        )

    form = ServicePortfolioForm(
        request.POST or None,
        request.FILES or None,
    )

    if (
        request.method == "POST"
        and form.is_valid()
    ):
        portfolio = form.save(
            commit=False
        )

        portfolio.provider = provider
        portfolio.created_by = request.user

        portfolio.approval_status = (
            ServicePortfolio.STATUS_DRAFT
        )

        portfolio.save()

        form.instance = portfolio

        form.save()

        messages.success(
            request,
            "Portfolio project added.",
        )

        return redirect(
            "provider_workspace:project_edit",
            project_id=portfolio.id,
        )

    return render(
        request,
        "installers/project_form.html",
        {
            "form": form,
            "title": (
                "Add completed project"
            ),
            "provider": provider,
            "entitlements": (
                ProjectEntitlementService(
                    provider
                ).payload()
            ),
            "media_summary": _project_media_summary(None),
        },
    )


# =============================================================================
# PROJECT DIRECTORY
# =============================================================================


def projects_directory(request):
    projects = (
        ServicePortfolio.objects
        .public()
        .optimized()
    )

    query = (
        request.GET.get(
            "q"
        )
        or ""
    ).strip()

    if query:
        projects = projects.filter(
            Q(
                title__icontains=query
            )
            | Q(
                short_summary__icontains=query
            )
            | Q(
                provider__business_name__icontains=query
            )
            | Q(
                service_category__name__icontains=query
            )
            | Q(
                city__icontains=query
            )
            | Q(
                state__icontains=query
            )
            | Q(
                project_products__product__name__icontains=query
            )
        ).distinct()

    filters = {
        "service_category__slug": (
            request.GET.get(
                "category"
            )
        ),
        "country__iexact": (
            request.GET.get(
                "country"
            )
        ),
        "state__iexact": (
            request.GET.get(
                "state"
            )
        ),
        "city__iexact": (
            request.GET.get(
                "city"
            )
        ),
        "project_type": (
            request.GET.get(
                "project_type"
            )
        ),
        "project_products__product_id": (
            request.GET.get(
                "product"
            )
        ),
    }

    for key, value in filters.items():
        if value:
            projects = projects.filter(
                **{
                    key: value,
                }
            )

    ordering = {
        "popular": "-views_count",
        "watched": "-video_views_count",
        "requested": "-quote_requests_count",
        "latest": "-published_at",
    }.get(
        request.GET.get(
            "sort"
        ),
        "-is_featured",
    )

    projects = projects.order_by(
        ordering,
        "-published_at",
    )

    page = Paginator(
        projects,
        18,
    ).get_page(
        request.GET.get(
            "page"
        )
    )

    categories = (
        ServiceCategory.objects
        .filter(
            is_active=True,
            projects__approval_status=(
                ServicePortfolio.STATUS_APPROVED
            ),
            projects__is_active=True,
        )
        .annotate(
            project_count=Count(
                "projects",
                distinct=True,
            )
        )
        .distinct()
    )

    return render(
        request,
        "installers/projects_directory.html",
        {
            "projects": page.object_list,
            "page_obj": page,
            "categories": categories,
            "featured_projects": (
                ServicePortfolio.objects
                .public()
                .optimized()
                .filter(
                    is_featured=True
                )[:6]
            ),
            "project_types": (
                ServicePortfolio.PROJECT_TYPE_CHOICES
            ),
            "seo_title": (
                "Real Installations & Completed Projects | Arolana"
            ),
            "seo_description": (
                "Watch verified installations, completed "
                "technical projects, and real professional "
                "work on Arolana."
            ),
        },
    )


# =============================================================================
# PROJECT DETAIL
# =============================================================================


def project_detail(
    request,
    slug,
):
    project = get_object_or_404(
        ServicePortfolio.objects
        .public()
        .optimized(),
        slug=slug,
    )

    record_project_event(
        project,
        "view",
        request=request,
        source="web",
    )

    # Keep the approved media prefetch attached to this instance. Refreshing
    # here discarded ``_public_media_items`` and caused the public gallery to
    # issue extra queries or fall back to legacy media unexpectedly.
    project_gallery = resolve_project_gallery_media(project)
    project_gallery_groups = group_project_gallery_media(project)
    has_normalized_video = any(
        item.kind == ServiceProjectMedia.TYPE_VIDEO
        for item in project_gallery
    )

    related = (
        ServicePortfolio.objects
        .public()
        .optimized()
        .filter(
            service_category=(
                project.service_category
            )
        )
        .exclude(
            pk=project.pk
        )[:6]
    )

    similar_providers = (
        ServiceProviderProfile.objects
        .public()
        .filter(
            services__category=(
                project.service_category
            )
        )
        .exclude(
            pk=project.provider_id
        )
        .distinct()[:4]
    )

    return render(
        request,
        "installers/project_detail.html",
        {
            "project": project,
            "media_items": (
                project.public_media
            ),
            "project_gallery": project_gallery,
            "project_gallery_groups": project_gallery_groups,
            "has_normalized_video": has_normalized_video,
            "is_landing_page": True,
            "products_used": (
                project.project_products
                .select_related(
                    "product",
                    "product__vendor",
                )
            ),
            "related_projects": related,
            "similar_providers": (
                similar_providers
            ),
            "is_saved": (
                request.user.is_authenticated
                and (
                    SavedServiceProject.objects
                    .filter(
                        project=project,
                        user=request.user,
                    )
                    .exists()
                )
            ),
            "seo_title": (
                f"{project.title} "
                "| Arolana Projects"
            ),
            "seo_description": (
                project.short_summary
                or project.description[:160]
            ),
        },
    )


# =============================================================================
# SAVE PROJECT
# =============================================================================


@login_required
def save_project(
    request,
    slug,
):
    project = get_object_or_404(
        ServicePortfolio.objects.public(),
        slug=slug,
    )

    saved, created = (
        SavedServiceProject.objects
        .get_or_create(
            project=project,
            user=request.user,
        )
    )

    if not created:
        saved.delete()

        if project.saves_count:
            ServicePortfolio.objects.filter(
                pk=project.pk
            ).update(
                saves_count=(
                    project.saves_count
                    - 1
                )
            )

        messages.info(
            request,
            (
                "Project removed from saved items."
            ),
        )

    else:
        record_project_event(
            project,
            "save",
            request=request,
            source="web",
        )

        messages.success(
            request,
            "Project saved.",
        )

    return redirect(
        project.get_absolute_url()
    )


# =============================================================================
# PROVIDER PROJECTS
# =============================================================================


@login_required
def provider_projects(request):
    provider = get_object_or_404(
        ServiceProviderProfile,
        user=request.user,
    )

    projects = (
        provider.portfolio_items
        .select_related(
            "service_category"
        )
        .prefetch_related(
            "media_items"
        )
    )

    totals = projects.aggregate(
        views=Sum(
            "views_count"
        ),
        video_views=Sum(
            "video_views_count"
        ),
        leads=Sum(
            "quote_requests_count"
        ),
    )

    return render(
        request,
        "installers/provider_projects.html",
        {
            "provider": provider,
            "projects": projects,
            "entitlements": (
                ProjectEntitlementService(
                    provider
                ).payload()
            ),
            "workspace_active": "projects",
            "profile_steps": (
                provider.profile_completion_items
            ),
            "profile_missing_steps": (
                provider.profile_missing_steps
            ),
            "project_entitlements": (
                ProjectEntitlementService(
                    provider
                ).payload()
            ),
            "totals": totals,
            "status_counts": {
                value: projects.filter(
                    approval_status=value
                ).count()
                for value, _label
                in (
                    ServicePortfolio
                    .APPROVAL_STATUS_CHOICES
                )
            },
        },
    )


# =============================================================================
# PROVIDER PROJECT EDIT
# =============================================================================


@login_required
def provider_project_edit(
    request,
    project_id,
):
    provider = get_object_or_404(
        ServiceProviderProfile,
        user=request.user,
    )

    project = get_object_or_404(
        provider.portfolio_items,
        pk=project_id,
    )

    form = ServicePortfolioForm(
        request.POST or None,
        request.FILES or None,
        instance=project,
    )

    if (
        request.method == "POST"
        and form.is_valid()
    ):
        project = form.save(
            commit=False
        )

        if (
            project.approval_status
            == ServicePortfolio.STATUS_APPROVED
        ):
            project.approval_status = (
                ServicePortfolio.STATUS_PENDING
            )

        project.save()

        form.save()

        action = request.POST.get(
            "action"
        )

        if action == "submit":
            publish_permission = (
                ProjectEntitlementService(
                    provider
                ).can_publish_project()
            )

            if not publish_permission.allowed:
                messages.error(
                    request,
                    publish_permission.message,
                )

            elif project.completion_percent < 60:
                messages.error(
                    request,
                    (
                        "Complete the category, location, "
                        "story, outcome, and media before "
                        "submission."
                    ),
                )

            else:
                project.approval_status = (
                    ServicePortfolio.STATUS_PENDING
                )

                project.moderation_notes = ""

                project.save(
                    update_fields=[
                        "approval_status",
                        "moderation_notes",
                        "updated_at",
                    ]
                )

                notify_project_submitted(
                    project
                )

                messages.success(
                    request,
                    (
                        "Project submitted for "
                        "Arolana review."
                    ),
                )

        else:
            messages.success(
                request,
                "Project draft saved.",
            )

        return redirect(
            "provider_workspace:project_edit",
            project_id=project.id,
        )

    return render(
        request,
        "installers/project_form.html",
        {
            "form": form,
            "project": project,
            "provider": provider,
            "title": (
                f"Edit {project.title}"
            ),
            "entitlements": (
                ProjectEntitlementService(
                    provider
                ).payload()
            ),
            "media_summary": _project_media_summary(project),
        },
    )


# =============================================================================
# PROVIDER PROJECT MEDIA
# =============================================================================


@login_required
def provider_project_media(
    request,
    project_id,
):
    provider = get_object_or_404(
        ServiceProviderProfile,
        user=request.user,
    )

    project = get_object_or_404(
        provider.portfolio_items,
        pk=project_id,
    )

    entitlement_service = ProjectEntitlementService(
        provider
    )
    entitlements = entitlement_service.payload()
    form = ServiceProjectBulkMediaForm(
        request.POST or None,
        request.FILES or None,
    )
    if not entitlements.get("external_video_allowed", True):
        form.fields["external_video_url"].widget.attrs.update(
            {
                "disabled": "disabled",
                "aria-disabled": "true",
            }
        )

    if request.method == "POST":
        action = (
            request.POST.get("action")
            or "upload"
        ).strip()

        if action in {
            "delete",
            "set_cover",
            "update",
            "move_up",
            "move_down",
        }:
            media = get_object_or_404(
                project.media_items,
                pk=request.POST.get("media_id"),
            )

            if action == "delete":
                media.delete()
                messages.success(
                    request,
                    "Project media removed.",
                )

            elif action == "set_cover":
                if media.media_type != ServiceProjectMedia.TYPE_IMAGE:
                    messages.error(
                        request,
                        "Only an image can be the project cover.",
                    )
                else:
                    media.is_cover = True
                    media.is_featured = True
                    media.save(
                        update_fields=[
                            "is_cover",
                            "is_featured",
                            "updated_at",
                        ]
                    )
                    messages.success(
                        request,
                        "Project cover updated.",
                    )

            elif action == "update":
                allowed_stages = {
                    value
                    for value, _label
                    in ServiceProjectMedia.STAGE_CHOICES
                }
                stage = request.POST.get("stage", "")
                stage_is_valid = stage in allowed_stages
                if (
                    stage == ServiceProjectMedia.STAGE_SUPPORTING_DOCUMENT
                    and media.media_type != ServiceProjectMedia.TYPE_DOCUMENT
                ):
                    stage_is_valid = False
                    messages.error(
                        request,
                        "Supporting document is only valid for document media.",
                    )
                if (
                    stage == ServiceProjectMedia.STAGE_COVER
                    and media.media_type != ServiceProjectMedia.TYPE_IMAGE
                ):
                    stage_is_valid = False
                    messages.error(
                        request,
                        "Only an image can use the cover stage.",
                    )
                if not stage_is_valid:
                    return redirect(
                        "provider_workspace:project_media",
                        project_id=project.id,
                    )
                media.stage = stage
                media.caption = (
                    request.POST.get("caption", "")
                    or ""
                ).strip()[:300]
                media.alt_text = (
                    request.POST.get("alt_text", "")
                    or ""
                ).strip()[:220]
                media.is_featured = bool(
                    request.POST.get("is_featured")
                )
                media.save(
                    update_fields=[
                        "stage",
                        "caption",
                        "alt_text",
                        "is_featured",
                        "updated_at",
                    ]
                )
                messages.success(
                    request,
                    "Media details saved.",
                )

            else:
                ordered_media = list(
                    project.media_items.order_by(
                        "display_order",
                        "id",
                    )
                )
                current_index = next(
                    (
                        index
                        for index, item in enumerate(ordered_media)
                        if item.pk == media.pk
                    ),
                    None,
                )
                offset = -1 if action == "move_up" else 1
                target_index = (
                    current_index + offset
                    if current_index is not None
                    else -1
                )

                if 0 <= target_index < len(ordered_media):
                    ordered_media[current_index], ordered_media[target_index] = (
                        ordered_media[target_index],
                        ordered_media[current_index],
                    )
                    for position, item in enumerate(ordered_media, start=1):
                        if item.display_order != position:
                            item.display_order = position
                            item.save(
                                update_fields=[
                                    "display_order",
                                    "updated_at",
                                ]
                            )
                    messages.success(
                        request,
                        "Project media order updated.",
                    )

            return redirect(
                "provider_workspace:project_media",
                project_id=project.id,
            )

        if form.is_valid():
            files = form.cleaned_data.get("files") or []
            external_video_url = (
                form.cleaned_data.get("external_video_url")
                or ""
            ).strip()
            requested_count = len(files) + bool(
                external_video_url
            )

            image_extensions = {
                ".jpg", ".jpeg", ".png", ".webp",
                ".avif", ".gif",
            }
            video_extensions = {
                ".mp4", ".webm", ".mov", ".m4v",
            }
            classified_files = []

            for upload in files:
                content_type = (
                    getattr(upload, "content_type", "")
                    or ""
                ).lower()
                suffix = Path(
                    getattr(upload, "name", "")
                ).suffix.lower()

                if (
                    content_type.startswith("image/")
                    or suffix in image_extensions
                ):
                    media_type = ServiceProjectMedia.TYPE_IMAGE
                elif (
                    content_type.startswith("video/")
                    or suffix in video_extensions
                ):
                    media_type = ServiceProjectMedia.TYPE_VIDEO
                else:
                    media_type = ServiceProjectMedia.TYPE_DOCUMENT

                classified_files.append(
                    (upload, media_type)
                )

            overall_permission = (
                entitlement_service.can_add_project_media(
                    project,
                    requested_count=requested_count,
                )
            )
            video_count = sum(
                media_type == ServiceProjectMedia.TYPE_VIDEO
                for _upload, media_type in classified_files
            ) + bool(external_video_url)
            image_count = sum(
                media_type == ServiceProjectMedia.TYPE_IMAGE
                for _upload, media_type in classified_files
            )
            document_count = sum(
                media_type == ServiceProjectMedia.TYPE_DOCUMENT
                for _upload, media_type in classified_files
            )
            image_permission = (
                entitlement_service.can_add_project_media(
                    project,
                    requested_count=image_count,
                    media_type=ServiceProjectMedia.TYPE_IMAGE,
                )
                if image_count
                else None
            )
            video_permission = (
                entitlement_service.can_add_project_media(
                    project,
                    requested_count=video_count,
                    media_type=ServiceProjectMedia.TYPE_VIDEO,
                )
                if video_count
                else None
            )
            document_permission = (
                entitlement_service.can_add_project_media(
                    project,
                    requested_count=document_count,
                    media_type=ServiceProjectMedia.TYPE_DOCUMENT,
                )
                if document_count
                else None
            )
            local_video_permission = (
                entitlement_service.can_upload_local_video(
                    project,
                    requested_count=sum(
                        media_type == ServiceProjectMedia.TYPE_VIDEO
                        for _upload, media_type in classified_files
                    ),
                )
                if any(
                    media_type == ServiceProjectMedia.TYPE_VIDEO
                    for _upload, media_type in classified_files
                )
                else None
            )
            external_video_permission = (
                entitlement_service.can_add_external_video()
                if external_video_url
                else None
            )

            permission_error = ""
            if not overall_permission.allowed:
                permission_error = overall_permission.message
            elif image_permission and not image_permission.allowed:
                permission_error = image_permission.message
            elif video_permission and not video_permission.allowed:
                permission_error = video_permission.message
            elif document_permission and not document_permission.allowed:
                permission_error = document_permission.message
            elif (
                local_video_permission
                and not local_video_permission.allowed
            ):
                permission_error = local_video_permission.message
            elif (
                external_video_permission
                and not external_video_permission.allowed
            ):
                permission_error = external_video_permission.message

            max_video_size_mb = int(
                entitlements.get("max_video_size_mb", 0)
                or 0
            )

            if permission_error:
                messages.error(
                    request,
                    permission_error,
                )
            else:
                try:
                    for upload, media_type in classified_files:
                        if media_type == ServiceProjectMedia.TYPE_VIDEO:
                            validate_project_video_upload(upload)
                            if (
                                max_video_size_mb > 0
                                and int(getattr(upload, "size", 0) or 0)
                                > max_video_size_mb * 1024 * 1024
                            ):
                                raise ValidationError(
                                    f"{upload.name} exceeds your plan's "
                                    f"{max_video_size_mb} MB video limit."
                                )
                        elif media_type == ServiceProjectMedia.TYPE_DOCUMENT:
                            validate_project_document_upload(upload)

                    thumbnail = form.cleaned_data.get("thumbnail")
                    stage = form.cleaned_data["stage"]
                    caption = form.cleaned_data.get("caption", "")
                    alt_text = form.cleaned_data.get("alt_text", "")
                    requested_order = form.cleaned_data.get(
                        "display_order_start"
                    )
                    next_order = requested_order
                    if next_order is None:
                        next_order = (
                            project.media_items.aggregate(
                                value=Max("display_order")
                            )["value"]
                            or 0
                        ) + 1
                    mark_featured = bool(
                        form.cleaned_data.get("mark_featured")
                    )
                    first_image = True
                    thumbnail_used = False

                    with transaction.atomic():
                        for upload, media_type in classified_files:
                            item_stage = stage
                            if media_type == ServiceProjectMedia.TYPE_DOCUMENT:
                                item_stage = (
                                    ServiceProjectMedia.STAGE_SUPPORTING_DOCUMENT
                                )
                            elif stage == ServiceProjectMedia.STAGE_SUPPORTING_DOCUMENT:
                                item_stage = ServiceProjectMedia.STAGE_GENERAL

                            make_cover = bool(
                                media_type == ServiceProjectMedia.TYPE_IMAGE
                                and first_image
                                and form.cleaned_data.get(
                                    "make_first_image_cover"
                                )
                            )
                            media = ServiceProjectMedia(
                                project=project,
                                media_type=media_type,
                                stage=item_stage,
                                caption=caption,
                                alt_text=alt_text,
                                display_order=next_order,
                                uploaded_by=request.user,
                                is_featured=mark_featured or make_cover,
                                is_cover=make_cover,
                            )
                            if media_type == ServiceProjectMedia.TYPE_IMAGE:
                                media.image = upload
                                first_image = False
                            elif media_type == ServiceProjectMedia.TYPE_VIDEO:
                                media.video = upload
                                if thumbnail and not thumbnail_used:
                                    media.thumbnail = thumbnail
                                    thumbnail_used = True
                            else:
                                media.document = upload
                            media.save()
                            next_order += 1

                        if external_video_url:
                            external_media = ServiceProjectMedia(
                                project=project,
                                media_type=ServiceProjectMedia.TYPE_VIDEO,
                                stage=stage,
                                external_video_url=external_video_url,
                                caption=caption,
                                alt_text=alt_text,
                                display_order=next_order,
                                uploaded_by=request.user,
                                is_featured=mark_featured,
                            )
                            if thumbnail and not thumbnail_used:
                                external_media.thumbnail = thumbnail
                            external_media.save()

                except ValidationError as exc:
                    _show_validation_errors(
                        request,
                        exc,
                    )
                except Exception as exc:
                    messages.error(
                        request,
                        str(exc),
                    )
                else:
                    messages.success(
                        request,
                        (
                            f"{requested_count} media item"
                            f"{'s' if requested_count != 1 else ''} "
                            "uploaded for Arolana review."
                        ),
                    )
                    return redirect(
                        "provider_workspace:project_media",
                        project_id=project.id,
                    )

    media_items = list(
        project.media_items.all()
    )
    stage_groups = []
    for stage, label in ServiceProjectMedia.STAGE_CHOICES:
        items = [
            item
            for item in media_items
            if item.stage == stage
        ]
        if items:
            stage_groups.append(
                {
                    "key": stage,
                    "label": label,
                    "items": items,
                }
            )

    media_permission = (
        entitlement_service.can_add_project_media(
            project
        )
    )

    return render(
        request,
        "installers/project_media.html",
        {
            "provider": provider,
            "project": project,
            "media_items": media_items,
            "stage_groups": stage_groups,
            "form": form,
            "media_permission": (
                media_permission.as_dict()
            ),
            "entitlements": (
                entitlements
            ),
            "workspace_active": (
                "projects"
            ),
            "profile_steps": (
                provider.profile_completion_items
            ),
            "profile_missing_steps": (
                provider.profile_missing_steps
            ),
            "project_entitlements": (
                ProjectEntitlementService(
                    provider
                ).payload()
            ),
        },
    )


# =============================================================================
# PROVIDER PROJECT ANALYTICS
# =============================================================================


@login_required
def provider_project_analytics(
    request,
    project_id,
):
    provider = get_object_or_404(
        ServiceProviderProfile,
        user=request.user,
    )

    project = get_object_or_404(
        provider.portfolio_items,
        pk=project_id,
    )

    enabled = (
        ProjectEntitlementService(
            provider
        )
        .payload()[
            "analytics_enabled"
        ]
    )

    return render(
        request,
        "installers/project_analytics.html",
        {
            "provider": provider,
            "project": project,
            "analytics_enabled": enabled,
            "conversion_rate": round(
                (
                    project.quote_requests_count
                    / max(
                        project.views_count,
                        1,
                    )
                    * 100
                ),
                2,
            ),
        },
    )


# =============================================================================
# PROVIDER PROJECT LEADS
# =============================================================================


@login_required
def provider_project_leads(request):
    provider = get_object_or_404(
        ServiceProviderProfile,
        user=request.user,
    )

    leads = (
        provider.quote_requests
        .filter(
            source_project__isnull=False
        )
        .select_related(
            "source_project",
            "source_project__service_category",
        )
    )

    return render(
        request,
        "installers/project_leads.html",
        {
            "provider": provider,
            "leads": leads,
            "entitlements": (
                ProjectEntitlementService(
                    provider
                ).payload()
            ),
            "workspace_active": (
                "project_leads"
            ),
            "profile_steps": (
                provider.profile_completion_items
            ),
            "profile_missing_steps": (
                provider.profile_missing_steps
            ),
            "project_entitlements": (
                ProjectEntitlementService(
                    provider
                ).payload()
            ),
        },
    )


# =============================================================================
# REQUEST QUOTE
# =============================================================================


def request_quote(request):
    initial = {}
    provider_id = request.GET.get(
        "provider"
    )

    category_id = request.GET.get(
        "category"
    )

    product_id = request.GET.get(
        "product"
    )

    project_id = request.GET.get(
        "project"
    )
    service_id = request.GET.get("service")
    if provider_id:
        initial["provider"] = (
            ServiceProviderProfile.objects
            .public()
            .filter(
                pk=provider_id
            )
            .first()
        )

    if category_id:
        initial["category"] = (
            ServiceCategory.objects
            .filter(
                pk=category_id,
                is_active=True,
            )
            .first()
        )

    if product_id:
        product = (
            Product.objects
            .filter(
                pk=product_id,
                is_active=True,
                approval_status="approved",
            )
            .first()
        )

        initial["product"] = product

        if product:
            initial["service_needed"] = (
                f"Service support for "
                f"{product.name}"
            )

    if project_id:
        project = (
            ServicePortfolio.objects
            .public()
            .filter(
                pk=project_id
            )
            .select_related(
                "provider",
                "service_category",
            )
            .first()
        )

        if project:
            initial.update(
                {
                    "source_project": (
                        project
                    ),
                    "provider": (
                        project.provider
                    ),
                    "category": (
                        project.service_category
                    ),
                    "state": (
                        project.state
                    ),
                    "city": (
                        project.city
                    ),
                    "service_needed": (
                        f"Similar project: "
                        f"{project.title}"
                    ),
                    "message": (
                        "I would like a quote for "
                        "a project similar to "
                        f"“{project.title}”."
                    ),
                }
            )

    if service_id:
        service = (
            ProviderService.objects.filter(pk=service_id, is_active=True)
            .select_related("provider", "category")
            .filter(
                provider__is_active=True,
                provider__verification_status__in=(
                    ServiceProviderProfile.STATUS_APPROVED,
                    ServiceProviderProfile.STATUS_VERIFIED,
                ),
            )
            .first()
        )
        if service:
            initial.update({
                "provider": service.provider,
                "category": service.category,
                "service_needed": service.service_name,
                "message": f"I would like a quote for {service.service_name}.",
            })
    if request.user.is_authenticated:
        initial.update(
            {
                "name": (
                    request.user.get_full_name()
                ),
                "email": (
                    request.user.email
                ),
                "phone": (
                    getattr(
                        request.user,
                        "phone_number",
                        "",
                    )
                    or ""
                ),
            }
        )

    form = ServiceQuoteRequestForm(
        request.POST or None,
        initial=initial,
    )

    if (
        request.method == "POST"
        and form.is_valid()
    ):
        quote = form.save(
            commit=False
        )

        if request.user.is_authenticated:
            quote.customer = (
                request.user
            )

        quote.save()

        if quote.source_project:
            record_project_event(
                quote.source_project,
                "quote_request",
                request=request,
                source="web",
            )

        notify_staff_service_quote(
            quote
        )

        if quote.provider:
            Notification.send(
                quote.provider.user,
                "message",
                "New service quote request",
                (
                    f"{quote.name} requested "
                    f"{quote.service_needed} in "
                    f"{quote.city}, {quote.state}."
                ),
                link=(
                    "/dashboard/provider/projects/leads/"
                    if quote.source_project_id
                    else (
                        "/dashboard/provider/"
                        "quote-requests/"
                    )
                ),
                metadata={
                    "type": (
                        "service_quote_request"
                    ),
                    "target_screen": (
                        "ProviderQuoteDetail"
                    ),
                    "role": "provider",
                    "service_quote_request_id": (
                        quote.id
                    ),
                    "quote_id": (
                        quote.id
                    ),
                    "project_id": (
                        quote.source_project_id
                    ),
                    "product_id": (
                        quote.product_id
                    ),
                },
                priority=3,
            )

        messages.success(
            request,
            (
                "Your request has been sent. "
                "A verified professional or "
                "Arolana support will contact you."
            ),
        )

        return redirect(
            "installers:quote_success"
        )

    return render(
        request,
        "installers/quote_form.html",
        {
            "form": form,
        },
    )


def quote_success(request):
    return render(
        request,
        "installers/quote_success.html",
    )


# =============================================================================
# SERVICE REVIEW
# =============================================================================


@login_required
def submit_review(
    request,
    slug,
):
    provider = get_object_or_404(
        ServiceProviderProfile.objects.public(),
        slug=slug,
    )

    form = ServiceReviewForm(
        request.POST or None
    )

    if (
        request.method == "POST"
        and form.is_valid()
    ):
        review = form.save(
            commit=False
        )

        review.provider = provider
        review.customer = request.user

        review.save()

        messages.success(
            request,
            (
                "Thank you. Your review will "
                "appear after moderation."
            ),
        )

        return redirect(
            provider.get_absolute_url()
        )

    return render(
        request,
        "installers/simple_form.html",
        {
            "form": form,
            "title": (
                f"Review {provider.business_name}"
            ),
        },
    )

@login_required
def workspace_quote_requests(request):
    provider = _provider_workspace(request)

    if not provider.approval_allows_dashboard:
        return redirect("installers:provider_dashboard")

    allowed_statuses = {
        value
        for value, _label
        in ServiceQuoteRequest.STATUS_CHOICES
    }

    if request.method == "POST":
        quote = get_object_or_404(
            provider.quote_requests,
            pk=request.POST.get("quote_id"),
        )

        next_status = (
            request.POST.get("status", "")
            or ""
        ).strip()

        if next_status not in allowed_statuses:
            messages.error(
                request,
                "Select a valid service request status.",
            )

            return redirect(
                "provider_workspace:quote_requests"
            )

        quote.status = next_status

        quote.provider_note = (
            request.POST.get("provider_note", "")
            or ""
        ).strip()[:2000]

        update_fields = [
            "status",
            "provider_note",
            "updated_at",
        ]

        if (
            next_status == "accepted"
            and quote.accepted_at is None
        ):
            quote.accepted_at = timezone.now()
            update_fields.append("accepted_at")

        if (
            next_status == "completed"
            and quote.completed_at is None
        ):
            quote.completed_at = timezone.now()
            update_fields.append("completed_at")

        quote.save(
            update_fields=update_fields
        )

        messages.success(
            request,
            "Service request updated.",
        )

        return redirect(
            "provider_workspace:quote_requests"
        )

    all_quotes = (
        provider.quote_requests
        .select_related(
            "product",
            "category",
            "source_project",
            "customer",
        )
        .order_by("-created_at")
    )

    selected_status = (
        request.GET.get("status", "")
        or ""
    ).strip()

    quote_requests = all_quotes

    if selected_status in allowed_statuses:
        quote_requests = quote_requests.filter(
            status=selected_status
        )

    context = _workspace_context(
        provider,
        "quote_requests",
    )

    context.update(
        {
            "quote_requests": quote_requests,
            "quote_status_choices": (
                ServiceQuoteRequest.STATUS_CHOICES
            ),
            "selected_status": selected_status,
            "counts": {
                "all": all_quotes.count(),
                "pending": all_quotes.filter(
                    status__in=[
                        "new",
                        "under_review",
                        "assigned",
                    ]
                ).count(),
                "active": all_quotes.filter(
                    status__in=[
                        "assigned",
                        "accepted",
                        "on_the_way",
                        "in_progress",
                    ]
                ).count(),
                "completed": all_quotes.filter(
                    status__in=[
                        "completed",
                        "closed",
                    ]
                ).count(),
                "urgent": (
                    all_quotes
                    .filter(
                        Q(urgency="urgent")
                        | Q(urgency="emergency")
                    )
                    .exclude(
                        status__in=[
                            "completed",
                            "closed",
                            "cancelled",
                        ]
                    )
                    .count()
                ),
            },
        }
    )

    return render(
        request,
        "installers/workspace/quote_requests.html",
        context,
    )

@login_required
def workspace_reviews(request):
    provider = _provider_workspace(request)

    reviews = (
        provider.reviews
        .select_related("customer")
        .order_by("-created_at")
    )

    approved_reviews = reviews.filter(
        is_approved=True
    )

    pending_reviews = reviews.filter(
        is_approved=False
    )

    averages = approved_reviews.aggregate(
        overall=Avg("rating"),
        professionalism=Avg(
            "professionalism_rating"
        ),
        communication=Avg(
            "communication_rating"
        ),
        quality=Avg(
            "quality_rating"
        ),
        timeliness=Avg(
            "timeliness_rating"
        ),
    )

    rating_distribution = [
        {
            "star": star,
            "count": approved_reviews.filter(
                rating=star
            ).count(),
        }
        for star in range(5, 0, -1)
    ]

    context = _workspace_context(
        provider,
        "reviews",
    )

    context.update(
        {
            "reviews": reviews,
            "approved_reviews": approved_reviews,
            "pending_reviews": pending_reviews,
            "averages": averages,
            "rating_distribution": rating_distribution,
            "counts": {
                "all": reviews.count(),
                "approved": approved_reviews.count(),
                "pending": pending_reviews.count(),
            },
        }
    )

    return render(
        request,
        "installers/workspace/reviews.html",
        context,
    )

@login_required
def workspace_subscription(request):
    provider = _provider_workspace(request)

    plans = (
        ProviderSubscriptionPlan.objects
        .filter(is_active=True)
        .order_by(
            "display_order",
            "price_monthly",
            "name",
        )
    )

    current_plan = (
        plans
        .filter(
            name__iexact=provider.subscription_plan
        )
        .first()
    )

    if request.method == "POST":
        plan = get_object_or_404(
            plans,
            pk=request.POST.get("plan_id"),
        )

        if (
            plan.price_monthly > 0
            or plan.price_yearly > 0
        ):
            billing_cycle = str(
                request.POST.get("billing_cycle") or ""
            ).strip().lower()

            if billing_cycle not in {"monthly", "yearly"}:
                messages.error(
                    request,
                    "Choose monthly or yearly billing.",
                )
                return redirect(
                    "provider_workspace:subscription"
                )

            selected_amount = (
                plan.price_monthly
                if billing_cycle == "monthly"
                else plan.price_yearly
            )

            if selected_amount <= 0:
                messages.error(
                    request,
                    f"{billing_cycle.title()} billing is not available for this plan.",
                )
                return redirect(
                    "provider_workspace:subscription"
                )

            payment = None

            try:
                payment = create_provider_subscription_payment(
                    provider=provider,
                    plan=plan,
                    billing_cycle=billing_cycle,
                    gateway=PaymentMethod.PAYSTACK,
                )

                checkout_url = init_paystack_checkout(
                    request,
                    payment,
                )

                if not checkout_url:
                    raise ValueError(
                        "Paystack did not return a checkout URL."
                    )

                return redirect(checkout_url)

            except Exception as exc:
                if (
                    payment is not None
                    and payment.status != PaymentStatus.SUCCESS
                ):
                    payment.mark_failed(
                        {
                            "error": str(exc),
                            "stage": "provider_subscription_checkout",
                        }
                    )

                messages.error(
                    request,
                    f"Unable to start secure checkout: {exc}",
                )

                return redirect(
                    "provider_workspace:subscription"
                )

        provider.subscription_plan = plan.name
        provider.subscription_status = "active"
        provider.subscription_expires_at = None

        provider.save(
            update_fields=[
                "subscription_plan",
                "subscription_status",
                "subscription_expires_at",
                "updated_at",
            ]
        )

        Notification.send(
            provider.user,
            "system",
            "Provider subscription updated",
            (
                "Your provider subscription is now "
                f"{provider.subscription_plan}."
            ),
            metadata={
                "service_provider_id": provider.id,
                "provider_subscription_plan_id": plan.id,
                "workspace": "provider",
            },
        )

        messages.success(
            request,
            (
                f"{plan.name} has been activated "
                "for your provider account."
            ),
        )

        return redirect(
            "provider_workspace:subscription"
        )

    provider_payments = (
        PaymentTransaction.objects
        .filter(
            user=provider.user,
            checkout_data__purpose="provider_subscription",
        )
        .order_by("-created_at")[:20]
    )

    context = _workspace_context(
        provider,
        "subscription",
    )

    context.update(
        {
            "plans": plans,
            "current_plan": current_plan,
            "provider_payments": provider_payments,
            "subscription_status_display": (
                provider.get_subscription_status_display()
            ),
        }
    )

    return render(
        request,
        "installers/workspace/subscription.html",
        context,
    )
