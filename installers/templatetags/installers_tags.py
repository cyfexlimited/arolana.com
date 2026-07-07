from django import template
from django.db import DatabaseError, OperationalError

from core.media_optimization import get_verified_optimized_image_url
from installers.models import ServiceMarketplaceHomepageSection, ServicePortfolio


register = template.Library()


@register.inclusion_tag("installers/partials/homepage_service_section.html", takes_context=True)
def service_marketplace_homepage_section(context):
    try:
        section = ServiceMarketplaceHomepageSection.objects.filter(is_active=True).first()
    except (OperationalError, DatabaseError):
        section = None
    return {"section": section, "request": context.get("request")}


@register.inclusion_tag("installers/partials/homepage_projects_section.html", takes_context=True)
def projects_homepage_section(context):
    try:
        section = ServiceMarketplaceHomepageSection.objects.filter(
            is_active=True,
            projects_enabled=True,
        ).first()
        projects = (
            ServicePortfolio.objects.public()
            .optimized()
            .order_by("-is_featured", "-published_at")[: max(1, min(section.projects_limit, 16))]
            if section
            else ServicePortfolio.objects.none()
        )
    except (OperationalError, DatabaseError):
        section = None
        projects = ServicePortfolio.objects.none()
    return {
        "section": section,
        "projects": projects,
        "request": context.get("request"),
    }


@register.inclusion_tag("installers/partials/homepage_professional_services_projects.html", takes_context=True)
def professional_services_projects_homepage_section(context):
    try:
        section = ServiceMarketplaceHomepageSection.objects.filter(is_active=True).first()
        if section and section.projects_enabled:
            projects = (
                ServicePortfolio.objects.public()
                .optimized()
                .order_by("-is_featured", "-published_at")[: max(1, min(getattr(section, "projects_limit", 10) or 10, 10))]
            )
        else:
            projects = ServicePortfolio.objects.none()
    except (OperationalError, DatabaseError):
        section = None
        projects = ServicePortfolio.objects.none()

    return {
        "section": section,
        "projects": projects,
        "request": context.get("request"),
    }


@register.simple_tag
def project_card_image_url(project):
    """
    Return a project-card image URL that is guaranteed to resolve.

    Provider project images can be uploaded through several paths. Some older
    uploads do not have every optimized derivative yet, so use the verified
    helper to fall back to the original uploaded media instead of rendering a
    broken optimized URL.
    """
    if not project:
        return ""

    featured_media = getattr(project, "featured_media", None)
    provider = getattr(project, "provider", None)
    candidates = [
        (getattr(project, "image", None), "project_card"),
        (getattr(featured_media, "image", None), "project_card"),
        (getattr(project, "video_thumbnail", None), "project_card"),
        (getattr(featured_media, "thumbnail", None), "project_card"),
        (getattr(provider, "business_banner", None), "provider_banner"),
    ]

    for image, preset in candidates:
        if not image:
            continue
        url = get_verified_optimized_image_url(image, preset)
        if url:
            return url

    return ""
