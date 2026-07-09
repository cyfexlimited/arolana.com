from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from notifications.models import Notification
from products.models import Product

from .forms import (
    ProviderAvailabilityForm,
    ProviderRegistrationForm,
    ProviderServiceForm,
    ProviderWorkspaceProfileForm,
    ProviderWorkspaceSettingsForm,
    ServicePortfolioForm,
    ServiceProjectMediaForm,
    ServiceQuoteRequestForm,
    ServiceReviewForm,
)
from .models import (
    ProviderSubscriptionPlan,
    ProviderKYCDocument,
    ProviderProfileChangeRequest,
    SavedServiceProject,
    ServiceCategory,
    ServicePortfolio,
    ServiceProviderProfile,
    ServiceQuoteRequest,
)
from .project_services import (
    ProjectEntitlementService,
    notify_project_submitted,
    record_project_event,
    resolve_project_gallery_media,
)
from .services import (
    filter_public_providers,
    notify_staff_service_quote,
    submit_provider_kyc,
    submit_provider_profile,
    update_provider_profile,
)


def _provider_workspace(request):
    return get_object_or_404(
        ServiceProviderProfile.objects.select_related("user"),
        user=request.user,
    )


def _workspace_context(provider, active):
    return {
        "provider": provider,
        "workspace_active": active,
        "profile_steps": provider.profile_completion_items,
        "profile_missing_steps": provider.profile_missing_steps,
        "project_entitlements": ProjectEntitlementService(provider).payload(),
    }


def directory(request):
    providers = filter_public_providers(request.GET)
    categories = (
        ServiceCategory.objects.filter(is_active=True)
        .annotate(provider_count=Count("provider_services__provider", distinct=True))
        .order_by("name")
    )
    page = Paginator(providers, 18).get_page(request.GET.get("page"))
    return render(request, "installers/directory.html", {
        "page_obj": page,
        "providers": page.object_list,
        "categories": categories,
        "provider_types": ServiceProviderProfile.PROVIDER_TYPES,
        "seo_title": "Verified Installers & Engineers | Arolana",
        "seo_description": "Find verified installers, repair engineers, technicians, trainers, and consultants on Arolana.",
    })


def category_detail(request, slug):
    category = get_object_or_404(ServiceCategory, slug=slug, is_active=True)
    providers = filter_public_providers({**request.GET.dict(), "category": category.slug})
    projects = ServicePortfolio.objects.public().optimized().filter(service_category=category)[:8]
    page = Paginator(providers, 18).get_page(request.GET.get("page"))
    return render(request, "installers/category_detail.html", {
        "category": category,
        "page_obj": page,
        "providers": page.object_list,
        "projects": projects,
        "seo_title": f"Verified {category.name} in Nigeria | Arolana",
        "seo_description": category.description or f"Find trusted and verified {category.name.lower()} on Arolana.",
    })


def provider_detail(request, slug):
    provider = get_object_or_404(
        ServiceProviderProfile.objects.public()
        .select_related("user")
        .prefetch_related(
            "services__category",
            "portfolio_items__media_items",
            "portfolio_items__service_category",
            "reviews__customer",
        ),
        slug=slug,
    )
    return render(request, "installers/provider_detail.html", {
        "provider": provider,
        "services": provider.services.filter(is_active=True).select_related("category"),
        "portfolio_items": ServicePortfolio.objects.public().optimized().filter(provider=provider),
        "reviews": provider.reviews.filter(is_approved=True).select_related("customer")[:20],
        "review_form": ServiceReviewForm(),
        "seo_title": f"{provider.business_name} - Verified {provider.get_provider_type_display()} | Arolana",
        "seo_description": provider.description[:160],
    })


@login_required
def register_provider(request):
    instance = ServiceProviderProfile.objects.filter(user=request.user).first()
    if request.method == "POST":
        form = ProviderRegistrationForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            provider = form.save(commit=False)
            provider.user = request.user
            provider.save()
            submit_provider_profile(provider)
            messages.success(request, "Your provider profile was saved and sent for Arolana verification.")
            return redirect("installers:provider_dashboard")
    else:
        initial = {
            "contact_person": request.user.get_full_name(),
            "email": request.user.email,
            "phone_number": getattr(request.user, "phone_number", "") or "",
        }
        form = ProviderRegistrationForm(instance=instance, initial=initial)
    return render(request, "installers/provider_form.html", {"form": form, "provider": instance})


@login_required
def provider_dashboard(request):
    provider = get_object_or_404(ServiceProviderProfile, user=request.user)
    if not provider.approval_allows_dashboard:
        return render(request, "installers/provider_pending.html", {
            "provider": provider,
            "kyc_documents": provider.kyc_documents.filter(is_active=True),
            "change_requests": provider.profile_change_requests.all()[:10],
        })

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_availability":
            availability = request.POST.get("availability_status")
            allowed = {value for value, _label in ServiceProviderProfile._meta.get_field("availability_status").choices}
            if availability in allowed:
                provider.availability_status = availability
                provider.availability_note = request.POST.get("availability_note", "")[:300]
                provider.save(update_fields=["availability_status", "availability_note", "updated_at"])
                messages.success(request, "Availability updated.")
            else:
                messages.error(request, "Select a valid availability status.")
            return redirect("installers:provider_dashboard")

        if action == "update_quote_status":
            quote = get_object_or_404(ServiceQuoteRequest, pk=request.POST.get("quote_id"), provider=provider)
            next_status = request.POST.get("status")
            allowed_statuses = {value for value, _label in ServiceQuoteRequest.STATUS_CHOICES}
            if next_status in allowed_statuses:
                quote.status = next_status
                quote.provider_note = request.POST.get("provider_note", quote.provider_note)[:2000]
                if next_status == "accepted" and not quote.accepted_at:
                    quote.accepted_at = timezone.now()
                if next_status == "completed" and not quote.completed_at:
                    quote.completed_at = timezone.now()
                quote.save(update_fields=["status", "provider_note", "accepted_at", "completed_at", "updated_at"])
                messages.success(request, "Service request updated.")
            else:
                messages.error(request, "Select a valid service request status.")
            return redirect("installers:provider_dashboard")

    quote_requests = provider.quote_requests.select_related("product", "category").order_by("-created_at")
    active_jobs = quote_requests.filter(status__in=["assigned", "accepted", "on_the_way", "in_progress"])
    pending_jobs = quote_requests.filter(status__in=["new", "under_review", "assigned"])
    completed_jobs = quote_requests.filter(status__in=["completed", "closed"])
    notifications = Notification.objects.filter(user=request.user).order_by("-created_at")[:8]
    subscription_plans = ProviderSubscriptionPlan.objects.filter(is_active=True).order_by("display_order", "price_monthly")

    return render(request, "installers/provider_dashboard.html", {
        "provider": provider,
        "services": provider.services.select_related("category"),
        "portfolio_items": provider.portfolio_items.all(),
        "project_entitlements": ProjectEntitlementService(provider).payload(),
        "quote_requests": quote_requests[:30],
        "active_jobs": active_jobs[:8],
        "pending_jobs": pending_jobs[:8],
        "completed_jobs": completed_jobs[:8],
        "quote_request_count": quote_requests.count(),
        "pending_job_count": pending_jobs.count(),
        "active_job_count": active_jobs.count(),
        "completed_job_count": completed_jobs.count(),
        "urgent_job_count": quote_requests.filter(Q(urgency="urgent") | Q(urgency="emergency")).exclude(status__in=["completed", "closed", "cancelled"]).count(),
        "kyc_documents": provider.kyc_documents.filter(is_active=True),
        "change_requests": provider.profile_change_requests.all()[:8],
        "notifications": notifications,
        "subscription_plans": subscription_plans,
        "availability_choices": ServiceProviderProfile._meta.get_field("availability_status").choices,
        "quote_status_choices": ServiceQuoteRequest.STATUS_CHOICES,
    })


@login_required
def workspace_dashboard(request):
    """Canonical provider operations dashboard at /dashboard/provider/."""
    provider = _provider_workspace(request)
    if not provider.approval_allows_dashboard:
        return redirect("installers:provider_dashboard")
    quotes = provider.quote_requests.all()
    projects = provider.portfolio_items.all()
    notifications = Notification.objects.filter(user=request.user, is_archived=False)
    context = _workspace_context(provider, "dashboard")
    context.update({
        "cards": {
            "services": provider.services.filter(is_active=True).count(),
            "projects": projects.count(),
            "approved_projects": provider.approved_project_count,
            "project_media": projects.aggregate(total=Count("media_items"))["total"] or 0,
            "views": provider.project_views_count,
            "video_views": provider.project_video_views_count,
            "leads": provider.project_leads_count,
            "quotes": quotes.count(),
            "active_jobs": quotes.filter(status__in=["assigned", "accepted", "on_the_way", "in_progress"]).count(),
            "completed_jobs": quotes.filter(status__in=["completed", "closed"]).count(),
            "reviews": provider.total_reviews,
            "unread_notifications": notifications.filter(is_read=False).count(),
        },
        "recent_projects": projects.select_related("service_category").order_by("-updated_at")[:4],
        "recent_jobs": quotes.select_related("category", "product").order_by("-updated_at")[:5],
        "recent_notifications": notifications.order_by("-created_at")[:5],
    })
    return render(request, "installers/workspace/dashboard.html", context)


@login_required
def workspace_profile(request):
    provider = _provider_workspace(request)
    form = ProviderWorkspaceProfileForm(request.POST or None, instance=provider)
    if request.method == "POST" and request.POST.get("action") == "profile" and form.is_valid():
        try:
            provider, change = update_provider_profile(
                provider,
                form.cleaned_data,
                user=request.user,
            )
        except Exception as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                "Sensitive changes were submitted for approval." if change else "Profile updated.",
            )
            return redirect("provider_workspace:profile")

    if request.method == "POST" and request.POST.get("action") == "media":
        field_name = request.POST.get("field_name")
        upload = request.FILES.get("file")
        allowed_fields = {"profile_image", "business_logo", "business_banner"}
        if field_name not in allowed_fields or not upload:
            messages.error(request, "Choose a valid provider image.")
        elif provider.approval_allows_dashboard:
            if provider.sensitive_update_locked:
                messages.error(
                    request,
                    f"Sensitive profile changes are locked until {provider.sensitive_update_available_at:%Y-%m-%d}.",
                )
            elif provider.profile_change_requests.filter(status=ProviderProfileChangeRequest.STATUS_PENDING).exists():
                messages.error(request, "A profile change is already awaiting Arolana approval.")
            else:
                ProviderProfileChangeRequest.objects.create(
                    provider=provider,
                    requested_by=request.user,
                    old_values={field_name: getattr(getattr(provider, field_name), "name", "")},
                    proposed_values={field_name: upload.name},
                    sensitive_fields=[field_name],
                    proposed_file=upload,
                    proposed_file_field=field_name,
                )
                messages.success(request, "Provider image submitted for Arolana approval.")
                return redirect("provider_workspace:profile")
        else:
            setattr(provider, field_name, upload)
            provider.save(update_fields=[field_name, "updated_at"])
            messages.success(request, "Provider image saved.")
            return redirect("provider_workspace:profile")

    context = _workspace_context(provider, "profile")
    context.update({
        "form": form,
        "pending_changes": provider.profile_change_requests.filter(
            status=ProviderProfileChangeRequest.STATUS_PENDING
        ),
    })
    return render(request, "installers/workspace/profile.html", context)


@login_required
def workspace_services(request, service_id=None):
    provider = _provider_workspace(request)
    service = get_object_or_404(provider.services, pk=service_id) if service_id else None
    form = ProviderServiceForm(request.POST or None, instance=service)
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "delete" and service:
            service.is_active = False
            service.save(update_fields=["is_active", "updated_at"])
            messages.success(request, "Service deactivated. Historical requests remain intact.")
            return redirect("provider_workspace:services")
        if form.is_valid():
            offering = form.save(commit=False)
            offering.provider = provider
            offering.save()
            messages.success(request, "Service offering saved.")
            return redirect("provider_workspace:services")
    context = _workspace_context(provider, "services")
    context.update({
        "services": provider.services.select_related("category"),
        "form": form,
        "editing_service": service,
    })
    return render(request, "installers/workspace/services.html", context)


@login_required
def workspace_availability(request):
    provider = _provider_workspace(request)
    form = ProviderAvailabilityForm(request.POST or None, instance=provider)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Coverage and availability updated.")
        return redirect("provider_workspace:availability")
    context = _workspace_context(provider, "availability")
    context["form"] = form
    return render(request, "installers/workspace/form_page.html", {
        **context,
        "page_title": "Coverage & Availability",
        "page_subtitle": "Control where and when customers can request your services.",
        "submit_label": "Save availability",
    })


@login_required
def workspace_kyc(request):
    provider = _provider_workspace(request)
    if request.method == "POST":
        created = 0
        for document_type, _label in ProviderKYCDocument.DOCUMENT_TYPES:
            upload = request.FILES.get(document_type)
            if upload:
                ProviderKYCDocument.objects.create(
                    provider=provider,
                    document_type=document_type,
                    file=upload,
                )
                created += 1
        if created:
            submit_provider_kyc(provider)
            messages.success(request, "KYC documents submitted for Arolana review.")
            return redirect("provider_workspace:kyc")
        messages.error(request, "Choose at least one KYC document.")
    context = _workspace_context(provider, "kyc")
    context["documents"] = provider.kyc_documents.filter(is_active=True)
    return render(request, "installers/workspace/kyc.html", context)


@login_required
def workspace_settings(request):
    provider = _provider_workspace(request)
    form = ProviderWorkspaceSettingsForm(request.POST or None, instance=provider)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Provider settings saved.")
        return redirect("provider_workspace:settings")
    context = _workspace_context(provider, "settings")
    context["form"] = form
    return render(request, "installers/workspace/form_page.html", {
        **context,
        "page_title": "Provider Settings",
        "page_subtitle": "Manage support contacts, payout details, language, and notifications.",
        "submit_label": "Save settings",
    })


@login_required
def workspace_analytics(request):
    provider = _provider_workspace(request)
    projects = provider.portfolio_items.all()
    context = _workspace_context(provider, "analytics")
    context.update({
        "totals": projects.aggregate(
            views=Sum("views_count"),
            video_views=Sum("video_views_count"),
            product_clicks=Sum("product_click_count"),
            provider_clicks=Sum("provider_click_count"),
            leads=Sum("quote_requests_count"),
            shares=Sum("shares_count"),
            saves=Sum("saves_count"),
        ),
        "projects": projects.order_by("-views_count")[:12],
    })
    return render(request, "installers/workspace/analytics.html", context)


@login_required
def workspace_notifications(request):
    provider = _provider_workspace(request)
    notifications = Notification.objects.filter(user=request.user, is_archived=False).order_by("-created_at")
    if request.method == "POST":
        notifications.filter(is_read=False).update(is_read=True)
        return redirect("provider_workspace:notifications")
    context = _workspace_context(provider, "notifications")
    context["notifications"] = notifications[:100]
    return render(request, "installers/workspace/notifications.html", context)


@login_required
def add_provider_service(request):
    provider = get_object_or_404(ServiceProviderProfile, user=request.user)
    form = ProviderServiceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        service = form.save(commit=False)
        service.provider = provider
        service.save()
        messages.success(request, "Service added.")
        return redirect("installers:provider_dashboard")
    return render(request, "installers/simple_form.html", {"form": form, "title": "Add service"})


@login_required
def add_portfolio(request):
    provider = get_object_or_404(ServiceProviderProfile, user=request.user)
    entitlement = ProjectEntitlementService(provider).can_create_project()
    if not entitlement.allowed:
        messages.error(request, entitlement.message)
        return redirect("installers:provider_projects")
    form = ServicePortfolioForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        portfolio = form.save(commit=False)
        portfolio.provider = provider
        portfolio.created_by = request.user
        portfolio.approval_status = ServicePortfolio.STATUS_DRAFT
        portfolio.save()
        form.instance = portfolio
        form.save()
        messages.success(request, "Portfolio project added.")
        return redirect("installers:provider_project_edit", project_id=portfolio.id)
    return render(request, "installers/project_form.html", {
        "form": form,
        "title": "Add completed project",
        "provider": provider,
        "entitlements": ProjectEntitlementService(provider).payload(),
    })


def projects_directory(request):
    projects = ServicePortfolio.objects.public().optimized()
    query = (request.GET.get("q") or "").strip()
    if query:
        projects = projects.filter(
            Q(title__icontains=query)
            | Q(short_summary__icontains=query)
            | Q(provider__business_name__icontains=query)
            | Q(service_category__name__icontains=query)
            | Q(city__icontains=query)
            | Q(state__icontains=query)
            | Q(project_products__product__name__icontains=query)
        ).distinct()
    filters = {
        "service_category__slug": request.GET.get("category"),
        "country__iexact": request.GET.get("country"),
        "state__iexact": request.GET.get("state"),
        "city__iexact": request.GET.get("city"),
        "project_type": request.GET.get("project_type"),
        "project_products__product_id": request.GET.get("product"),
    }
    for key, value in filters.items():
        if value:
            projects = projects.filter(**{key: value})
    ordering = {
        "popular": "-views_count",
        "watched": "-video_views_count",
        "requested": "-quote_requests_count",
        "latest": "-published_at",
    }.get(request.GET.get("sort"), "-is_featured")
    projects = projects.order_by(ordering, "-published_at")
    page = Paginator(projects, 18).get_page(request.GET.get("page"))
    categories = ServiceCategory.objects.filter(
        is_active=True,
        projects__approval_status=ServicePortfolio.STATUS_APPROVED,
        projects__is_active=True,
    ).annotate(project_count=Count("projects", distinct=True)).distinct()
    return render(request, "installers/projects_directory.html", {
        "projects": page.object_list,
        "page_obj": page,
        "categories": categories,
        "featured_projects": ServicePortfolio.objects.public().optimized().filter(is_featured=True)[:6],
        "project_types": ServicePortfolio.PROJECT_TYPE_CHOICES,
        "seo_title": "Real Installations & Completed Projects | Arolana",
        "seo_description": "Watch verified installations, completed technical projects, and real professional work on Arolana.",
    })


def project_detail(request, slug):
    project = get_object_or_404(ServicePortfolio.objects.public().optimized(), slug=slug)
    record_project_event(project, "view", request=request, source="web")
    project.refresh_from_db()
    related = ServicePortfolio.objects.public().optimized().filter(
        service_category=project.service_category,
    ).exclude(pk=project.pk)[:6]
    similar_providers = ServiceProviderProfile.objects.public().filter(
        services__category=project.service_category,
    ).exclude(pk=project.provider_id).distinct()[:4]
    return render(request, "installers/project_detail.html", {
        "project": project,
        "media_items": project.public_media,
        "products_used": project.project_products.select_related("product", "product__vendor"),
        "related_projects": related,
        "similar_providers": similar_providers,
        "is_saved": (
            request.user.is_authenticated
            and SavedServiceProject.objects.filter(project=project, user=request.user).exists()
        ),
        "seo_title": f"{project.title} | Arolana Projects",
        "seo_description": project.short_summary or project.description[:160],
    })


@login_required
def save_project(request, slug):
    project = get_object_or_404(ServicePortfolio.objects.public(), slug=slug)
    saved, created = SavedServiceProject.objects.get_or_create(project=project, user=request.user)
    if not created:
        saved.delete()
        if project.saves_count:
            ServicePortfolio.objects.filter(pk=project.pk).update(saves_count=project.saves_count - 1)
        messages.info(request, "Project removed from saved items.")
    else:
        record_project_event(project, "save", request=request, source="web")
        messages.success(request, "Project saved.")
    return redirect(project.get_absolute_url())


@login_required
def provider_projects(request):
    provider = get_object_or_404(ServiceProviderProfile, user=request.user)
    projects = provider.portfolio_items.select_related("service_category").prefetch_related("media_items")
    totals = projects.aggregate(
        views=Sum("views_count"),
        video_views=Sum("video_views_count"),
        leads=Sum("quote_requests_count"),
    )
    return render(request, "installers/provider_projects.html", {
        "provider": provider,
        "projects": projects,
        "entitlements": ProjectEntitlementService(provider).payload(),
        "workspace_active": "projects",
        "profile_steps": provider.profile_completion_items,
        "profile_missing_steps": provider.profile_missing_steps,
        "project_entitlements": ProjectEntitlementService(provider).payload(),
        "totals": totals,
        "status_counts": {
            value: projects.filter(approval_status=value).count()
            for value, _label in ServicePortfolio.APPROVAL_STATUS_CHOICES
        },
    })


@login_required
def provider_project_edit(request, project_id):
    provider = get_object_or_404(ServiceProviderProfile, user=request.user)
    project = get_object_or_404(provider.portfolio_items, pk=project_id)
    form = ServicePortfolioForm(request.POST or None, request.FILES or None, instance=project)
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        if project.approval_status == ServicePortfolio.STATUS_APPROVED:
            project.approval_status = ServicePortfolio.STATUS_PENDING
        project.save()
        form.save()
        action = request.POST.get("action")
        if action == "submit":
            publish_permission = ProjectEntitlementService(provider).can_publish_project()
            if not publish_permission.allowed:
                messages.error(request, publish_permission.message)
            elif project.completion_percent < 60:
                messages.error(request, "Complete the category, location, story, outcome, and media before submission.")
            else:
                project.approval_status = ServicePortfolio.STATUS_PENDING
                project.moderation_notes = ""
                project.save(update_fields=["approval_status", "moderation_notes", "updated_at"])
                notify_project_submitted(project)
                messages.success(request, "Project submitted for Arolana review.")
        else:
            messages.success(request, "Project draft saved.")
        return redirect("installers:provider_project_edit", project_id=project.id)
    return render(request, "installers/project_form.html", {
        "form": form,
        "project": project,
        "provider": provider,
        "title": f"Edit {project.title}",
        "entitlements": ProjectEntitlementService(provider).payload(),
    })


@login_required
def provider_project_media(request, project_id):
    provider = get_object_or_404(ServiceProviderProfile, user=request.user)
    project = get_object_or_404(provider.portfolio_items, pk=project_id)
    media_permission = ProjectEntitlementService(provider).can_add_project_media(project)
    form = ServiceProjectMediaForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if not media_permission.allowed:
            messages.error(request, media_permission.message)
        elif form.is_valid():
            media = form.save(commit=False)
            media.project = project
            try:
                media.save()
            except Exception as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "Media uploaded for Arolana review.")
                return redirect("installers:provider_project_media", project_id=project.id)
    gallery_items = resolve_project_gallery_media(project)
    grouped_media = {
        "before": [item for item in gallery_items if item.media_type == "before_image"],
        "during": [item for item in gallery_items if item.media_type in {"during_image", "progress_image"}],
        "after": [item for item in gallery_items if item.media_type == "after_image"],
        "videos": [item for item in gallery_items if item.kind == "video"],
        "all": gallery_items,
    }
    return render(request, "installers/project_media.html", {
        "provider": provider,
        "project": project,
        "media_items": project.media_items.all(),
        "resolved_media_items": gallery_items,
        "grouped_media": grouped_media,
        "form": form,
        "media_permission": media_permission.as_dict(),
        "entitlements": ProjectEntitlementService(provider).payload(),
        "workspace_active": "projects",
        "profile_steps": provider.profile_completion_items,
        "profile_missing_steps": provider.profile_missing_steps,
        "project_entitlements": ProjectEntitlementService(provider).payload(),
    })


@login_required
def provider_project_analytics(request, project_id):
    provider = get_object_or_404(ServiceProviderProfile, user=request.user)
    project = get_object_or_404(provider.portfolio_items, pk=project_id)
    enabled = ProjectEntitlementService(provider).payload()["analytics_enabled"]
    return render(request, "installers/project_analytics.html", {
        "provider": provider,
        "project": project,
        "analytics_enabled": enabled,
        "conversion_rate": round(project.quote_requests_count / max(project.views_count, 1) * 100, 2),
    })


@login_required
def provider_project_leads(request):
    provider = get_object_or_404(ServiceProviderProfile, user=request.user)
    leads = provider.quote_requests.filter(source_project__isnull=False).select_related("source_project", "source_project__service_category")
    return render(request, "installers/project_leads.html", {
        "provider": provider,
        "leads": leads,
        "entitlements": ProjectEntitlementService(provider).payload(),
        "workspace_active": "project_leads",
        "profile_steps": provider.profile_completion_items,
        "profile_missing_steps": provider.profile_missing_steps,
        "project_entitlements": ProjectEntitlementService(provider).payload(),
    })


def request_quote(request):
    initial = {}
    provider_id = request.GET.get("provider")
    category_id = request.GET.get("category")
    product_id = request.GET.get("product")
    project_id = request.GET.get("project")
    if provider_id:
        initial["provider"] = ServiceProviderProfile.objects.public().filter(pk=provider_id).first()
    if category_id:
        initial["category"] = ServiceCategory.objects.filter(pk=category_id, is_active=True).first()
    if product_id:
        product = Product.objects.filter(pk=product_id, is_active=True, approval_status="approved").first()
        initial["product"] = product
        if product:
            initial["service_needed"] = f"Service support for {product.name}"
    if project_id:
        project = ServicePortfolio.objects.public().filter(pk=project_id).select_related(
            "provider", "service_category"
        ).first()
        if project:
            initial.update({
                "source_project": project,
                "provider": project.provider,
                "category": project.service_category,
                "state": project.state,
                "city": project.city,
                "service_needed": f"Similar project: {project.title}",
                "message": f"I would like a quote for a project similar to “{project.title}”.",
            })
    if request.user.is_authenticated:
        initial.update({
            "name": request.user.get_full_name(),
            "email": request.user.email,
            "phone": getattr(request.user, "phone_number", "") or "",
        })
    form = ServiceQuoteRequestForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        quote = form.save(commit=False)
        if request.user.is_authenticated:
            quote.customer = request.user
        quote.save()
        if quote.source_project:
            record_project_event(quote.source_project, "quote_request", request=request, source="web")
        notify_staff_service_quote(quote)
        if quote.provider:
            Notification.send(
                quote.provider.user,
                "message",
                "New service quote request",
                f"{quote.name} requested {quote.service_needed} in {quote.city}, {quote.state}.",
                link="/dashboard/provider/projects/leads/" if quote.source_project_id else "/dashboard/provider/quote-requests/",
                metadata={
                    "type": "service_quote_request",
                    "target_screen": "ProviderQuoteDetail",
                    "role": "provider",
                    "service_quote_request_id": quote.id,
                    "quote_id": quote.id,
                    "project_id": quote.source_project_id,
                    "product_id": quote.product_id,
                },
                priority=3,
            )
        messages.success(request, "Your request has been sent. A verified professional or Arolana support will contact you.")
        return redirect("installers:quote_success")
    return render(request, "installers/quote_form.html", {"form": form})


def quote_success(request):
    return render(request, "installers/quote_success.html")


@login_required
def submit_review(request, slug):
    provider = get_object_or_404(ServiceProviderProfile.objects.public(), slug=slug)
    form = ServiceReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        review = form.save(commit=False)
        review.provider = provider
        review.customer = request.user
        review.save()
        messages.success(request, "Thank you. Your review will appear after moderation.")
        return redirect(provider.get_absolute_url())
    return render(request, "installers/simple_form.html", {"form": form, "title": f"Review {provider.business_name}"})
