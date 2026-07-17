import re

from django import template
from django.db import DatabaseError, OperationalError
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

from installers.models import ServiceMarketplaceHomepageSection, ServicePortfolio
from installers.project_services import (
    resolve_project_card_media,
    resolve_project_gallery_media,
    resolve_project_hero_media,
)


register = template.Library()


@register.filter(needs_autoescape=True)
def project_rich_text(value, autoescape=True):
    """Render plain project copy as escaped paragraphs and semantic lists."""
    escape = conditional_escape if autoescape else str
    lines = str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output = []
    paragraph = []
    list_items = []

    def flush_paragraph():
        if paragraph:
            output.append(
                '<p class="project-copy-paragraph">{}</p>'.format(
                    " ".join(escape(item) for item in paragraph)
                )
            )
            paragraph.clear()

    def flush_list():
        if list_items:
            output.append(
                '<ul class="project-copy-list">{}</ul>'.format(
                    "".join(f"<li>{escape(item)}</li>" for item in list_items)
                )
            )
            list_items.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        bullet = re.match(r"^(?:[*•-]|\d+[.)])\s+(.+)$", line)
        if bullet:
            flush_paragraph()
            list_items.append(bullet.group(1).strip())
            continue
        flush_list()
        paragraph.append(line)

    flush_paragraph()
    flush_list()
    return mark_safe("".join(output))


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
    return resolve_project_card_media(project).url if project else ""


@register.simple_tag
def project_hero_image_url(project):
    return resolve_project_hero_media(project).url if project else ""


@register.simple_tag
def project_gallery_items(project):
    return [item.as_dict() for item in resolve_project_gallery_media(project)] if project else []


@register.filter
def public_media_count(project):
    if not project:
        return 0
    media = getattr(project, "public_media", [])
    try:
        return len(media)
    except TypeError:
        return media.count()
