from django import template
from django.utils import timezone
from ads.models import AdBanner, AdPlacement, AdImpression
import random

register = template.Library()

@register.inclusion_tag('ads/banner.html', takes_context=True)
def render_ad(context, placement_slug, count=1):
    """Render ads for a specific placement"""
    request = context.get('request')
    if not request:
        return {'ads': []}
    
    try:
        placement = AdPlacement.objects.get(slug=placement_slug, is_active=True)
    except AdPlacement.DoesNotExist:
        return {'ads': []}
    
    now = timezone.now()
    
    # Get active banners for this placement
    banners = AdBanner.objects.filter(
        placement=placement,
        is_active=True,
        campaign__status='active',
        campaign__approved=True,
        campaign__start_date__lte=now
    ).exclude(
        campaign__end_date__isnull=False,
        campaign__end_date__lt=now
    ).select_related('campaign', 'placement')
    
    if not banners.exists():
        return {'ads': []}
    
    # Filter banners based on campaign settings
    user = request.user if request.user.is_authenticated else None
    filtered_banners = []
    
    for banner in banners:
        campaign = banner.campaign
        
        # Check budget
        if campaign.spent >= campaign.budget:
            continue
        
        # Check targeting
        if campaign.targeting == 'logged_in' and not user:
            continue
        
        filtered_banners.append(banner)
    
    if not filtered_banners:
        return {'ads': []}
    
    # Select random banner for rotation
    selected_ad = random.choice(filtered_banners)
    
    # Track impression asynchronously (don't wait for response)
    if request.session.session_key:
        try:
            # Check if already tracked today to avoid duplicates
            from datetime import date
            today = date.today()
            existing = AdImpression.objects.filter(
                banner=selected_ad,
                session_id=request.session.session_key,
                timestamp__date=today
            ).exists()
            
            if not existing:
                AdImpression.objects.create(
                    banner=selected_ad,
                    campaign=selected_ad.campaign,
                    user=user,
                    session_id=request.session.session_key,
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
                )
                # Update counts
                selected_ad.impressions += 1
                selected_ad.save()
                selected_ad.campaign.impressions += 1
                selected_ad.campaign.save()
        except Exception as e:
            # Silently fail for tracking errors
            pass
    
    return {'ads': [selected_ad], 'request': request}