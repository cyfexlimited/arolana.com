from django import template
from django.db import DatabaseError, OperationalError

from installers.models import ServiceMarketplaceHomepageSection


register = template.Library()


@register.inclusion_tag("installers/partials/homepage_service_section.html", takes_context=True)
def service_marketplace_homepage_section(context):
    try:
        section = ServiceMarketplaceHomepageSection.objects.filter(is_active=True).first()
    except (OperationalError, DatabaseError):
        section = None
    return {"section": section, "request": context.get("request")}
