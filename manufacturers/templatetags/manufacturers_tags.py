from django import template
from manufacturers.models import Manufacturer

register = template.Library()

@register.simple_tag
def featured_manufacturers(limit=8):
    """Get featured manufacturers"""
    return Manufacturer.objects.filter(is_featured=True, is_active=True)[:limit]

@register.simple_tag
def top_manufacturers(limit=8):
    """Get top manufacturers by sales"""
    return Manufacturer.objects.filter(is_active=True).order_by('-total_sales')[:limit]
