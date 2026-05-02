from django import template
from manufacturers.models import Manufacturer

register = template.Library()

@register.simple_tag
def get_featured_manufacturers(limit=12):
    """Get featured manufacturers for mega menu"""
    return Manufacturer.objects.filter(is_active=True, is_featured=True)[:limit]

@register.simple_tag
def get_all_manufacturers():
    """Get all active manufacturers"""
    return Manufacturer.objects.filter(is_active=True)
