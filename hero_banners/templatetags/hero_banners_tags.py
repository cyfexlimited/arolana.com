from django import template
from hero_banners.models import HeroBanner

register = template.Library()

@register.inclusion_tag('hero_banners/carousel.html', takes_context=True)
def hero_carousel(context):
    request = context.get('request')
    
    # Get all active banners
    banners = HeroBanner.objects.filter(is_active=True).order_by('display_order')
    
    return {
        'banners': banners,
        'request': request,
    }