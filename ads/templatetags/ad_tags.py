from django import template
from django.db import models
from django.utils import timezone
from ads.models import AdBanner, AdPlacement
import random

register = template.Library()

@register.inclusion_tag('ads/banner.html', takes_context=True)
def render_ad(context, placement_slug):
    request = context.get('request')
    
    try:
        placement = AdPlacement.objects.get(slug=placement_slug, is_active=True)
    except AdPlacement.DoesNotExist:
        return {'ad': None, 'placement': None}
    
    # Get active banners for this placement
    now = timezone.now()
    banners = AdBanner.objects.filter(
        placement=placement,
        is_active=True,
        campaign__is_active=True
    ).filter(
        models.Q(campaign__start_date__isnull=True) | models.Q(campaign__start_date__lte=now)
    ).filter(
        models.Q(campaign__end_date__isnull=True) | models.Q(campaign__end_date__gte=now)
    ).order_by('-priority', '-created_at')
    
    # Get the first banner
    banner = banners.first()
    
    # Track impression
    if banner:
        banner.increment_impression()
    
    return {
        'ad': banner,
        'placement': placement,
        'request': request
    }
