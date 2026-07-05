from django import template
from django.db import DatabaseError, OperationalError

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
