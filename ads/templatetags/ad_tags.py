from django import template
from django.utils import timezone
from django.core.cache import cache
from django.db.models import Q, F
from ads.models import Advertisement, AdBanner, AdCreative, AdPlacement, AdImpression
import random
import logging

logger = logging.getLogger(__name__)
register = template.Library()


@register.inclusion_tag('ads/ad_carousel.html', takes_context=True)
def render_ad_carousel(context, placement, count=5, interval=5000, autoplay='true'):
    """
    Render an ad carousel with multiple ads (creatives, banners, simple ads)
    
    Usage:
        {% load ad_tags %}
        {% render_ad_carousel 'sidebar' count=5 interval=5000 autoplay='true' %}
    
    Args:
        placement (str): Placement slug (sidebar, banner, footer, homepage)
        count (int): Number of ads to display (default: 5)
        interval (int): Auto-play interval in milliseconds (default: 5000)
        autoplay (str): Enable autoplay ('true' or 'false')
    """
    request = context.get('request')
    now = timezone.now()
    
    all_ads = []
    
    # 1. Get Active Creatives (highest priority)
    try:
        creatives = AdCreative.objects.filter(
            is_active=True
        ).select_related('campaign').filter(
            campaign__status='active',
            campaign__approved=True,
            campaign__start_date__lte=now
        ).filter(
            Q(campaign__end_date__isnull=True) | Q(campaign__end_date__gte=now)
        ).order_by('-ab_weight', '?')[:count]
        
        for creative in creatives:
            all_ads.append({
                'object': creative,
                'type': 'creative',
                'id': f'creative-{creative.id}',
                'title': creative.headline,
                'description': creative.description or '',
                'cta_text': creative.cta_text or 'Learn More',
                'url': creative.clickthrough_url,
                'image': creative.image,
                'image_mobile': creative.image_mobile or creative.image,
                'ctr': float(creative.ctr) if creative.ctr else 0,
                'views': creative.impressions or 0,
                'clicks': creative.clicks or 0,
                'creative_type': creative.creative_type,
                'ab_variant': creative.ab_variant,
            })
    except Exception as e:
        logger.error(f"Error fetching creatives: {e}")
    
    # 2. Get Active Banners
    try:
        placement_obj = AdPlacement.objects.filter(
            slug=placement, 
            is_active=True
        ).first()
        
        if placement_obj:
            banners = AdBanner.objects.filter(
                placement=placement_obj,
                is_active=True,
                start_date__lte=now
            ).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=now)
            ).select_related('campaign', 'creative').order_by('-priority', '?')[:count]
            
            for banner in banners:
                all_ads.append({
                    'object': banner,
                    'type': 'banner',
                    'id': f'banner-{banner.id}',
                    'title': banner.title,
                    'description': banner.description or '',
                    'cta_text': banner.cta_text or 'View More',
                    'url': banner.cta_url,
                    'image': banner.image,
                    'image_mobile': banner.image_mobile or banner.image,
                    'ctr': float(banner.ctr) if banner.ctr else 0,
                    'views': banner.impressions or 0,
                    'clicks': banner.clicks or 0,
                    'animation': banner.animation or 'fade',
                })
    except Exception as e:
        logger.error(f"Error fetching banners: {e}")
    
    # 3. Get Simple Advertisements
    try:
        ads = Advertisement.objects.filter(
            placement=placement,
            is_active=True
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=now)
        ).order_by('-is_featured', '-created_at')[:count]
        
        for ad in ads:
            all_ads.append({
                'object': ad,
                'type': 'simple',
                'id': f'ad-{ad.id}',
                'title': ad.title,
                'description': ad.description or '',
                'cta_text': ad.button_text or 'Click Here',
                'url': ad.url,
                'image': ad.image,
                'ctr': float(ad.ctr) if ad.ctr else 0,
                'views': ad.views or 0,
                'clicks': ad.clicks or 0,
                'is_featured': ad.is_featured,
            })
    except Exception as e:
        logger.error(f"Error fetching simple ads: {e}")
    
    # Shuffle and limit to requested count
    random.shuffle(all_ads)
    all_ads = all_ads[:count]
    
    # Track initial impressions
    if request and request.session.session_key:
        for ad in all_ads:
            _track_ad_impression(request, ad['object'], ad['type'])
    
    return {
        'ads': all_ads,
        'placement': placement,
        'interval': int(interval),
        'autoplay': autoplay.lower() == 'true',
        'count': len(all_ads),
        'user': request.user if request else None,
    }


@register.inclusion_tag('ads/advanced_ad.html', takes_context=True)
def render_ad(context, placement):
    """
    Render a single ad for a specific placement with automatic priority selection
    
    Usage:
        {% load ad_tags %}
        {% render_ad 'sidebar' %}
    
    Args:
        placement (str): Placement slug (sidebar, banner, footer, homepage)
    """
    request = context.get('request')
    now = timezone.now()
    
    selected_ad = None
    ad_type = None
    
    try:
        # Priority 1: Active Creatives
        creatives = AdCreative.objects.filter(
            is_active=True
        ).select_related('campaign').filter(
            campaign__status='active',
            campaign__approved=True,
            campaign__start_date__lte=now
        ).filter(
            Q(campaign__end_date__isnull=True) | Q(campaign__end_date__gte=now)
        ).annotate(
            weight=F('ab_weight')
        ).order_by('-weight', '?')
        
        if creatives.exists():
            selected_ad = creatives.first()
            ad_type = 'creative'
        else:
            # Priority 2: Active Banners
            placement_obj = AdPlacement.objects.filter(
                slug=placement, 
                is_active=True
            ).first()
            
            if placement_obj:
                banners = AdBanner.objects.filter(
                    placement=placement_obj,
                    is_active=True,
                    start_date__lte=now
                ).filter(
                    Q(end_date__isnull=True) | Q(end_date__gte=now)
                ).select_related('campaign', 'creative').order_by('-priority', '?')
                
                if banners.exists():
                    selected_ad = banners.first()
                    ad_type = 'banner'
                else:
                    raise AdPlacement.DoesNotExist
            else:
                raise AdPlacement.DoesNotExist
                
            # Priority 3: Simple Ads
            if not selected_ad:
                ads = Advertisement.objects.filter(
                    placement=placement,
                    is_active=True
                ).filter(
                    Q(end_date__isnull=True) | Q(end_date__gte=now)
                ).order_by('-is_featured', '-created_at')
                
                if ads.exists():
                    selected_ad = ads.first()
                    ad_type = 'simple'
    
    except (AdPlacement.DoesNotExist, Exception) as e:
        logger.warning(f"No ads found for placement '{placement}': {e}")
        selected_ad = None
        ad_type = None
    
    # Track impression
    if selected_ad and request:
        _track_ad_impression(request, selected_ad, ad_type)
    
    # Determine format and device
    format_map = {
        'sidebar': 'compact',
        'banner': 'wide',
        'footer': 'small',
        'homepage': 'hero',
    }
    
    device = _detect_device(request)
    
    return {
        'ad': selected_ad,
        'ad_type': ad_type,
        'placement': placement,
        'format': format_map.get(placement, 'standard'),
        'device': device,
        'user': request.user if request else None,
    }


@register.simple_tag(takes_context=True)
def ad_click_url(context, ad_id, ad_type):
    """Generate tracking URL for ad clicks"""
    return f"/ads/track-click/?id={ad_id}&type={ad_type}"


@register.filter
def format_ad_number(value):
    """Format numbers with commas for display"""
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return "0"


@register.filter
def ad_ctr_percentage(views, clicks):
    """Calculate and display CTR percentage"""
    try:
        if int(views) > 0:
            ctr = (int(clicks) / int(views)) * 100
            return f"{ctr:.2f}%"
        return "0.00%"
    except (ValueError, TypeError, ZeroDivisionError):
        return "0.00%"


def _track_ad_impression(request, ad_obj, ad_type):
    """Track lightweight impression counters without writing rows during render."""
    try:
        session_id = getattr(request.session, 'session_key', '') or _get_client_ip(request) or 'anonymous'
        cache_key = f'ad-impression:{ad_type}:{getattr(ad_obj, "pk", "")}:{session_id}'
        if not cache.add(cache_key, True, 300):
            return

        if ad_type == 'creative':
            AdCreative.objects.filter(pk=ad_obj.pk).update(impressions=F('impressions') + 1)
            if ad_obj.campaign_id:
                ad_obj.campaign.__class__.objects.filter(pk=ad_obj.campaign_id).update(impressions=F('impressions') + 1)
        elif ad_type == 'banner':
            AdBanner.objects.filter(pk=ad_obj.pk).update(impressions=F('impressions') + 1)
            if ad_obj.campaign_id:
                ad_obj.campaign.__class__.objects.filter(pk=ad_obj.campaign_id).update(impressions=F('impressions') + 1)
        elif ad_type == 'simple':
            Advertisement.objects.filter(pk=ad_obj.pk).update(views=F('views') + 1)
    except Exception as e:
        logger.error(f"Error tracking impression: {e}")


def _get_client_ip(request):
    """Extract client IP from request"""
    if not request:
        return None
    
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _detect_device(request):
    """Detect device type from user agent"""
    if not request:
        return 'unknown'
    
    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    
    if 'mobile' in user_agent or 'android' in user_agent or 'iphone' in user_agent:
        return 'mobile'
    elif 'tablet' in user_agent or 'ipad' in user_agent:
        return 'tablet'
    else:
        return 'desktop'


def _get_country(request):
    """Get country from request (requires GeoIP setup)"""
    try:
        from django.contrib.gis.geoip2 import GeoIP2
        from django.conf import settings
        
        if hasattr(settings, 'GEOIP_PATH'):
            g = GeoIP2()
            ip = _get_client_ip(request)
            country = g.country(ip)
            return country.get('country_code', 'XX')
    except Exception:
        pass
    
    return 'XX'


# Register filters for template use
register.filter('format_ad_number', format_ad_number)
register.filter('ad_ctr_percentage', ad_ctr_percentage)
